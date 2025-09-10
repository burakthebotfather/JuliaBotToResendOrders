import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from datetime import datetime
import os

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
    -1002079167705: "A. Mousse Art Bakery, Белинского, 23",
    -1002387655137: "B. Millionroz.by, Тимирязева, 67",
    -1002423500927: "E. Flovi.Studio, Тимирязева, 65Б",
    -1002178818697: "H. Kudesnica.by, Старовиленский тракт, 10"
    -1002477650634: "I. Cvetok.by, Восточная, 41"
    -1002660511483: "K. Pastel Flowers, Сурганова, 31"
    -1002864795738: "G. Цветы Мира, Академическая, 6"
}

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Счётчик заявок по дате
message_counter = {"date": None, "count": 0}

def get_request_number():
    today = datetime.now().strftime("%d.%m.%Y")
    if message_counter["date"] != today:
        message_counter["date"] = today
        message_counter["count"] = 0
    message_counter["count"] += 1
    return f"{message_counter['count']:02d} / {today}"

@dp.message(F.chat.id.in_(ALLOWED_THREADS.keys()))
async def handle_message(message: Message):
    if message.message_thread_id != ALLOWED_THREADS.get(message.chat.id):
        return

    if len(message.text or "") < 50:
        return

    if message.from_user.id == UNIQUE_USER_ID:
        return

    request_number = get_request_number()

    # Получаем название чата
    chat_name = CHAT_NAMES.get(message.chat.id, f"Chat {message.chat.id}")

    # Пересылаем в личку с названием чата
    await bot.send_message(
        UNIQUE_USER_ID,
        f"Заявка {request_number} ({chat_name}):\n{message.text}"
    )

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
