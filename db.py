"""Локальная база (SQLite, только stdlib): профили игроков, очки, звания, статистика, история.
Файл базы: $DB_PATH или $DATA_DIR/games.db (по умолчанию ./data/games.db). На хосте смонтируй туда том,
иначе после редеплоя база обнулится."""
import os
import sqlite3
import time
from pathlib import Path

# ───────────── звания: (порог очков, название, эмодзи) ─────────────
RANKS = [
    (0, "Новичок", "🥚"),
    (100, "Любитель", "🌱"),
    (250, "Игрок", "🎲"),
    (500, "Знаток", "🥉"),
    (900, "Мастер", "🥈"),
    (1400, "Эксперт", "🥇"),
    (2100, "Грандмастер", "💎"),
    (3000, "Легенда", "👑"),
]
WIN_BASE, WIN_PER_LOSER, LOSS, DRAW = 10, 10, -10, 5
RULES = [
    "🏆 Победа: от +20 (чем больше соперников, тем больше очков)",
    "💀 Поражение: −10 (ниже нуля очки не падают)",
    "🤝 Ничья: +5",
    "🔥 Серия побед: с 3-й подряд +5, с 5-й подряд +10 за каждую",
    "Прерванные из-за неактивности партии не считаются",
]

_c: sqlite3.Connection | None = None


def init(path: str | None = None) -> None:
    global _c
    path = path or os.getenv("DB_PATH") or str(Path(os.getenv("DATA_DIR") or Path(__file__).parent / "data") / "games.db")
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    _c = sqlite3.connect(path, check_same_thread=False)
    _c.row_factory = sqlite3.Row
    _c.execute("PRAGMA journal_mode=WAL")
    _c.executescript("""
    CREATE TABLE IF NOT EXISTS players(
        uid INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '', username TEXT,
        points INTEGER NOT NULL DEFAULT 0, played INTEGER NOT NULL DEFAULT 0,
        wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0, draws INTEGER NOT NULL DEFAULT 0,
        streak INTEGER NOT NULL DEFAULT 0, best_streak INTEGER NOT NULL DEFAULT 0,
        created INTEGER NOT NULL, last_seen INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_players_username ON players(username COLLATE NOCASE);
    CREATE TABLE IF NOT EXISTS stats(
        uid INTEGER NOT NULL, game TEXT NOT NULL,
        played INTEGER NOT NULL DEFAULT 0, wins INTEGER NOT NULL DEFAULT 0,
        losses INTEGER NOT NULL DEFAULT 0, draws INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(uid, game));
    CREATE TABLE IF NOT EXISTS history(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, chat_id INTEGER, game TEXT NOT NULL,
        uid INTEGER NOT NULL, result TEXT NOT NULL, delta INTEGER NOT NULL, n INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_history_uid ON history(uid, id DESC);
    CREATE TABLE IF NOT EXISTS chat_players(chat_id INTEGER NOT NULL, uid INTEGER NOT NULL, PRIMARY KEY(chat_id, uid));
    """)
    _c.commit()


def conn() -> sqlite3.Connection:
    if _c is None:
        init()
    return _c


# ───────────── звания ─────────────
def rank_info(points: int) -> dict:
    idx = max(i for i, r in enumerate(RANKS) if points >= r[0])
    cur = RANKS[idx]
    nxt = RANKS[idx + 1] if idx + 1 < len(RANKS) else None
    return {"idx": idx, "name": cur[1], "emoji": cur[2], "min": cur[0],
            "next_min": nxt[0] if nxt else None, "next_name": nxt[1] if nxt else None, "next_emoji": nxt[2] if nxt else None,
            "left": nxt[0] - points if nxt else 0,
            "progress": round((points - cur[0]) / (nxt[0] - cur[0]), 3) if nxt else 1.0}


# ───────────── игроки ─────────────
def touch(uid: int, name: str = "", username: str | None = None) -> None:
    now = int(time.time())
    c = conn()
    with c:
        c.execute("INSERT INTO players(uid,name,username,created,last_seen) VALUES(?,?,?,?,?) "
                  "ON CONFLICT(uid) DO UPDATE SET name=CASE WHEN excluded.name<>'' THEN excluded.name ELSE name END, "
                  "username=COALESCE(excluded.username,username), last_seen=excluded.last_seen",
                  (uid, name or "", (username or None), now, now))


def find_by_username(username: str) -> int | None:
    r = conn().execute("SELECT uid FROM players WHERE username=? COLLATE NOCASE", (username.lstrip("@"),)).fetchone()
    return r["uid"] if r else None


def _badges(p: dict, games: dict, place) -> list:
    b = []
    if p["wins"] >= 1:
        b.append({"e": "🎯", "t": "Первая победа"})
    if p["played"] >= 10:
        b.append({"e": "🔟", "t": "10 партий"})
    if p["played"] >= 100:
        b.append({"e": "💯", "t": "Заядлый игрок"})
    if p["best_streak"] >= 3:
        b.append({"e": "🔥", "t": "Серия из 3 побед"})
    if p["best_streak"] >= 5:
        b.append({"e": "⚡", "t": "Неудержимый: 5 побед подряд"})
    if len([g for g in games.values() if g["played"]]) >= 4:
        b.append({"e": "🎰", "t": "Универсал: сыграл во все игры"})
    for g, s in games.items():
        if s["wins"] >= 5:
            b.append({"e": "🏅", "t": f"Мастер игры: {g}"})
    if place == 1 and p["played"] >= 5:
        b.append({"e": "👑", "t": "№1 в рейтинге"})
    return b


def get_profile(uid: int, name: str = "") -> dict:
    c = conn()
    r = c.execute("SELECT * FROM players WHERE uid=?", (uid,)).fetchone()
    p = dict(r) if r else {"uid": uid, "name": name or "Игрок", "username": None, "points": 0, "played": 0, "wins": 0,
                           "losses": 0, "draws": 0, "streak": 0, "best_streak": 0, "created": 0, "last_seen": 0}
    p["name"] = p["name"] or name or "Игрок"
    p["rank"] = rank_info(p["points"])
    p["winrate"] = round(100 * p["wins"] / p["played"]) if p["played"] else 0
    games = {g["game"]: {k: g[k] for k in ("played", "wins", "losses", "draws")}
             for g in c.execute("SELECT * FROM stats WHERE uid=?", (uid,))}
    p["games"] = games
    p["recent"] = [x["result"] for x in c.execute("SELECT result FROM history WHERE uid=? ORDER BY id DESC LIMIT 10", (uid,))]
    if p["played"]:
        p["place"] = c.execute("SELECT COUNT(*)+1 FROM players WHERE played>0 AND points>?", (p["points"],)).fetchone()[0]
        p["total"] = c.execute("SELECT COUNT(*) FROM players WHERE played>0").fetchone()[0]
    else:
        p["place"], p["total"] = None, c.execute("SELECT COUNT(*) FROM players WHERE played>0").fetchone()[0]
    p["badges"] = _badges(p, games, p["place"])
    return p


def top(chat_id: int | None = None, limit: int = 10, game: str | None = None) -> list:
    """Топ по очкам (или по победам в конкретной игре). chat_id — только те, кто играл в этом чате."""
    where, args = [], []
    if chat_id is not None:
        where.append("p.uid IN (SELECT uid FROM chat_players WHERE chat_id=?)")
        args.append(chat_id)
    if game:
        q = ("SELECT p.uid,p.name,p.points,s.played,s.wins,s.losses,s.draws FROM players p JOIN stats s ON s.uid=p.uid AND s.game=? "
             + ("WHERE " + " AND ".join(where) + " " if where else "") + "ORDER BY s.wins DESC, s.played ASC, p.points DESC LIMIT ?")
        rows = conn().execute(q, [game, *args, limit]).fetchall()
    else:
        where.append("p.played>0")
        q = ("SELECT p.uid,p.name,p.points,p.played,p.wins,p.losses,p.draws FROM players p WHERE " + " AND ".join(where)
             + " ORDER BY p.points DESC, p.wins DESC, p.played ASC LIMIT ?")
        rows = conn().execute(q, [*args, limit]).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        ri = rank_info(d["points"])
        d["rank_emoji"], d["rank_name"] = ri["emoji"], ri["name"]
        out.append(d)
    return out


# ───────────── запись результата партии ─────────────
def win_points(n_players: int, n_winners: int) -> int:
    return round(WIN_BASE + WIN_PER_LOSER * (n_players - 1) / max(1, n_winners))


def streak_bonus(streak: int) -> int:
    return 10 if streak >= 5 else 5 if streak >= 3 else 0


def record_game(chat_id, game: str, players: list, winners: list, names: dict | None = None) -> dict:
    """Записывает итог партии. Возвращает {uid: {result, delta, points, rank, up, streak}}."""
    players = list(dict.fromkeys(players))
    n = len(players)
    if n < 2:
        return {}
    names = names or {}
    wset = set(winners) & set(players)
    draw = not wset or len(wset) == n
    now = int(time.time())
    c, out = conn(), {}
    with c:
        for uid in players:
            c.execute("INSERT OR IGNORE INTO players(uid,name,created,last_seen) VALUES(?,?,?,?)", (uid, names.get(uid, ""), now, now))
            if names.get(uid):
                c.execute("UPDATE players SET name=? WHERE uid=?", (names[uid], uid))
            pts, streak, best = c.execute("SELECT points,streak,best_streak FROM players WHERE uid=?", (uid,)).fetchone()
            if draw:
                res, delta, new_streak = "d", DRAW, streak
            elif uid in wset:
                new_streak = streak + 1
                res, delta = "w", win_points(n, len(wset)) + streak_bonus(new_streak)
            else:
                res, delta, new_streak = "l", LOSS, 0
            new_pts = max(0, pts + delta)
            delta = new_pts - pts
            col = {"w": "wins", "l": "losses", "d": "draws"}[res]
            c.execute(f"UPDATE players SET points=?, played=played+1, {col}={col}+1, streak=?, best_streak=?, last_seen=? WHERE uid=?",
                      (new_pts, new_streak, max(best, new_streak), now, uid))
            c.execute("INSERT OR IGNORE INTO stats(uid,game) VALUES(?,?)", (uid, game))
            c.execute(f"UPDATE stats SET played=played+1, {col}={col}+1 WHERE uid=? AND game=?", (uid, game))
            c.execute("INSERT INTO history(ts,chat_id,game,uid,result,delta,n) VALUES(?,?,?,?,?,?,?)", (now, chat_id, game, uid, res, delta, n))
            if chat_id is not None:
                c.execute("INSERT OR IGNORE INTO chat_players(chat_id,uid) VALUES(?,?)", (chat_id, uid))
            before, after = rank_info(pts), rank_info(new_pts)
            out[uid] = {"result": res, "delta": delta, "points": new_pts, "streak": new_streak,
                        "rank": {"name": after["name"], "emoji": after["emoji"]}, "up": after["idx"] > before["idx"]}
    return out
