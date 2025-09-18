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

# chat_id -> thread_id (сохранил все, как у тебя)
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

# chat_id -> readable name (как у тебя)
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

# Счётчик заявок по дате (если нужен)
message_counter = {"date": None, "count": 0}


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
    """Возвращает: 'ok', 'missing', 'invalid'"""
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


# mapping: admin_sent_message_id -> { orig_chat_id, orig_msg_id, (optionally other fields) }
assign_mapping: dict[int, dict] = {}

# Удаляет список сообщений в чате через delay секунд
async def delete_messages_later(chat_id: int, message_ids: list[int], delay: int = 300):
    await asyncio.sleep(delay)
    for m_id in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=m_id)
        except Exception:
            pass


@dp.message(F.chat.id.in_(ALLOWED_THREADS.keys()))
async def handle_message(message: Message):
    """Перехватываем заявки из разрешённых тредов."""
    # фильтр треда
    if message.message_thread_id != ALLOWED_THREADS.get(message.chat.id):
        return

    # минимальная длина
    if len(message.text or "") < 50:
        return

    # игнорируем сообщения от самого администратора
    if message.from_user.id == UNIQUE_USER_ID:
        return

    status = validate_contact(message.text or "")
    night = is_night_time()

    # Если не ночь и статус == 'ok' — *не* отвечаем автоматически.
    # Для остальных статусов (missing/invalid) или при ночном режиме — оставим ответ в чате,
    # как было раньше (если нужно изменить — скажи).
    if night:
        # Сохраняем прежнее поведение — отвечаем ночным текстом в чате, затем пересылаем админу с пометкой.
        reply_text = "Уже не онлайн 🌃\nНакапливаю заявки - распределим утром."
        try:
            await message.reply(reply_text)
        except Exception:
            pass
    else:
        # если статус != ok — отправляем соответствующий ответ в исходный чат
        if status == "ok":
            # НЕ присылаем автоматический "Заказ принят в работу." — кнопки будут у админа
            pass
        elif status == "missing":
            reply_text = (
                "Номер для связи не обнаружен. "
                "Доставка возможна без предварительного звонка получателю. "
                "Риски - на отправителе."
            )
            try:
                await message.reply(reply_text)
            except Exception:
                pass
        else:  # invalid
            reply_text = (
                "Заказ не принят в работу. "
                "Номер телефона получателя в заявке указан некорректно. "
                "Пожалуйста, укажите номер в формате +375ХХХХХХХХХ или ник Telegram, используя символ @."
            )
            try:
                await message.reply(reply_text)
            except Exception:
                pass

    # Формируем карточку для администратора (с кнопками Принять/Отклонить)
    request_number = get_request_number()
    chat_name = CHAT_NAMES.get(message.chat.id, f"Chat {message.chat.id}")
    header = f"{request_number}\n{chat_name}\n\n"
    forward_body = header + (message.text or "")
    if status == "invalid":
        forward_body = "❌ ОТКЛОНЕН ❌\n\n" + forward_body
    if night:
        forward_body = "НОЧНОЙ ЗАКАЗ 🌙\n\n" + forward_body

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять заказ", callback_data="decision:accept"),
            InlineKeyboardButton(text="❌ Отклонить заказ", callback_data="decision:reject"),
        ]
    ])

    sent = await bot.send_message(
        UNIQUE_USER_ID,
        forward_body,
        reply_markup=kb,
        disable_notification=night,
    )

    # сохраняем связь admin_msg_id -> исходный чат+сообщение
    assign_mapping[sent.message_id] = {
        "orig_chat_id": message.chat.id,
        "orig_msg_id": message.message_id,
    }


@dp.callback_query(F.data.startswith("decision:"))
async def handle_decision(callback: CallbackQuery):
    """Обработка нажатия 'Принять' / 'Отклонить' админом."""
    # admin message id (это то сообщение, под которым была нажата кнопка)
    admin_msg_id = callback.message.message_id
    info = assign_mapping.get(admin_msg_id)
    if not info:
        await callback.answer("Заявка устарела или не найдена.", show_alert=True)
        return

    action = callback.data.split(":", 1)[1]  # "accept" или "reject"
    orig_chat_id = info["orig_chat_id"]
    orig_msg_id = info["orig_msg_id"]

    if action == "accept":
        reply_text = "Заказ принят в работу."
        popup = "Отметил как принятый."
    else:
        reply_text = "Заказ не принят в работу. Доставка невозможна в пределах предложенного интервала."
        popup = "Отметил как отклонённый."

    # отправляем ответ в исходный чат (reply к исходному сообщению)
    try:
        await bot.send_message(
            orig_chat_id,
            reply_text,
            reply_to_message_id=orig_msg_id,
        )
    except Exception as e:
        await callback.answer(f"Ошибка при отправке в исходный чат: {e}", show_alert=True)
        return

    # убираем кнопки под карточкой у админа (чтобы нельзя было нажать снова)
    try:
        await bot.edit_message_reply_markup(chat_id=UNIQUE_USER_ID, message_id=admin_msg_id, reply_markup=None)
    except Exception:
        pass

    await callback.answer(popup)


@dp.message(F.from_user.id == UNIQUE_USER_ID, F.reply_to_message)
async def handle_admin_assign_reply(message: Message):
    """
    Админ отвечает на карточку в ЛС, указывая @username.
    Бот отправляет в исходный чат 'Доставка для @username' (reply к заявке).
    Сообщение админа с @username и подтверждение бота будут удалены через 5 минут,
    чтобы в ЛС остались только пересланные карточки.
    """
    reply_to = message.reply_to_message
    if not reply_to:
        return

    admin_sent_msg_id = reply_to.message_id
    info = assign_mapping.get(admin_sent_msg_id)
    if not info:
        await message.reply("Информация по этой заявке устарела или не найдена.")
        return

    target = (message.text or "").strip()
    if not target.startswith("@") or " " in target:
        await message.reply("Пожалуйста, укажи ник в формате @username (без пробелов).")
        return

    orig_chat_id = info["orig_chat_id"]
    orig_msg_id = info["orig_msg_id"]

    # Отправляем пометку в исходный чат (reply к заявке)
    try:
        await bot.send_message(
            orig_chat_id,
            f"Доставка для {target}",
            reply_to_message_id=orig_msg_id,
        )
    except Exception as e:
        await message.reply(f"Ошибка при уведомлении исходного чата: {e}")
        return

    # Отправляем подтверждение админу и запланируем удаление:
    try:
        confirm = await message.reply("Готово — уведомил чат.")
    except Exception:
        confirm = None

    # Планируем удаление: сам admin message (с @username) и подтверждения (если есть)
    to_delete = [message.message_id]
    if confirm:
        to_delete.append(confirm.message_id)

    asyncio.create_task(delete_messages_later(UNIQUE_USER_ID, to_delete, delay=5 * 60))

    # (Оставляем карточку админа в ЛС — она не удаляется, чтобы админ видел историю заявок)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
