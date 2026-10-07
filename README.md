# dobrolap-booking-bot

Telegram-бот бронирования зоогостиницы «Добролап».

MVP-поток реализован: анкета → подбор → услуги → ручное подтверждение → реквизиты → чек → фиксация.

## Документация

- [Архитектура](docs/ARCHITECTURE.md)
- [План реализации](docs/IMPLEMENTATION.md)
- [Доступ к таблице (Apps Script)](docs/OWNER_SETUP.md)
- [Реестр материалов](docs/source/materials-inventory.md)

## Быстрый старт

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# BOT_TOKEN, OWNER_CHAT_ID, PAYMENT_INSTRUCTIONS
# Sheets: см. docs/OWNER_SETUP.md → GAS_WEBAPP_URL + GAS_WEBAPP_TOKEN
pytest
python -m dobrolap_bot
```

## Переменные окружения

| Переменная | Назначение |
|---|---|
| `BOT_TOKEN` | токен Telegram-бота |
| `OWNER_CHAT_ID` | numeric chat id владельца |
| `PAYMENT_INSTRUCTIONS` | текст реквизитов (после approve) |
| `GAS_WEBAPP_URL` | URL Apps Script Web App |
| `GAS_WEBAPP_TOKEN` | общий секрет с `SCRIPT_TOKEN` в Code.gs |
| `GOOGLE_SHEETS_ENABLED` | `true` после деплоя скрипта |
| `DATABASE_PATH` | SQLite, по умолчанию `data/app.db` |

Секреты только в `.env`, не в Git.

## Что умеет бот

**Клиент:** согласие, даты, несколько питомцев, паспорт, подбор места, питание, доп. услуги, отправка заявки, статус `/status`, ответ владельцу, загрузка чека. Если одновременно ожидают оплату несколько заявок, перед чеком нужно выбрать нужную командой `/receipt НОМЕР_ЗАЯВКИ`.

**Владелец:** подтвердить, задать вопрос, предложить другой unit id, отклонить, принять оплату.

Живой Google Sheets и LLM — следующие внешние шаги после данных от владельца.
