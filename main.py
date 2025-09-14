import asyncio
import re
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

API_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TOKEN_HERE")
UNIQUE_USER_ID = int(os.getenv("UNIQUE_USER_ID", 542345855))

# Часовой пояс
TZ = ZoneInfo("Europe/Minsk")

# chat_id -> thread_id
ALLOWED_THREADS = {
    -1002079167705: 7340,
    -1002387655137: 9,
    -1002423500927: 4,
    -1002178818697: 4,
    -1002477650634: 4,
    -1002660511483: 4,
    -1002864795738: 4,
    -1002360529455: 4,
    -1002538985387: 4,
}

# chat_id -> readable name
CHAT_NAMES = {
    -1002079167705: "A. Mousse Art Bakery - Белинского, 23",
    -1002387655137: "B. Millionroz.by - Тимирязева, 67",
    -1002423500927: "E. Flovi.Studio - Тимирязева, 65Б",
    -1002178818697: "H. Kudesnica.by - Старовиленский тракт, 10",
    -1002477650634: "I. Cvetok.by - Восточная, 41",
    -1002660511483: "K. Pastel Flowers - Сурганова, 31",
    -1002864795738: "G. Цветы Мира - Академическая, 6",
    -1002360529455: "333. ТЕСТ БОТОВ - 1-й Нагатинский пр-д",
    -1002538985387: "L. Lamour.by - Кропоткина, 84",
}

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# Счётчик заявок по дате
message_counter = {"date": None, "count": 0}

# mapping: admin_message_id -> (orig_chat_id, orig_message_id)
assign_mapping: dict[int, tuple[int, int]] = {}


def is_night_time() -> bool:
    """Проверяем, ночь ли (с 22:00 до 08:00 по UTC+3)."""
    now = datetime.now(TZ).time()
    return now >= datetime.strptime("22:00", "%H:%M").time() or now < datetime.strptime("08:00", "%H:%M").time()


def get_request_number():
    today = datetime.now(TZ).strftime("%d.%m.%Y")
    if message_counter["date"] != today:
        message_counter["date"] = today
        message_counter["count"] = 0
    message_counter["count"] += 1
    return f"{message_counter['count']:02d} / {today}"


def validate_contact(text: str) -> str:
    """Проверка корректности контакта"""
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


@dp.message(F.chat.id.in_(ALLOWED_THREADS.keys()))
async def handle_message(message: Message):
    """Обрабатываем заявки из чатов"""
    if message.message_thread_id != ALLOWED_THREADS.get(message.chat.id):
        return
    if len(message.text or "") < 50:
        return
    if message.from_user.id == UNIQUE_USER_ID:
        return

    request_number = get_request_number()
    chat_name = CHAT_NAMES.get(message.chat.id, f"Chat {message.chat.id}")
    status = validate_contact(message.text)

    if is_night_time():
        reply_text = "Уже не онлайн 🌃\nНакапливаю заявки - распределим утром."
    else:
        if status == "ok":
            reply_text = "Заказ принят в работу."
        elif status == "missing":
            reply_text = (
                "Номер для связи не обнаружен. "
                "Доставка возможна без предварительного звонка получателю. "
                "Риски - на отправителе."
            )
        else:
            reply_text = (
                "Заказ не принят в работу. "
                "Номер телефона получателя в заявке указан некорректно. "
                "Пожалуйста, укажите номер в формате +375ХХХХХХХХХ "
                "или ник Telegram, используя символ @."
            )

    # ответ в исходном чате
    await message.reply(reply_text)

    # карточка для администратора
    header = f"{request_number}\n{chat_name}\n\n"
    forward_text = header + (message.text or "")
    if status == "invalid":
        forward_text = "❌ ОТКЛОНЕН ❌\n\n" + forward_text
    if is_night_time():
        forward_text = "НОЧНОЙ ЗАКАЗ 🌙\n\n" + forward_text

    # добавляем кнопку "Выполнен ✅"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выполнен ✅", callback_data="done")]
    ])

    sent = await bot.send_message(
        UNIQUE_USER_ID,
        forward_text,
        reply_markup=kb,
        disable_notification=is_night_time()
    )
    assign_mapping[sent.message_id] = (message.chat.id, message.message_id)


@dp.message(F.from_user.id == UNIQUE_USER_ID, F.reply_to_message)
async def handle_assign_reply(message: Message):
    """Админ отвечает на сообщение бота ником исполнителя"""
    reply_to = message.reply_to_message
    if not reply_to:
        return

    orig = assign_mapping.get(reply_to.message_id)
    if not orig:
        return

    target = (message.text or "").strip()
    if not target.startswith("@") or " " in target:
        await message.reply("Пожалуйста, укажи ник в формате @username (без пробелов).")
        return

    orig_chat_id, orig_msg_id = orig
    try:
        confirm_msg = await bot.send_message(
            orig_chat_id,
            f"Доставка для {target}",
            reply_to_message_id=orig_msg_id,
        )
        done_msg = await message.reply("Готово — уведомила чат.")

        # Автоудаление через 5 минут
        await asyncio.sleep(300)
        try:
            await confirm_msg.delete()
            await done_msg.delete()
        except:
            pass

    except Exception as e:
        await message.reply(f"Ошибка при уведомлении чата: {e}")

    assign_mapping.pop(reply_to.message_id, None)


@dp.callback_query(F.data == "done")
async def mark_done(callback: CallbackQuery):
    """Скрываем сообщение по нажатию 'Выполнен ✅'"""
    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer("Заявка отмечена как выполненная ✅")


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
