import asyncio
import re
import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from difflib import SequenceMatcher

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from openai import OpenAI

# ================== CONFIG ==================

API_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TOKEN_HERE")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
UNIQUE_USER_ID = int(os.getenv("UNIQUE_USER_ID", 542345855))

TZ = ZoneInfo("Europe/Minsk")
client = OpenAI(api_key=OPENAI_API_KEY)

# ================== THREADS ==================

ALLOWED_THREADS = {
    -1002079167705: 7340,
    -1002936236597: 4,
    -1002423500927: 4,
    -1003117964688: 2,
    -1002864795738: 4,
    -1002535060344: 3,
    -1002477650634: 4,
    -1003204457764: 3,
    -1002660511483: 4,
    -1002360529455: 4,
    -1002538985387: 4,
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
    -1002360529455: "333. ТЕСТ БОТОВ",
    -1002538985387: "L. Lamour.by - Кропоткина, 84",
}

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

message_counter = {"date": None, "count": 0}
assign_mapping: dict[int, dict] = {}

# ================== AI PROMPT ==================

ADDRESS_AI_PROMPT = """
Ты помощник службы доставки.

Проверь, содержит ли текст заявки следующие данные:
- street (улица)
- house (номер дома)
- entrance (подъезд)
- floor (этаж)
- apartment (квартира)

Верни СТРОГО JSON:
{
  "street": true/false,
  "house": true/false,
  "entrance": true/false,
  "floor": true/false,
  "apartment": true/false,
  "comment": "кратко, что отсутствует"
}
"""

def check_address_with_ai(text: str) -> dict:
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": ADDRESS_AI_PROMPT},
            {"role": "user", "content": text}
        ],
        temperature=0
    )
    return json.loads(response.choices[0].message.content)

# ================== HELPERS ==================

def get_request_number():
    today = datetime.now(TZ).strftime("%d.%m.%Y")
    if message_counter["date"] != today:
        message_counter["date"] = today
        message_counter["count"] = 0
    message_counter["count"] += 1
    return f"{message_counter['count']:02d} / {today}"

def is_night_time() -> bool:
    now = datetime.now(TZ).time()
    return now >= datetime.strptime("21:55", "%H:%M").time() or now < datetime.strptime("09:05", "%H:%M").time()

def validate_contact(text: str) -> str:
    if not text:
        return "missing"
    cleaned = re.sub(r"[ \-\(\)]", "", text)
    if re.search(r"(\+375\d{9}|80(25|29|33|44)\d{7})", cleaned):
        return "ok"
    if "@" in text:
        return "ok"
    if re.search(r"\+?\d{7,}", cleaned):
        return "invalid"
    return "missing"

async def delete_messages_later(chat_id: int, message_ids: list[int], delay: int = 300):
    await asyncio.sleep(delay)
    for m_id in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=m_id)
        except Exception:
            pass

def generate_diff(old_text: str, new_text: str) -> str:
    sm = SequenceMatcher(None, old_text, new_text)
    result = ""
    for opcode, i1, i2, j1, j2 in sm.get_opcodes():
        if opcode == "equal":
            result += new_text[j1:j2]
        elif opcode == "insert":
            result += new_text[j1:j2]
        elif opcode == "delete":
            result += f"<s>{old_text[i1:i2]}</s>"
        elif opcode == "replace":
            result += f"<s>{old_text[i1:i2]}</s>{new_text[j1:j2]}"
    return result

# ================== MAIN HANDLER ==================

@dp.message(F.chat.id.in_(ALLOWED_THREADS.keys()))
async def handle_message(message: Message):
    if message.message_thread_id != ALLOWED_THREADS.get(message.chat.id):
        return
    if len(message.text or "") < 50:
        return
    if message.from_user.id == UNIQUE_USER_ID:
        return

    status = validate_contact(message.text or "")
    night = is_night_time()

    missing_address = []
    try:
        addr = check_address_with_ai(message.text or "")
        missing_address = [k for k, v in addr.items() if v is False and k != "comment"]
    except Exception:
        pass

    if night:
        await message.reply("Уже не онлайн\nНакапливаю заявки — распределим утром.\nГрафик работы: 09:05 - 21:55 (без выходных).")
    else:
        if status == "missing":
            await message.reply(
                "Номер для связи не обнаружен. "
                "Доставка возможна без предварительного звонка получателю. "
                "Риски - на отправителе."
            )
        elif status == "invalid":
            await message.reply(
                "Заказ не принят в работу. "
                "Номер телефона получателя в заявке указан некорректно. "
                "Пожалуйста, укажите номер в формате +375ХХХХХХХХХ или ник Telegram, используя символ @."
            )

    request_number = get_request_number()
    chat_name = CHAT_NAMES.get(message.chat.id, "Чат")
    header = f"{request_number}\n{chat_name}\n\n"

    warning = ""
    if missing_address:
        warning = (
            "⚠️ НЕПОЛНЫЙ АДРЕС\n"
            f"Отсутствует: {', '.join(missing_address)}\n\n"
        )

    forward_body = header + warning + (message.text or "")

    if missing_address:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Уточнить адрес", callback_data="address:fix")],
            [InlineKeyboardButton(text="🚗 Передать без уточнений (платно)", callback_data="address:skip")],
            [InlineKeyboardButton(text="❌ Отклонить", callback_data="decision:reject")],
        ])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🆗 ПРИНЯТЬ", callback_data="decision:accept"),
                InlineKeyboardButton(text="⛔️ ОТКЛОНИТЬ", callback_data="decision:reject"),
            ],
            [InlineKeyboardButton(text="✅ ВЫПОЛНЕН", callback_data="decision:done")]
        ])

    sent = await bot.send_message(
        UNIQUE_USER_ID,
        forward_body,
        reply_markup=kb,
        disable_notification=night,
    )

    assign_mapping[sent.message_id] = {
        "orig_chat_id": message.chat.id,
        "orig_msg_id": message.message_id,
        "accept_reply_id": None,
        "address_incomplete": bool(missing_address),
        "original_text": message.text or "",
        "request_number": request_number,
    }

# ================== ADDRESS DECISION ==================

@dp.callback_query(F.data.startswith("address:"))
async def handle_address(callback: CallbackQuery):
    action = callback.data.split(":")[1]

    if action == "fix":
        await callback.message.reply(
            "✏️ Пожалуйста, дополните адрес:\n"
            "улица, дом, подъезд, этаж, квартира"
        )
        await callback.answer("Ожидаю уточнение")

    elif action == "skip":
        await callback.message.reply(
            "🚗 Заявка передана без уточнения адреса.\n"
            "💰 Уточнение — платная опция для водителя."
        )
        await callback.answer("Передано без уточнений")

# ================== DECISIONS ==================

@dp.callback_query(F.data.startswith("decision:"))
async def handle_decision(callback: CallbackQuery):
    admin_msg_id = callback.message.message_id
    info = assign_mapping.get(admin_msg_id)
    if not info:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    action = callback.data.split(":")[1]
    orig_chat_id = info["orig_chat_id"]
    orig_msg_id = info["orig_msg_id"]

    if action == "accept":
        sent = await bot.send_message(orig_chat_id, "Заказ принят в работу.", reply_to_message_id=orig_msg_id)
        info["accept_reply_id"] = sent.message_id

    elif action == "reject":
        await bot.send_message(orig_chat_id, "Заказ не принят в работу. Доставка невозможна в пределах предложенного интервала.", reply_to_message_id=orig_msg_id)

    else:  # done
        await bot.delete_message(UNIQUE_USER_ID, admin_msg_id)
        assign_mapping.pop(admin_msg_id, None)
        await callback.answer("Карточка удалена")
        return

    await callback.answer("Готово")

# ================== ASSIGN DRIVER ==================

@dp.message(F.from_user.id == UNIQUE_USER_ID, F.reply_to_message)
async def handle_admin_assign_reply(message: Message):
    reply_to = message.reply_to_message
    info = assign_mapping.get(reply_to.message_id)
    if not info:
        return

    target = (message.text or "").strip()
    if not target.startswith("@"):
        await message.reply("Укажи ник в формате @username")
        return

    await bot.send_message(
        info["orig_chat_id"],
        f"Доставка для {target}",
        reply_to_message_id=info["orig_msg_id"]
    )

    confirm = await message.reply("Готово — уведомил чат.")
    asyncio.create_task(delete_messages_later(
        UNIQUE_USER_ID,
        [message.message_id, confirm.message_id],
        delay=300
    ))

# ================== EDITED MESSAGE HANDLER ==================

@dp.edited_message(F.chat.id.in_(ALLOWED_THREADS.keys()))
async def handle_edited_message(message: Message):
    # Ищем соответствующую заявку
    info = None
    for admin_msg_id, data in assign_mapping.items():
        if data["orig_msg_id"] == message.message_id and data["orig_chat_id"] == message.chat.id:
            info = data
            break
    if not info:
        return

    old_text = info.get("original_text", "")
    new_text = message.text or ""
    if old_text == new_text:
        return

    diff_content = generate_diff(old_text, new_text)

    # Отправляем в thread_id без шапки
    diff_msg_thread = "Обнаружены правки в исходной заявке!\n" + diff_content
    await bot.send_message(
        chat_id=message.chat.id,
        text=diff_msg_thread,
        reply_to_message_id=message.message_id,
        parse_mode="HTML"
    )

    # Отправляем пользователю с уникальным ID с шапкой
    request_number = info.get("request_number", get_request_number())
    chat_name = CHAT_NAMES.get(info["orig_chat_id"], f"Chat {info['orig_chat_id']}")
    header = f"UPD 🆙 к {request_number}\n{chat_name}\n\n"
    diff_msg_user = header + "Обнаружены правки в исходной заявке!\n" + diff_content

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Принять изменение", callback_data=f"accept_edit:{admin_msg_id}")]
    ])

    sent_to_user = await bot.send_message(
        UNIQUE_USER_ID,
        diff_msg_user,
        reply_markup=kb,
        parse_mode="HTML"
    )

    info["edit_notification_id"] = sent_to_user.message_id
    info["original_text"] = new_text

# ================== ACCEPT EDIT ==================

@dp.callback_query(F.data.startswith("accept_edit:"))
async def handle_accept_edit(callback: CallbackQuery):
    admin_msg_id = int(callback.data.split(":")[1])
    info = assign_mapping.get(admin_msg_id)
    if not info:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    # Отправляем сообщение в thread_id о принятии изменений
    await bot.send_message(
        chat_id=info["orig_chat_id"],
        reply_to_message_id=info["orig_msg_id"],
        text="изменения приняты Исполнителем"
    )

    # Убираем кнопку у пользователя
    try:
        await bot.edit_message_reply_markup(
            chat_id=UNIQUE_USER_ID,
            message_id=info.get("edit_notification_id"),
            reply_markup=None
        )
    except Exception:
        pass

    await callback.answer("Изменения приняты")

# ================== RUN ==================

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
