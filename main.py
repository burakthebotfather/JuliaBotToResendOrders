import asyncio
import re
import os
from datetime import datetime

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

# chat_id -> thread_id
ALLOWED_THREADS = {
    -1002079167705: 7340,
    -1002387655137: 9,
    -1002423500927: 4,
    -1002178818697: 4,
    -1002477650634: 4,
    -1002660511483: 4,
    -1002864795738: 4,
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
}

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# Счётчик заявок по дате
message_counter = {"date": None, "count": 0}

# mapping: admin_message_id -> (orig_chat_id, orig_message_id)
assign_mapping: dict[int, tuple[int, int]] = {}


def get_request_number():
    today = datetime.now().strftime("%d.%m.%Y")
    if message_counter["date"] != today:
        message_counter["date"] = today
        message_counter["count"] = 0
    message_counter["count"] += 1
    return f"{message_counter['count']:02d} / {today}"


def validate_contact(text: str) -> str:
    """Проверка корректности контакта. Возвращает статус: ok, missing, invalid"""
    if not text:
        return "missing"

    cleaned = text.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")

    belarus_pattern = re.compile(r"(\+375\d{9}|80(25|29|33|44)\d{7})")
    if belarus_pattern.search(cleaned):
        return "ok"

    if "@" in text:
        return "ok"

    if re.search(r"\+?\d{7,}", cleaned):  # есть номер, но не белорусский/не в нужном формате
        return "invalid"

    return "missing"


@dp.message(F.chat.id.in_(ALLOWED_THREADS.keys()))
async def handle_message(message: Message):
    # пропускаем если не в нужном треде
    if message.message_thread_id != ALLOWED_THREADS.get(message.chat.id):
        return

    # минимальная длина, как раньше
    if len(message.text or "") < 50:
        return

    # игнорируем сообщения от самого администратора
    if message.from_user.id == UNIQUE_USER_ID:
        return

    request_number = get_request_number()
    chat_name = CHAT_NAMES.get(message.chat.id, f"Chat {message.chat.id}")

    # Проверка контакта
    status = validate_contact(message.text)

    if status == "ok":
        reply_text = "Заказ принят в работу."
    elif status == "missing":
        reply_text = (
            "Номер для связи не обнаружен. "
            "Доставка возможна без предварительного звонка получателю. "
            "Риски - на отправителе."
        )
    else:  # invalid
        reply_text = (
            "Заказ не принят в работу. "
            "Номер телефона получателя в заявке указан некорректно. "
            "Пожалуйста, укажите номер в формате +375ХХХХХХХХХ "
            "или ник Telegram, используя символ @"
        )

    # Ответ в исходном чате
    await message.reply(reply_text)

    # Формируем карточку (без парсинга) и прикрепляем кнопку "Передать"
    header = f"{request_number}\n{chat_name}\n\n"
    forward_text = header + (message.text or "")

    if status == "invalid":
        forward_text = "❌ ОТКЛОНЕН ❌\n\n" + forward_text

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Передать", callback_data=f"assign:{message.chat.id}:{message.message_id}")]
    ])

    # Отправляем админу и запоминаем id этого сообщения (чтобы потом по reply точно знать, к какой заявке оно относится)
    sent = await bot.send_message(UNIQUE_USER_ID, forward_text, reply_markup=kb)
    assign_mapping[sent.message_id] = (message.chat.id, message.message_id)


@dp.callback_query(F.data.startswith("assign:"))
async def cb_assign(callback: CallbackQuery):
    """
    Обработчик нажатия кнопки "Передать".
    Просто даём инструкцию — админ должен ответить на это сообщение ником @username.
    """
    # краткое уведомление (toast)
    await callback.answer("Отправь ник пользователя (например @ivan) в ответ на это сообщение.")
    # и дубль-инструкция в чате (чтобы не потерялась)
    await callback.message.reply("Отправь ник пользователя (например @ivan) в ответ на это сообщение.")


@dp.message(F.from_user.id == UNIQUE_USER_ID, F.reply_to_message)
async def handle_assign_reply(message: Message):
    """
    Админ отвечает на сообщение бота в личке ником (например @ivan).
    Тогда бот уведомляет исходный чат, что заказ передан.
    """
    reply_to = message.reply_to_message
    if not reply_to:
        return

    orig = assign_mapping.get(reply_to.message_id)
    if not orig:
        # возможно админ ответил не на то сообщение — игнорируем
        return

    target = (message.text or "").strip()
    if not target.startswith("@") or len(target) < 2 or " " in target:
        await message.reply("Пожалуйста, укажи ник в формате @username (без пробелов).")
        return

    orig_chat_id, orig_msg_id = orig

    # отправляем уведомление в исходный чат в reply к исходному сообщению
    try:
        await bot.send_message(orig_chat_id, f"Заказ передан в работу для {target}", reply_to_message_id=orig_msg_id)
        await message.reply("Готово — уведомил чат.")
    except Exception as e:
        await message.reply(f"Ошибка при уведомлении чата: {e}")

    # чистим mapping (чтобы не накапливать)
    assign_mapping.pop(reply_to.message_id, None)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
