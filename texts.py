"""Тексты для чата (HTML для Telegram): профиль, топ, звания, помощь, итоги очков."""
import html

import db
from games import REGISTRY

e = html.escape
ICON = {"w": "🟢", "l": "🔴", "d": "🟡"}
MEDALS = ["🥇", "🥈", "🥉"]


def bar(frac: float, n: int = 10) -> str:
    k = round(max(0.0, min(1.0, frac)) * n)
    return "▰" * k + "▱" * (n - k)


def profile_text(p: dict) -> str:
    r = p["rank"]
    lines = [f"👤 <b>{e(p['name'])}</b>" + (f"  <i>@{e(p['username'])}</i>" if p.get("username") else ""),
             f"{r['emoji']} Звание: <b>{r['name']}</b>",
             f"⭐ Очки: <b>{p['points']}</b>"]
    if r["next_min"] is not None:
        lines.append(f"{bar(r['progress'])} до «{r['next_name']}» {r['next_emoji']} — {r['left']}")
    else:
        lines.append("👑 Высшее звание достигнуто")
    if not p["played"]:
        lines.append("\nЕщё не сыграно ни одной партии. Напиши «игра дурак» и вперёд!")
        return "\n".join(lines)
    lines.append(f"\n🎮 Сыграно: <b>{p['played']}</b> · 🏆 Побед: <b>{p['wins']}</b> · 💀 Поражений: <b>{p['losses']}</b>"
                 + (f" · 🤝 Ничьих: <b>{p['draws']}</b>" if p["draws"] else ""))
    lines.append(f"📊 Процент побед: <b>{p['winrate']}%</b>")
    lines.append(f"🔥 Серия побед: <b>{p['streak']}</b> (рекорд {p['best_streak']})")
    if p.get("place"):
        lines.append(f"🌍 Место в рейтинге: <b>#{p['place']}</b> из {p['total']}")
    gl = [f"{REGISTRY[g]['emoji']} {REGISTRY[g]['title']}: {s['played']} игр, {s['wins']} поб." for g, s in p["games"].items() if g in REGISTRY and s["played"]]
    if gl:
        lines.append("\n<b>По играм</b>\n" + "\n".join(gl))
    if p["recent"]:
        lines.append("\nПоследние: " + "".join(ICON[x] for x in p["recent"]))
    if p["badges"]:
        lines.append("🎖 " + " ".join(b["e"] for b in p["badges"]) + "  <i>— значки</i>")
    return "\n".join(lines)


def top_text(rows: list, scope: str, game: str | None = None) -> str:
    if game:
        head = f"{REGISTRY[game]['emoji']} <b>Топ по победам: {REGISTRY[game]['title']}</b> ({scope})"
    else:
        head = f"🏆 <b>Рейтинг игроков</b> ({scope})"
    if not rows:
        return head + "\n\nПока никто не сыграл. Напиши «игра дурак» — и ты будешь первым!"
    out = [head, ""]
    for i, r in enumerate(rows):
        pos = MEDALS[i] if i < 3 else f"{i + 1}."
        tail = f"{r['wins']} поб. из {r['played']}" if game else f"{r['points']} ⭐ · {r['wins']}/{r['played']} поб."
        out.append(f"{pos} {r.get('rank_emoji', '')} <b>{e(r['name'] or '?')}</b> — {tail}")
    return "\n".join(out)


def ranks_text() -> str:
    lines = ["🏅 <b>Звания</b>"] + [f"{em} {name} — от {pts}" for pts, name, em in db.RANKS]
    return "\n".join(lines) + "\n\n⭐ <b>Как начисляются очки</b>\n" + "\n".join(db.RULES)


def help_text() -> str:
    games = "\n".join(f"{g['emoji']} <b>игра {k_ru}</b> — {g['title']}, {g['min']}–{g['max']} игроков"
                      for (k_ru, g) in [("дурак", REGISTRY["durak"]), ("блекджек", REGISTRY["blackjack"]),
                                        ("покер", REGISTRY["poker"]), ("тетрис", REGISTRY["tetris"])])
    return ("🎮 <b>Игровой бот</b>\n\n" + games +
            "\n\n<b>Профиль и очки</b>\n"
            "👤 <b>профиль</b> / <b>кто я</b> / <b>моя стата</b> — твоя карточка: очки, звание, победы\n"
            "👥 <b>профиль</b> ответом на чужое сообщение или <b>профиль @ник</b> — карточка другого игрока\n"
            "🏆 <b>топ</b> / <b>рейтинг</b> — лидеры чата; <b>топ дурак</b> — лидеры по игре\n"
            "🏅 <b>звания</b> — все звания и как начисляются очки\n"
            "❓ <b>помощь</b> / <b>команды</b> — это сообщение\n\n"
            "Работают и обычные команды: /profile /top /ranks /help")


def rewards_text(rewards: dict, names: dict) -> str:
    if not rewards:
        return ""
    lines = ["\n⭐ <b>Очки</b>"]
    ups = []
    for uid, r in sorted(rewards.items(), key=lambda kv: -kv[1]["delta"]):
        sign = "+" if r["delta"] > 0 else ""
        icon = {"w": "🏆", "l": "💀", "d": "🤝"}[r["result"]]
        lines.append(f"{icon} {e(names.get(uid, '?'))}: <b>{sign}{r['delta']}</b> → {r['points']} {r['rank']['emoji']}")
        if r["up"]:
            ups.append(f"🎉 {e(names.get(uid, '?'))} получает звание <b>{r['rank']['name']}</b> {r['rank']['emoji']}!")
    return "\n".join(lines + ups)
