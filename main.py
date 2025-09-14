import asyncio
import re
import os
from datetime import datetime, timedelta
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

# mapping: admin_message_id -> info dict
# info keys:
#   orig_chat_id: int
#   orig_msg_id: int
#   orig_bot_reply_id: int  # id сообщения-ответа бота в исходном чате ("Заказ принят..." и т.п.)
#   orig_notification_msg_id: int | None  # id пометки "Доставка для @nik" в исходном чате (после назначения)
#   admin_notification_msg_id: int | None  # id копии "Доставка для @nik" в лс админа (удаляем через 5мин)
#   admin_confirm_msg_id: int | None       # id сообщения "Готово — уведомил чат." в лс админа (удаляем через 5мин)
assign_mapping: dict[int, dict] = {}

AUTO_DELETE_DELAY = 5 * 60  # 5 минут


def is_night_time() -> bool:
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


async def schedule_admin_delete(admin_sent_msg_id: int, delay: int = AUTO_DELETE_DELAY):
    """Через delay секунд удаляем в ЛС админа admin_notification_msg_id и admin_confirm_msg_id (если есть)."""
    await asyncio.sleep(delay)
    info = assign_mapping.get(admin_sent_msg_id)
    if not info:
        return

    admin_notif_id = info.get("admin_notification_msg_id")
    admin_confirm_id = info.get("admin_confirm_msg_id")

    # удаляем сначала "Доставка для @nik" в ЛС админа
    if admin_notif_id:
        try:
            await bot.delete_message(chat_id=UNIQUE_USER_ID, message_id=admin_notif_id)
        except Exception:
            pass

    # затем удаляем "Готово — уведомил чат."
    if admin_confirm_id:
        try:
            await bot.delete_message(chat_id=UNIQUE_USER_ID, message_id=admin_confirm_id)
        except Exception:
            pass

    # очищаем mapping
    assign_mapping.pop(admin_sent_msg_id, None)


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

    night = is_night_time()

    if night:
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

    # отправляем и сохраняем id ответа бота в исходном чате
    try:
        bot_reply = await message.reply(reply_text)
        bot_reply_id = bot_reply.message_id
    except Exception:
        bot_reply_id = None

    # карточка для администратора
    header = f"{request_number}\n{chat_name}\n\n"
    forward_text = header + (message.text or "")
    if status == "invalid":
        forward_text = "❌ ОТКЛОНЕН ❌\n\n" + forward_text
    if night:
        forward_text = "НОЧНОЙ ЗАКАЗ 🌙\n\n" + forward_text

    # кнопка "Выполнен ✅" под карточкой в ЛС админа
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выполнен ✅", callback_data="done")]
    ])

    sent = await bot.send_message(
        UNIQUE_USER_ID,
        forward_text,
        reply_markup=kb,
        disable_notification=night
    )

    # сохраняем связь: admin_sent_msg_id -> информация
    assign_mapping[sent.message_id] = {
        "orig_chat_id": message.chat.id,
        "orig_msg_id": message.message_id,
        "orig_bot_reply_id": bot_reply_id,
        "orig_notification_msg_id": None,
        "admin_notification_msg_id": None,
        "admin_confirm_msg_id": None,
    }


@dp.message(F.from_user.id == UNIQUE_USER_ID, F.reply_to_message)
async def handle_assign_reply(message: Message):
    """
    Админ отвечает на карточку бота ником исполнителя.
    Удаляем в исходном чате "Заказ принят..." (ботовый ответ),
    отправляем уведомление в исходный чат и делаем копию + подтверждение в ЛС админа,
    через 5 минут — удаляем эти два сообщения в ЛС админа.
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
    orig_bot_reply_id = info.get("orig_bot_reply_id")

    # 1) удаляем в исходном чате бот-ответ ("Заказ принят..." и т.п.), если он есть
    if orig_bot_reply_id:
        try:
            await bot.delete_message(chat_id=orig_chat_id, message_id=orig_bot_reply_id)
        except Exception:
            # возможно удалено ранее — игнорируем
            pass

    # 2) отправляем пометку в исходный чат (reply к заявке)
    try:
        orig_notif = await bot.send_message(
            orig_chat_id,
            f"Доставка для {target}",
            reply_to_message_id=orig_msg_id,
        )
        info["orig_notification_msg_id"] = orig_notif.message_id
    except Exception as e:
        await message.reply(f"Ошибка при уведомлении исходного чата: {e}")
        return

    # 3) делаем копию пометки в ЛС админа (чтобы она была в лс и её можно было удалить через 5 минут)
    try:
        admin_notif = await bot.send_message(
            UNIQUE_USER_ID,
            f"Доставка для {target}",
            reply_to_message_id=admin_sent_msg_id,
        )
        info["admin_notification_msg_id"] = admin_notif.message_id
    except Exception:
        info["admin_notification_msg_id"] = None

    # 4) отправляем подтверждение админу "Готово — уведомил чат."
    try:
        admin_confirm = await message.reply("Готово — уведомил чат.")
        info["admin_confirm_msg_id"] = admin_confirm.message_id
    except Exception:
        info["admin_confirm_msg_id"] = None

    # обновляем mapping
    assign_mapping[admin_sent_msg_id] = info

    # 5) запускаем задачу авто-удаления (удалит две записи в лс админа)
    asyncio.create_task(schedule_admin_delete(admin_sent_msg_id))

    # (Не удаляем orig_notification_msg автоматически — по требованию он остаётся в чате.
    #  Если хочешь, можно и его планировать на удаление — скажи.)

    # Обновление done-кнопки: оставляем её под исходной карточкой администратора (она уже там).
    # В случае, если нужно — можно добавить кнопку под orig_notification и под admin_notif.
    # Сейчас кнопка "Выполнен ✅" под исходной карточкой удаляет саму карточку и (если найдено) удаляет orig_notification.


@dp.callback_query(F.data == "done")
async def mark_done(callback: CallbackQuery):
    """Нажали 'Выполнен ✅' под сообщением админу — удаляем карточку в ЛС админа и, если есть, пометку в исходном чате."""
    await callback.answer("Отмечено как выполненное — скрываю сообщение.")
    admin_msg_id = callback.message.message_id
    info = assign_mapping.get(admin_msg_id)

    # удаляем само сообщение (карточку) в ЛС админа
    try:
        await bot.delete_message(chat_id=UNIQUE_USER_ID, message_id=admin_msg_id)
    except Exception:
        pass

    # если есть уведомление в исходном чате — удаляем его
    if info:
        orig_notif_id = info.get("orig_notification_msg_id")
        orig_chat = info.get("orig_chat_id")
        if orig_notif_id and orig_chat:
            try:
                await bot.delete_message(chat_id=orig_chat, message_id=orig_notif_id)
            except Exception:
                pass
        # чистим mapping
        assign_mapping.pop(admin_msg_id, None)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
