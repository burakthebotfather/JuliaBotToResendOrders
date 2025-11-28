#!/usr/bin/env python3
# coding: utf-8
"""
Delivery Profit Bot (aiogram, JSON storage)

Commands:
  /start, /open, /close, /max, /min, /off, /report

Environment variables:
  BOT_TOKEN - required
  UNIQUE_USER_ID - optional (admin copy), default 542345855
"""

import os
import re
import asyncio
import json
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import Dict, Any, List

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ---------------- CONFIG ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("Please set BOT_TOKEN environment variable")

UNIQUE_USER_ID = int(os.getenv("UNIQUE_USER_ID", 542345855))

TZ = ZoneInfo("Europe/Minsk")  # UTC+3

DATA_FILE = "data.json"

# chat_id -> thread_id (use the mapping you provided)
ALLOWED = {
    -1002079167705: 48,
    -1002936236597: 3,
    -1002423500927: 2,
    -1003117964688: 5,
    -1002864795738: 3,
    -1002535060344: 5,
    -1002477650634: 3,
    -1003204457764: 4,
    -1002660511483: 3,
    -1002360529455: 3,
    -1002538985387: 3,
}

CHAT_NAMES = {
    -1002079167705: "A. Mousse Art Bakery - Белинского, 23",
    -1002936236597: "B. Millionroz.by - Тимирязева, 67",
    -1002423500927: "E. Flovi.Studio - Тимирязева, 65Б",
    -1003117964688: "F. Flowers Titan - Мележа, 1",
    -1002864795738: "G. Цветы Мира - Академическая, 6",
    -1002535060344: "H. Kudesnica.by - Старовиленский тракт, 10",
    -1002477650634: "I. Cvetok.by - Восточная, 41",
    -1003204457764: "J. Jungle.by - Неманская, 2",
    -1002660511483: "K. Pastel Flowers - Сурганова, 31",
    -1002360529455: "333. ТЕСТ БОТОВ - 1-й Нагатинский пр-д",
    -1002538985387: "L. Lamour.by - Кропоткина, 84",
}

# PRICES (your latest spec)
PRICE_BASE = 10.00   # '+'
PRICE_MK = 5.00      # 'мк'
PRICE_GAB_UNIT = 7.00  # n*габ base
COLORS = {
    "синяя": 8.00, "красная": 16.00, "оранжевая": 25.00, "салатовая": 33.00,
    "коричневая": 42.00, "светло-серая": 50.00, "розовая": 49.00, "темно-серая": 67.00,
    "голубая": 76.00
}

# ---------------- Data persistence ----------------
def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return {"drivers": {}, "entries": []}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"drivers": {}, "entries": []}

def save_data(d: Dict[str, Any]) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

DATA = load_data()

def next_entry_id() -> int:
    ids = [e.get("id", 0) for e in DATA.get("entries", [])] or [0]
    return max(ids) + 1

def now_iso() -> str:
    return datetime.now(TZ).isoformat()

# ---------------- Parsing utilities ----------------
def parse_cash_from_text(text: str) -> float:
    # finds first number potentially followed by "р", "руб", etc.
    m = re.search(r"(\d+[.,]?\d*)(?=\s*(р|руб|руб\.|р\.)?)", text)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except:
            return 0.0
    return 0.0

def compute_earn_from_text(text: str) -> (float, List[str]):
    """
    Parse triggers after first '+'.
    Supports:
      - ++ double
      - мк token
      - colors
      - nгаб (e.g. 2габ or 2 габ)
    """
    text_l = (text or "").lower()
    if "+" not in text_l:
        return 0.0, []
    # detect '++' anywhere -> double base
    earn = 0.0
    triggers = []
    if "++" in text_l:
        earn += PRICE_BASE * 2
        triggers.append("++")
    else:
        earn += PRICE_BASE
        triggers.append("+")
    # substring after first '+'
    after = text_l.split("+", 1)[1]
    # detect 'мк' (word boundary)
    if re.search(r"\bмк\b", after):
        earn += PRICE_MK
        triggers.append("мк")
    # detect colors
    for color, price in COLORS.items():
        if color in after:
            earn += price
            triggers.append(color)
    # detect n*габ or nгаб or 'n габ'
    for m in re.finditer(r"(\d+)\s*\*?\s*габ", after):
        try:
            n = int(m.group(1))
            earn += n * PRICE_GAB_UNIT
            triggers.append(f"{n}габ")
        except:
            pass
    # single 'габ'
    if re.search(r"\bгаб\b", after) and not re.search(r"\d+\s*\*?\s*габ", after):
        earn += PRICE_GAB_UNIT
        triggers.append("габ")
    return round(earn, 2), triggers

# ---------------- Bot and runtime state ----------------
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# message_id -> scheduled task
SCHEDULED: Dict[int, asyncio.Task] = {}
# awaiting correction: user_id -> dict(orig_chat, orig_message_id, bot_reply_id, expecting_private)
AWAITING_CORRECTION: Dict[int, Dict[str, Any]] = {}

# ---------------- Commands ----------------
@dp.message(Command(commands=["start"]))
async def cmd_start(m: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="/open - открыть смену", callback_data="noop")],
        [InlineKeyboardButton(text="/close - закрыть смену", callback_data="noop")],
        [InlineKeyboardButton(text="/report - сформировать отчет", callback_data="noop")],
    ])
    await m.answer(
        "Привет! Я фиксирую отметки.\n\nКоманды:\n"
        "/open - открыть смену\n/close - закрыть смену\n/max - подробный режим\n/min - итоговый режим\n/off - выйти с линии (перед /report)\n/report - сформировать отчет (после /close и через 5 минут)",
        reply_markup=kb
    )

@dp.message(Command(commands=["open"]))
async def cmd_open(m: types.Message):
    uid = str(m.from_user.id)
    drivers = DATA.setdefault("drivers", {})
    st = drivers.get(uid, {})
    st["open"] = True
    st["open_time"] = now_iso()
    st["mode"] = st.get("mode", "min")
    st["entries"] = st.get("entries", [])
    st["last_activity"] = now_iso()
    st["off"] = False
    drivers[uid] = st
    save_data(DATA)
    await m.reply(f"Вы на линии с {datetime.now(TZ).strftime('%H:%M:%S')}! Режим: {st['mode']}")

@dp.message(Command(commands=["max"]))
async def cmd_max(m: types.Message):
    uid = str(m.from_user.id)
    drivers = DATA.setdefault("drivers", {})
    st = drivers.get(uid, {})
    st["mode"] = "max"
    drivers[uid] = st
    save_data(DATA)
    await m.reply("Режим оповещений: подробный (/max).")

@dp.message(Command(commands=["min"]))
async def cmd_min(m: types.Message):
    uid = str(m.from_user.id)
    drivers = DATA.setdefault("drivers", {})
    st = drivers.get(uid, {})
    st["mode"] = "min"
    drivers[uid] = st
    save_data(DATA)
    await m.reply("Режим оповещений: в конце дня (/min).")

@dp.message(Command(commands=["off"]))
async def cmd_off(m: types.Message):
    uid = str(m.from_user.id)
    drivers = DATA.setdefault("drivers", {})
    st = drivers.get(uid, {})
    st["off"] = True
    drivers[uid] = st
    save_data(DATA)
    await m.reply("Вы ушли с линии. Теперь можно формировать отчет после /close.")

@dp.message(Command(commands=["close"]))
async def cmd_close(m: types.Message):
    uid = str(m.from_user.id)
    drivers = DATA.setdefault("drivers", {})
    st = drivers.get(uid, {})
    if not st.get("open"):
        await m.reply("Смена не была открыта.")
        return
    st["open"] = False
    st["close_time"] = now_iso()
    drivers[uid] = st
    save_data(DATA)
    # schedule ready flag after 5 minutes
    async def ready_flag(u):
        await asyncio.sleep(5*60)
        DATA.setdefault("drivers", {}).setdefault(u, {})["ready_for_report"] = True
        save_data(DATA)
    asyncio.create_task(ready_flag(uid))
    await m.reply("Смена закрыта. Через 5 минут можно формировать /report.")

@dp.message(Command(commands=["report"]))
async def cmd_report(m: types.Message):
    uid = str(m.from_user.id)
    drivers = DATA.setdefault("drivers", {})
    st = drivers.get(uid, {})
    if st.get("open"):
        await m.reply("Сначала закройте смену командой /close.")
        return
    if not st.get("ready_for_report"):
        await m.reply("Отчёт будет доступен через 5 минут после /close.")
        return
    if not st.get("off"):
        await m.reply("Перед формированием отчёта выполните /off.")
        return
    open_t = datetime.fromisoformat(st.get("open_time")) if st.get("open_time") else None
    close_t = datetime.fromisoformat(st.get("close_time")) if st.get("close_time") else None
    entries = []
    for e in DATA.get("entries", []):
        if str(e.get("driver_id")) == uid and e.get("processed"):
            et = datetime.fromisoformat(e["accepted_ts"])
            if open_t and close_t and open_t <= et <= close_t:
                entries.append(e)
    total_income = sum(e.get("earn", 0.0) for e in entries)
    total_cash = sum(e.get("cash", 0.0) for e in entries)
    balance = round(total_cash - total_income, 2)
    count = len(entries)
    lines = [
        datetime.now(TZ).strftime("%d.%m.%Y"),
        f"{m.from_user.full_name} (id:{m.from_user.id})",
        "",
        f"Доход: {total_income:.2f} BYN",
        f"Наличные: {total_cash:.2f} BYN",
        f"Баланс: {balance:.2f} BYN",
        "",
        f"Количество: {count}",
        ""
    ]
    by_chat = {}
    for e in entries:
        by_chat.setdefault(e["chat_id"], []).append(e)
    for cid, lst in by_chat.items():
        name = CHAT_NAMES.get(int(cid), str(cid))
        lines.append(f"{name}:")
        for item in lst:
            lines.append(f" - {item['text']} ({item['earn']:.2f} BYN, cash {item.get('cash',0.0):.2f})")
        lines.append("")
    report_text = "\n".join(lines)
    await m.reply(report_text)
    # send copy to admin
    try:
        await bot.send_message(UNIQUE_USER_ID, f"[Отчёт водителя]\n{report_text}")
    except Exception:
        pass
    st["ready_for_report"] = False
    save_data(DATA)

# ---------------- Message handling in allowed threads ----------------
@dp.message()
async def handle_messages(m: types.Message):
    # process only allowed chats & threads
    if m.chat.id not in ALLOWED:
        return
    expected = ALLOWED[m.chat.id]
    if m.message_thread_id != expected:
        return
    uid = m.from_user.id
    drivers = DATA.setdefault("drivers", {})
    st = drivers.get(str(uid), {})
    # only record if driver is on shift
    if not st.get("open"):
        return
    text = m.text or ""
    if "+" not in text:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Повторная запись отметки", callback_data=f"repeat|{m.chat.id}|{m.message_id}")]
        ])
        sent = await m.reply("Ошибка. Отсутствует основной триггер. Пожалуйста, нажмите кнопку «повторная запись отметки» и введите данные корректно", reply_markup=kb)
        AWAITING_CORRECTION[uid] = {"orig_chat": m.chat.id, "orig_msg": m.message_id, "bot_msg": sent.message_id, "expecting_private": False}
        return
    # create entry and schedule processing in 5 minutes
    eid = next_entry_id()
    entry = {
        "id": eid,
        "driver_id": uid,
        "chat_id": m.chat.id,
        "thread_id": m.message_thread_id,
        "text": text,
        "ts": m.date.astimezone(TZ).isoformat(),
        "processed": False,
        "accepted_ts": None,
        "earn": 0.0,
        "cash": 0.0
    }
    DATA.setdefault("entries", []).append(entry)
    save_data(DATA)
    async def delayed(eid_local, user_local, chat_local):
        await asyncio.sleep(5*60)
        e = next((x for x in DATA.get("entries", []) if x["id"] == eid_local), None)
        if not e:
            return
        earn, triggers = compute_earn_from_text(e["text"])
        cash = parse_cash_from_text(e["text"])
        e["earn"] = earn
        e["cash"] = cash
        e["processed"] = True
        e["accepted_ts"] = now_iso()
        save_data(DATA)
        # update driver's last activity
        st_local = DATA.setdefault("drivers", {}).get(str(user_local), {})
        st_local["last_activity"] = now_iso()
        DATA["drivers"][str(user_local)] = st_local
        save_data(DATA)
        # if driver in max mode, notify immediately
        if st_local.get("mode", "min") == "max":
            try:
                summary = (f"+{earn:.2f} BYN • {cash:.2f} BYN\n"
                           f"{CHAT_NAMES.get(chat_local, str(chat_local))}\n"
                           f"{e['ts']}\n\nАдрес: {e['text'].split('+')[0].strip()}\nТриггеры: {', '.join(triggers)}\n\n"
                           f"Доход за смену: {calc_driver_total(user_local):.2f} BYN\nБаланс за смену: {calc_driver_balance(user_local):.2f} BYN")
                await bot.send_message(user_local, summary)
            except Exception:
                pass
    task = asyncio.create_task(delayed(eid, uid, m.chat.id))
    SCHEDULED[eid] = task
    await m.reply("Отметка принята. Данные будут зафиксированы через 5 минут (можно исправить).")

# callback: repeat flow
@dp.callback_query(lambda c: c.data and c.data.startswith("repeat|"))
async def callback_repeat(c: CallbackQuery):
    parts = c.data.split("|")
    user = c.from_user.id
    if AWAITING_CORRECTION.get(user) is None:
        await c.answer("Нет ожидающих исправлений.", show_alert=False)
        return
    await c.message.answer("Правильная отметка:")
    AWAITING_CORRECTION[user]["expecting_private"] = True
    await c.answer()

# private messages: handle corrected input
@dp.message(lambda m: m.chat.type == "private")
async def private_handler(m: types.Message):
    user = m.from_user.id
    if user in AWAITING_CORRECTION and AWAITING_CORRECTION[user].get("expecting_private"):
        text = m.text or ""
        if "+" not in text:
            await m.reply("Ошибка. В корректной отметке отсутствует '+'. Попробуйте ещё раз.")
            return
        info = AWAITING_CORRECTION[user]
        orig_chat = info["orig_chat"]
        orig_msg = info["orig_msg"]
        bot_msg = info["bot_msg"]
        eid = next_entry_id()
        entry = {
            "id": eid,
            "driver_id": user,
            "chat_id": orig_chat,
            "thread_id": ALLOWED.get(orig_chat),
            "text": text,
            "ts": now_iso(),
            "processed": True,
            "accepted_ts": now_iso(),
            "earn": 0.0,
            "cash": 0.0
        }
        earn, triggers = compute_earn_from_text(text)
        cash = parse_cash_from_text(text)
        entry["earn"] = earn
        entry["cash"] = cash
        DATA.setdefault("entries", []).append(entry)
        save_data(DATA)
        await m.reply("Отметка принята! Старые пометки записи будут удалены в автоматическом режиме через некоторое время")
        # schedule deletion of original bad messages after 3 minutes
        async def delayed_del():
            await asyncio.sleep(3*60)
            try:
                await bot.delete_message(chat_id=orig_chat, message_id=orig_msg)
            except Exception:
                pass
            try:
                await bot.delete_message(chat_id=orig_chat, message_id=bot_msg)
            except Exception:
                pass
            try:
                await bot.delete_message(chat_id=user, message_id=m.message_id)
            except Exception:
                pass
        asyncio.create_task(delayed_del())
        # notify if max mode
        drivers = DATA.setdefault("drivers", {})
        st = drivers.get(str(user), {})
        if st.get("mode") == "max":
            try:
                await bot.send_message(user, f"+{earn:.2f} BYN • {cash:.2f} BYN\n{CHAT_NAMES.get(orig_chat)}\n{entry['ts']}\nАдрес: {text.split('+')[0].strip()}\nТриггеры: {', '.join(triggers)}\n\nДоход за смену: {calc_driver_total(user):.2f} BYN\nБаланс за смену: {calc_driver_balance(user):.2f} BYN")
            except Exception:
                pass
        AWAITING_CORRECTION.pop(user, None)

# ---------------- Utilities for driver totals ----------------
def calc_driver_total(uid: int) -> float:
    t = 0.0
    for e in DATA.get("entries", []):
        if e.get("driver_id") == uid and e.get("processed"):
            t += float(e.get("earn", 0.0))
    return round(t, 2)

def calc_driver_cash(uid: int) -> float:
    t = 0.0
    for e in DATA.get("entries", []):
        if e.get("driver_id") == uid and e.get("processed"):
            t += float(e.get("cash", 0.0))
    return round(t, 2)

def calc_driver_balance(uid: int) -> float:
    return round(calc_driver_cash(uid) - calc_driver_total(uid), 2)

# ---------------- Background tasks: inactivity and auto-close ----------------
async def background_tasks():
    while True:
        now = datetime.now(TZ)
        drivers = DATA.setdefault("drivers", {})
        for uid, st in list(drivers.items()):
            if not st.get("open"):
                continue
            last_iso = st.get("last_activity")
            last = datetime.fromisoformat(last_iso) if last_iso else None
            if last:
                if (now - last) > timedelta(hours=3) and not st.get("reminder_sent"):
                    try:
                        await bot.send_message(int(uid), "Активности нет длительное время. Пожалуйста, закройте смену и сформируйте отчет!")
                        st["reminder_sent"] = True
                        save_data(DATA)
                    except Exception:
                        pass
                if st.get("reminder_sent") and (now - last) > timedelta(hours=4):
                    try:
                        await bot.send_message(int(uid), "Активности нет длительное время. Пожалуйста, закройте смену и сформируйте отчет!")
                    except Exception:
                        pass
        # auto close at 23:00
        if now.hour == 23 and now.minute == 0:
            for uid, st in list(drivers.items()):
                if st.get("open"):
                    st["open"] = False
                    st["close_time"] = now.isoformat()
                    st["ready_for_report"] = True
                    try:
                        await bot.send_message(UNIQUE_USER_ID, f"Водитель {uid} не закрыл смену — бот закрыл автоматически.")
                    except Exception:
                        pass
            save_data(DATA)
        await asyncio.sleep(60)

# startup hook
async def on_startup():
    asyncio.create_task(background_tasks())

# ---------------- Run ----------------
if __name__ == "__main__":
    print("Starting delivery profit bot...")
    asyncio.get_event_loop().create_task(on_startup())
    from aiogram import executor
    executor.start_polling(dp, bot, skip_updates=True)
