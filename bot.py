"""Telegram group games bot: Дурак / Блэкджек / Покер / Тетрис + Mini App со зрителями.
Runtime: Python 3.11+, aiogram 3.x, aiohttp 3.x. One process = bot (long polling) + HTTPS-less app server (put it behind TLS)."""
import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiohttp import WSMsgType, web

import db
import texts
from commands import parse
from games import REGISTRY, GameError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("games")

TOKEN = os.environ.get("BOT_TOKEN", "")
PORT = int(os.getenv("PORT", "8080"))
APP_SHORT_NAME = os.getenv("APP_SHORT_NAME", "")  # optional: t.me/<bot>/<short>?startapp=...
DEV = os.getenv("DEV") == "1"
OPEN_TTL, IDLE_TTL, KEEP_TTL = 600, 900, 3600

def _load_env():
    f = Path(__file__).parent / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


_load_env()
TOKEN = os.environ.get("BOT_TOKEN", TOKEN)
if not TOKEN:
    raise SystemExit("BOT_TOKEN не задан: укажи его в переменных окружения хоста или в файле .env")
bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
BOT_USERNAME = ""


@dataclass
class Lobby:
    id: str
    game: str
    chat_id: int
    host: int
    players: list = field(default_factory=list)
    names: dict = field(default_factory=dict)
    status: str = "open"            # open | playing | finished | cancelled
    engine: object = None
    msg_id: int = 0
    start_msg_id: int = 0
    result: str = ""
    created: float = field(default_factory=time.time)
    touched: float = field(default_factory=time.time)
    sockets: dict = field(default_factory=dict)  # ws -> uid
    rewards: dict = field(default_factory=dict)  # uid -> итог очков после партии


LOBBIES: dict[str, Lobby] = {}
CHAT_LOBBY: dict[int, str] = {}


def mention(l: Lobby, uid: int) -> str:
    return f'<a href="tg://user?id={uid}">{html.escape(l.names.get(uid, str(uid)))}</a>'


def fmt_result(text: str, names: dict) -> str:
    return re.sub(r"\{name:(\d+)\}", lambda m: names.get(int(m.group(1)), "?"), text)


def lobby_text(l: Lobby) -> str:
    g = REGISTRY[l.game]
    rows = "\n".join(f"{i}. {mention(l, p)}" for i, p in enumerate(l.players, 1))
    return (f"{g['emoji']} <b>{g['title']}</b> — команда создана\n"
            f"Создатель: {mention(l, l.host)}\n\n"
            f"Игроки ({len(l.players)}/{g['max']}):\n{rows}")


def lobby_kb(l: Lobby) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Зайти", callback_data=f"j:{l.id}")],
        [InlineKeyboardButton(text="▶️ Начать", callback_data=f"s:{l.id}"),
         InlineKeyboardButton(text="✖️ Отменить", callback_data=f"c:{l.id}")],
    ])


def app_url(l: Lobby) -> str:
    base = f"https://t.me/{BOT_USERNAME}" + (f"/{APP_SHORT_NAME}" if APP_SHORT_NAME else "")
    return f"{base}?startapp={l.id}"


def release_chat(l: Lobby):
    if CHAT_LOBBY.get(l.chat_id) == l.id:
        del CHAT_LOBBY[l.chat_id]


# ───────────────────────── bot handlers ─────────────────────────
def mini_app_kb(text="📱 Открыть профиль") -> InlineKeyboardMarkup:
    base = f"https://t.me/{BOT_USERNAME}" + (f"/{APP_SHORT_NAME}" if APP_SHORT_NAME else "")
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, url=f"{base}?startapp=me")]])


async def create_lobby(m: Message, game: str):
    if m.chat.id in CHAT_LOBBY:
        old = LOBBIES.get(CHAT_LOBBY[m.chat.id])
        if old and old.status in ("open", "playing"):
            await m.reply("В этом чате уже идёт игра. Дождитесь конца или отмените её.")
            return
    u = m.from_user
    l = Lobby(id=secrets.token_urlsafe(6).replace("-", "a").replace("_", "b"), game=game, chat_id=m.chat.id, host=u.id,
              players=[u.id], names={u.id: u.full_name})
    LOBBIES[l.id] = l
    CHAT_LOBBY[m.chat.id] = l.id
    sent = await m.reply(lobby_text(l), reply_markup=lobby_kb(l))
    l.msg_id = sent.message_id


async def show_profile(m: Message, arg: dict):
    me = m.from_user
    target, own = me, True
    if arg.get("username"):
        uid = db.find_by_username(arg["username"])
        if uid is None:
            return await m.reply(f"Не знаю игрока @{html.escape(arg['username'])} — он ещё не писал боту и не играл.")
        p = db.get_profile(uid)
        return await m.reply(texts.profile_text(p))
    rep = m.reply_to_message.from_user if m.reply_to_message else None
    if rep and not rep.is_bot and rep.id != me.id:
        target, own = rep, False
        db.touch(rep.id, rep.full_name, rep.username)
    elif arg.get("other"):
        return await m.reply("Ответь этой командой на сообщение игрока или напиши «профиль @ник».")
    p = db.get_profile(target.id, target.full_name)
    await m.reply(texts.profile_text(p), reply_markup=mini_app_kb() if own and BOT_USERNAME else None)


@dp.message(F.chat.type.in_({"group", "supergroup", "private"}), F.text)
async def on_text(m: Message):
    if not m.from_user or m.from_user.is_bot:
        return
    cmd = parse(m.text, BOT_USERNAME)
    if not cmd:
        return
    kind, arg = cmd
    u = m.from_user
    db.touch(u.id, u.full_name, u.username)
    group = m.chat.type != "private"
    if kind == "game":
        if not group:
            return await m.reply("Игры запускаются в группе: добавь меня в чат и напиши там «игра дурак».")
        await create_lobby(m, arg)
    elif kind == "profile":
        await show_profile(m, arg)
    elif kind == "top":
        rows = db.top(m.chat.id if group else None, 10, arg)
        await m.reply(texts.top_text(rows, "этот чат" if group else "все игроки", arg))
    elif kind == "ranks":
        await m.reply(texts.ranks_text())
    elif kind == "help":
        await m.reply(texts.help_text())


async def _lobby_cb(cb: CallbackQuery):
    _, _, lid = cb.data.partition(":")
    l = LOBBIES.get(lid)
    if not l or l.status != "open":
        await cb.answer("Эта игра уже недоступна", show_alert=True)
        return None
    l.touched = time.time()
    return l


@dp.callback_query(F.data.startswith("j:"))
async def cb_join(cb: CallbackQuery):
    l = await _lobby_cb(cb)
    if not l:
        return
    u, g = cb.from_user, REGISTRY[l.game]
    if u.id in l.players:
        return await cb.answer("Ты уже в игре")
    if len(l.players) >= g["max"]:
        return await cb.answer("Мест нет", show_alert=True)
    l.players.append(u.id)
    l.names[u.id] = u.full_name
    await cb.answer("Ты в игре!")
    try:
        await cb.message.edit_text(lobby_text(l), reply_markup=lobby_kb(l))
    except TelegramBadRequest:
        pass


@dp.callback_query(F.data.startswith("c:"))
async def cb_cancel(cb: CallbackQuery):
    l = await _lobby_cb(cb)
    if not l:
        return
    if cb.from_user.id != l.host:
        return await cb.answer("Отменить может только создатель", show_alert=True)
    l.status = "cancelled"
    release_chat(l)
    await cb.answer()
    await cb.message.edit_text(f"✖️ {REGISTRY[l.game]['title']} отменена.")


@dp.callback_query(F.data.startswith("s:"))
async def cb_start(cb: CallbackQuery):
    l = await _lobby_cb(cb)
    if not l:
        return
    g = REGISTRY[l.game]
    if cb.from_user.id != l.host:
        return await cb.answer("Начать может только создатель", show_alert=True)
    if len(l.players) < g["min"]:
        return await cb.answer(f"Нужно минимум {g['min']} игрока", show_alert=True)
    l.engine = g["cls"](list(l.players))
    l.status = "playing"
    l.touched = time.time()
    await cb.answer()
    try:
        await cb.message.edit_text(f"{g['emoji']} <b>{g['title']}</b> — игра началась", reply_markup=None)
    except TelegramBadRequest:
        pass
    versus = " ⚔️ ".join(mention(l, p) for p in l.players)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎮 Открыть бой", url=app_url(l))]])
    sent = await bot.send_message(l.chat_id, f"⚔️ <b>Бой начался!</b>\n{versus}\n\n"
                                  f"Зрители могут смотреть — карты в руках им не видны.", reply_markup=kb)
    l.start_msg_id = sent.message_id


async def announce(l: Lobby, text: str):
    try:
        await bot.send_message(l.chat_id, f"🏆 <b>{REGISTRY[l.game]['title']}</b>: {html.escape(text)}"
                               + texts.rewards_text(l.rewards, l.names), reply_to_message_id=l.start_msg_id or None)
    except Exception:
        log.exception("announce failed")


# ───────────────────────── mini app backend ─────────────────────────
def check_init_data(init_data: str, max_age=86400 * 2) -> dict:
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    got = parsed.pop("hash", "")
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest(), got):
        raise ValueError("bad hash")
    if time.time() - int(parsed.get("auth_date", 0)) > max_age:
        raise ValueError("expired")
    return json.loads(parsed["user"])


async def send_state(l: Lobby, ws, uid: int):
    p = {"t": "state", "game": l.game, "lobby": l.id, "me": uid, "status": l.status, "players": l.players,
         "role": "player" if uid in l.players else "spectator", "names": {str(k): v for k, v in l.names.items()},
         "viewers": len(l.sockets), "result": l.result,
         "rewards": {str(k): v for k, v in l.rewards.items()}, "view": l.engine.view(uid) if l.engine else None}
    try:
        await ws.send_json(p)
    except ConnectionResetError:
        pass


async def send_profile(ws, uid: int, chat_id=None):
    top = db.top(chat_id, 10)
    try:
        await ws.send_json({"t": "profile", "p": db.get_profile(uid), "top": top, "scope": "chat" if chat_id is not None else "all",
                            "ranks": [{"min": r[0], "name": r[1], "emoji": r[2]} for r in db.RANKS], "rules": db.RULES,
                            "games": {k: {"title": g["title"], "emoji": g["emoji"]} for k, g in REGISTRY.items()}})
    except ConnectionResetError:
        pass


async def push(l: Lobby):
    for ws, uid in list(l.sockets.items()):
        await send_state(l, ws, uid)


async def after_act(l: Lobby):
    eng = l.engine
    events, eng.events = eng.events, []
    for ev in events:
        for ws, uid in list(l.sockets.items()):
            if uid == ev["to"]:
                await ws.send_json(ev)
    if eng.finished and l.status == "playing":
        l.status, l.result = "finished", fmt_result(eng.result_text, l.names)
        release_chat(l)
        try:
            l.rewards = db.record_game(l.chat_id, l.game, list(l.players), list(eng.winners), l.names)
        except Exception:
            log.exception("db.record_game")
        asyncio.create_task(announce(l, l.result))
        await push(l)
        for ws, uid in list(l.sockets.items()):
            if uid in l.rewards:
                await send_profile(ws, uid, l.chat_id)
        return
    await push(l)


async def ws_handler(request: web.Request):
    ws = web.WebSocketResponse(heartbeat=25, max_msg_size=64 * 1024)
    await ws.prepare(request)
    l, uid = None, None
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                d = json.loads(msg.data)
            except ValueError:
                continue
            if d.get("t") == "auth" and l is None:
                try:
                    user = {"id": 1, "first_name": "dev"} if DEV and d.get("dev") else check_init_data(d.get("initData", ""))
                except Exception:
                    await ws.send_json({"t": "fatal", "msg": "Не удалось проверить Telegram-авторизацию"})
                    break
                uid = user["id"]
                db.touch(uid, (user.get("first_name", "") + " " + user.get("last_name", "")).strip(), user.get("username"))
                if (d.get("lobby") or "") in ("", "me", "profile"):  # режим «только профиль»
                    await send_profile(ws, uid)
                    continue
                l = LOBBIES.get(d.get("lobby", ""))
                if not l or l.status not in ("playing", "finished"):
                    await ws.send_json({"t": "fatal", "msg": "Игра не найдена или уже закончилась"})
                    l = None
                    break
                l.names.setdefault(uid, (user.get("first_name", "") + " " + user.get("last_name", "")).strip() or "Игрок")
                l.sockets[ws] = uid
                await push(l)
                await send_profile(ws, uid, l.chat_id)
            elif d.get("t") == "profile" and uid is not None:
                await send_profile(ws, uid, l.chat_id if l else None)
            elif d.get("t") == "act" and l and l.status == "playing":
                try:
                    l.engine.act(uid, d)
                    l.touched = time.time()
                except GameError as e:
                    await ws.send_json({"t": "error", "msg": str(e)})
                except Exception:
                    log.exception("engine crash")
                    await ws.send_json({"t": "error", "msg": "Внутренняя ошибка"})
                await after_act(l)
    finally:
        if l:
            l.sockets.pop(ws, None)
            await push(l)
    return ws


async def janitor():
    while True:
        await asyncio.sleep(60)
        now = time.time()
        for l in list(LOBBIES.values()):
            try:
                if l.status == "open" and now - l.created > OPEN_TTL:
                    l.status = "cancelled"
                    release_chat(l)
                    await bot.edit_message_text("⌛ Время ожидания вышло, игра отменена.", chat_id=l.chat_id, message_id=l.msg_id)
                elif l.status == "playing" and now - l.touched > IDLE_TTL:
                    l.status, l.result = "finished", "игра прервана из-за неактивности"
                    release_chat(l)
                    await push(l)
                    await announce(l, l.result)
                elif l.status in ("finished", "cancelled") and now - l.touched > KEEP_TTL:
                    LOBBIES.pop(l.id, None)
            except Exception:
                log.exception("janitor")


async def index(_):
    return web.FileResponse(Path(__file__).parent / "webapp" / "index.html", headers={"Cache-Control": "no-store"})


async def main():
    global BOT_USERNAME
    BOT_USERNAME = (await bot.get_me()).username
    db.init()
    try:
        await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in [
            ("profile", "Мой профиль: очки, звание, статистика"), ("top", "Рейтинг игроков"),
            ("ranks", "Звания и как считаются очки"), ("help", "Список команд")]])
    except Exception:
        log.exception("set_my_commands")
    app = web.Application()
    app.add_routes([web.get("/", index), web.get("/ws", ws_handler), web.get("/health", lambda _: web.Response(text="ok"))])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    asyncio.create_task(janitor())
    log.info("app on :%s, bot @%s", PORT, BOT_USERNAME)
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    asyncio.run(main())
