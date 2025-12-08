# main.py
import asyncio
import re
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

API_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TOKEN_HERE")
UNIQUE_USER_ID = int(os.getenv("UNIQUE_USER_ID", 542345855))

# Часовой пояс (UTC+3)
TZ = ZoneInfo("Europe/Minsk")

# chat_id -> thread_id
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

# chat_id -> readable name
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

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# Счётчик заявок по дате
message_counter = {"date": None, "count": 0}

# admin_msg_id -> {orig_chat_id, orig_msg_id, accept_reply_id, last_assigned_driver}
assign_mapping: dict[int, dict] = {}


def get_request_number():
    today = datetime.now(TZ).strftime("%d.%m.%Y")
    if message_counter["date"] != today:
        message_counter["date"] = today
        message_counter["count"] = 0
    message_counter["count"] += 1
    return f"{message_counter['count']:02d} / {today}"


def is_night_time() -> bool:
    now = datetime.now(TZ).time()
    return now >= datetime.strptime("22:00", "%H:%M").time() or now < datetime.strptime("08:00", "%H:%M").time()


def validate_contact(text: str) -> str:
    if not text:
        return "missing"
    cleaned = text.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    belarus_pattern = re.compile(r"(\+375\d{9}|80(25|29|33|44)\d{7})")
    if belarus_pattern.search(cleaned):
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


def admin_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять", callback_data="decision:accept"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data="decision:reject"),
        ],
        [
            InlineKeyboardButton(
                text="ℹ️ Рекомендации по адресу",
                callback_data="info:address"
            )
        ],
        [InlineKeyboardButton(text="🟢 Выполнен", callback_data="decision:done")]
    ])
    return kb


@dp.message(F.chat.id.in_(ALLOWED_THREADS.keys()))
async def handle_message(message: Message):
    """Обработка заявок из чатов."""
    if message.message_thread_id != ALLOWED_THREADS.get(message.chat.id):
        return
    if len(message.text or "") < 50:
        return
    if message.from_user.id == UNIQUE_USER_ID:
        return

    status = validate_contact(message.text or "")
    night = is_night_time()

    if night:
        try:
            await message.reply("Уже не онлайн 🌃\nНакапливаю заявки - распределим утром.")
        except Exception:
            pass
    else:
        if status == "missing":
            try:
                await message.reply(
                    "Номер для связи не обнаружен. "
                    "Доставка возможна без предварительного звонка получателю. "
                    "Риски - на отправителе."
                )
            except Exception:
                pass
        elif status == "invalid":
            try:
                await message.reply(
                    "Заказ не принят в работу. "
                    "Номер телефона получателя в заявке указан некорректно. "
                    "Пожалуйста, укажите номер в формате +375ХХХХХХХХХ или ник Telegram, используя символ @."
                )
            except Exception:
                pass

    # Карточка админу
    request_number = get_request_number()
    chat_name = CHAT_NAMES.get(message.chat.id, f"Chat {message.chat.id}")
    header = f"{request_number}\n{chat_name}\n\n"
    forward_body = header + (message.text or "")
    if status == "invalid":
        forward_body = "❌ ОТКЛОНЕН ❌\n\n" + forward_body
    if night:
        forward_body = "НОЧНОЙ ЗАКАЗ 🌙\n\n" + forward_body

    sent = await bot.send_message(
        UNIQUE_USER_ID,
        forward_body,
        reply_markup=admin_keyboard(),
        disable_notification=night,
    )

    assign_mapping[sent.message_id] = {
        "orig_chat_id": message.chat.id,
        "orig_msg_id": message.message_id,
        "accept_reply_id": None,
        "last_assigned_driver": None
    }


@dp.callback_query(F.data.startswith("decision:"))
async def handle_decision(callback: CallbackQuery):
    admin_msg_id = callback.message.message_id
    info = assign_mapping.get(admin_msg_id)
    if not info:
        await callback.answer("Заявка устарела или не найдена.", show_alert=True)
        return

    action = callback.data.split(":", 1)[1]
    orig_chat_id = info["orig_chat_id"]
    orig_msg_id = info["orig_msg_id"]

    if action == "accept":
        try:
            sent = await bot.send_message(
                orig_chat_id,
                "Заказ принят в работу. 💡 Рекомендуется уточнять все обязательные элементы адреса при формировании исходной заявки.\n"
                "🏠 для жилых помещений: адрес, подъезд, этаж, номер квартиры и (или) комментарий;\n"
                "🏢 для коммерческих зданий: адрес, номер офиса, блок, секция, ориентиры входа, режим доступа и иные сведения, обеспечивающие возможность осуществления доставки",
                reply_to_message_id=orig_msg_id
            )
            info["accept_reply_id"] = sent.message_id
        except Exception:
            pass
        popup = "Отметил как принятый."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Выполнен", callback_data="decision:done")]
        ])
        await bot.edit_message_reply_markup(UNIQUE_USER_ID, admin_msg_id, reply_markup=kb)

    elif action == "reject":
        try:
            await bot.send_message(
                orig_chat_id,
                "Заказ не принят в работу. Доставка невозможна в пределах предложенного интервала.",
                reply_to_message_id=orig_msg_id,
            )
        except Exception:
            pass
        popup = "Отметил как отклонённый."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Выполнен", callback_data="decision:done")]
        ])
        await bot.edit_message_reply_markup(UNIQUE_USER_ID, admin_msg_id, reply_markup=kb)

    else:  # done
        try:
            await bot.delete_message(chat_id=UNIQUE_USER_ID, message_id=admin_msg_id)
        except Exception:
            pass
        assign_mapping.pop(admin_msg_id, None)
        await callback.answer("Карточка удалена.")
        return

    assign_mapping[admin_msg_id] = info
    await callback.answer(popup)


@dp.message(F.from_user.id == UNIQUE_USER_ID, F.reply_to_message)
async def handle_admin_assign_reply(message: Message):
    """Назначение водителя — вариант 3: уведомление магазина без отправки карточки водителю."""
    reply_to = message.reply_to_message
    if not reply_to:
        return

    admin_msg_id = reply_to.message_id
    info = assign_mapping.get(admin_msg_id)
    if not info:
        await message.reply("Информация по этой заявке устарела или не найдена.")
        return

    raw = (message.text or "").strip()
    if not raw:
        await message.reply("Пожалуйста, укажи ник в формате @username.")
        return

    # извлекаем @username
    m = re.search(r"@([A-Za-z0-9_]{5,32})", raw)
    if not m:
        await message.reply("Укажи ник в формате @username.")
        return
    username = m.group(1)
    target = f"@{username}"

    orig_chat_id = info["orig_chat_id"]
    orig_msg_id = info["orig_msg_id"]

    # проверка повторного назначения
    if info.get("last_assigned_driver") is not None:
        try:
            await bot.send_message(
                orig_chat_id,
                f"Назначен новый водитель. Доставка для {target}",
                reply_to_message_id=orig_msg_id
            )
        except Exception:
            pass

    # обновляем последний назначенный ник
    info["last_assigned_driver"] = target
    assign_mapping[admin_msg_id] = info

    confirm = await message.reply(f"Готово — назначен водитель {target}.")
    asyncio.create_task(delete_messages_later(UNIQUE_USER_ID, [message.message_id, confirm.message_id], delay=5*60))


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
