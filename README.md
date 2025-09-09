# Telegram Thread Bot

Этот бот отслеживает сообщения в указанных чатах/тредах и пересылает заявки администратору.

## Переменные окружения

- `BOT_TOKEN` — API токен Telegram-бота
- `UNIQUE_USER_ID` — ID пользователя, которому будут пересылаться заявки

## Запуск локально

```bash
pip install -r requirements.txt
BOT_TOKEN=xxx UNIQUE_USER_ID=542345855 python main.py
```

## Деплой на Railway

1. Залить проект на GitHub
2. Подключить репозиторий к Railway
3. Добавить переменные окружения:
   - `BOT_TOKEN`
   - `UNIQUE_USER_ID`
4. Деплойнуть сервис
