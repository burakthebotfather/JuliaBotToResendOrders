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

# admin_msg_id -> dict с данными
# структура:
# {
#   "orig_chat_id": int,
#   "orig_msg_id": int,
#   "accept_reply_id": int|None,
#   "request_number": str,
#   "admin_text": str,
#   "driver_id": int|None,
#   "driver_msg_id": int|None,
#   "driver_state": str|None
# }
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


# --- клавиатуры ---
def admin_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять", callback_data="decision:accept"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data="decision:reject"),
        ],
        [InlineKeyboardButton(text="🟢 Выполнен", callback_data="decision:done")]
    ])
    return kb


def driver_keyboard(admin_msg_id: int, state: str | None = None) -> InlineKeyboardMarkup:
    """
    Кнопки для водителя (локально, вариант A).
    callback_data формата: drv:<action>:<admin_msg_id>
    """
    def label(base):
        if state and base == state:
            return f"{base} ✅"
        return base

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label("Принять"), callback_data=f"drv:accept:{admin_msg_id}")],
        [InlineKeyboardButton(text=label("В пути за заказом"), callback_data=f"drv:onway:{admin_msg_id}")],
        [InlineKeyboardButton(text=label("Заказ получен"), callback_data=f"drv:got:{admin_msg_id}")],
        [InlineKeyboardButton(text=label("Выполнен"), callback_data=f"drv:done:{admin_msg_id}")],
    ])
    return kb


# --------------------------
# Обработка входящих сообщений из чатов
# --------------------------
@dp.message(F.chat.id.in_(ALLOWED_THREADS.keys()))
async def handle_message(message: Message):
    """Обработка заявок из чатов."""
    # проверяем thread_id
    expected_thread = ALLOWED_THREADS.get(message.chat.id)
    if getattr(message, "message_thread_id", None) != expected_thread:
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

    kb = admin_keyboard()

    sent = await bot.send_message(
        UNIQUE_USER_ID,
        forward_body,
        reply_markup=kb,
        disable_notification=night,
    )

    # сохраняем в mapping; ключ = message_id в чате админа
    assign_mapping[sent.message_id] = {
        "orig_chat_id": message.chat.id,
        "orig_msg_id": message.message_id,
        "accept_reply_id": None,
        "request_number": request_number,
        "admin_text": forward_body,  # полезно для отправки водителю
        "driver_id": None,
        "driver_msg_id": None,
        "driver_state": None,
    }


# --------------------------
# Обработчики кнопок - админ
# --------------------------
@dp.callback_query(F.data.startswith("decision:"))
async def handle_decision(callback: CallbackQuery):
    """Принят/отклонён/выполнен."""
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
            sent = await bot.send_message(orig_chat_id, "Заказ принят в работу.", reply_to_message_id=orig_msg_id)
            info["accept_reply_id"] = sent.message_id
        except Exception:
            pass
        popup = "Отметил как принятый."

        # оставляем только кнопку "Выполнен"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Выполнен", callback_data="decision:done")]
        ])
        try:
            await bot.edit_message_reply_markup(UNIQUE_USER_ID, admin_msg_id, reply_markup=kb)
        except Exception:
            pass

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
        try:
            await bot.edit_message_reply_markup(UNIQUE_USER_ID, admin_msg_id, reply_markup=kb)
        except Exception:
            pass

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


# --------------------------
# Назначение водителя через reply админа на карточку
# --------------------------
@dp.message(F.from_user.id == UNIQUE_USER_ID, F.reply_to_message)
async def handle_admin_assign_reply(message: Message):
    """Назначение водителя через @username."""
    reply_to = message.reply_to_message
    if not reply_to:
        return

    admin_sent_msg_id = reply_to.message_id
    info = assign_mapping.get(admin_sent_msg_id)
    if not info:
        await message.reply("Информация по этой заявке устарела или не найдена.")
        return

    target = (message.text or "").strip()
    # ожидаем ровно один ник в формате @username
    if not target.startswith("@") or " " in target:
        await message.reply("Укажи ник в формате @username.")
        return

    orig_chat_id = info["orig_chat_id"]
    orig_msg_id = info["orig_msg_id"]

    # Удаляем "Заказ принят..." если был
    accept_reply_id = info.get("accept_reply_id")
    if accept_reply_id:
        try:
            await bot.delete_message(chat_id=orig_chat_id, message_id=accept_reply_id)
        except Exception:
            pass
        info["accept_reply_id"] = None

    # Отправляем "Доставка для ..."
    try:
        await bot.send_message(
            orig_chat_id,
            f"Доставка для {target}",
            reply_to_message_id=orig_msg_id,
        )
    except Exception as e:
        await message.reply(f"Ошибка при уведомлении исходного чата: {e}")
        return

    # --- НОВОЕ: отправляем дубликат карточки водителю в личку (вариант A) ---
    username = target.lstrip("@")
    try:
        # получаем chat объекта водителя; если ник неверный - исключение
        chat_obj = await bot.get_chat(f"@{username}")
        driver_id = chat_obj.id
    except Exception:
        await message.reply(f"Не удалось найти пользователя {target}. Проверь ник и попробуй снова.")
        return

    # Формируем текст карточки для водителя (идентичен карточке админу)
    admin_text = info.get("admin_text", "")
    driver_text = admin_text

    try:
        sent_to_driver = await bot.send_message(
            chat_id=driver_id,
            text=driver_text,
            reply_markup=driver_keyboard(admin_sent_msg_id, state=None),
        )
    except Exception:
        await message.reply(f"Не удалось отправить карточку {target}. Возможно, у пользователя закрыты личные сообщения.")
        return

    # Обновляем mapping
    info["driver_id"] = driver_id
    info["driver_msg_id"] = sent_to_driver.message_id
    info["driver_state"] = None
    assign_mapping[admin_sent_msg_id] = info

    # Подтверждаем админу и удаляем служебные сообщения через время
    confirm = await message.reply("Готово — уведомил чат и отправил карточку водителю в личку.")
    # удалим сообщения админа (его сообщение с ником и подтверждение) через 5 минут
    asyncio.create_task(delete_messages_later(UNIQUE_USER_ID, [message.message_id, confirm.message_id], delay=5 * 60))


# --------------------------
# Обработчики callback'ов — водитель (локально, вариант A)
# --------------------------
@dp.callback_query(F.data.startswith("drv:"))
async def handle_driver_callbacks(callback: CallbackQuery):
    """
    Формат callback.data: drv:<action>:<admin_msg_id>
    Действия: accept, onway, got, done
    """
    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.answer("Неверные данные", show_alert=True)
        return
    _, action, admin_msg_id_str = parts
    try:
        admin_msg_id = int(admin_msg_id_str)
    except Exception:
        await callback.answer("Неверный идентификатор заявки", show_alert=True)
        return

    info = assign_mapping.get(admin_msg_id)
    if not info:
        await callback.answer("Заявка не найдена или устарела.", show_alert=True)
        return

    # Обновляем состояние у водителя и только в его личном сообщении (вариант A)
    if action == "accept":
        info["driver_state"] = "Принять"
        try:
            await callback.message.edit_reply_markup(driver_keyboard(admin_msg_id, state="Принять"))
            await callback.answer("Вы приняли заявку")
        except Exception:
            await callback.answer("OK")
    elif action == "onway":
        info["driver_state"] = "В пути за заказом"
        try:
            await callback.message.edit_reply_markup(driver_keyboard(admin_msg_id, state="В пути за заказом"))
            await callback.answer("Отмечено: в пути за заказом")
        except Exception:
            await callback.answer("OK")
    elif action == "got":
        info["driver_state"] = "Заказ получен"
        try:
            await callback.message.edit_reply_markup(driver_keyboard(admin_msg_id, state="Заказ получен"))
            await callback.answer("Отмечено: заказ получен")
        except Exception:
            await callback.answer("OK")
    elif action == "done":
        info["driver_state"] = "Выполнен"
        try:
            # оставляем пометку "Выполнен ✅"
            await callback.message.edit_reply_markup(driver_keyboard(admin_msg_id, state="Выполнен"))
            await callback.answer("Отмечено: выполнено (водитель)")
        except Exception:
            await callback.answer("OK")
    else:
        await callback.answer("Неизвестное действие")

    # сохраняем изменения
    assign_mapping[admin_msg_id] = info


# --------------------------
# Запуск
# --------------------------
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
