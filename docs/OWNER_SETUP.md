# Что попросить у владельца (доступ к таблице)

Бот ходит в Google Sheets **через Apps Script Web App** — без service account и без шаринга таблицы на ИИ.

Готовый код: [`integrations/apps_script/Code.gs`](../integrations/apps_script/Code.gs).

## Что сделать владельцу (5–10 минут)

1. Открыть таблицу «Размещение добролап».
2. **Расширения → Apps Script** → вставить `Code.gs` → сохранить.
3. В скрипте заменить `SCRIPT_TOKEN` на длинный секрет (тот же в `.env` как `GAS_WEBAPP_TOKEN`).
4. **Deploy → New deployment → Web app**
   - Execute as: **Me**
   - Who has access: **Anyone**
5. Скопировать URL web app → в `.env`:
   ```env
   GOOGLE_SHEETS_ENABLED=true
   GAS_WEBAPP_URL=https://script.google.com/macros/s/.../exec
   GAS_WEBAPP_TOKEN=тот_же_секрет
   ```
6. При первом `upsert` скрипт сам создаст лист `Bookings` с колонками:
   `external_id | unit_id | date_from | date_to | status`

Если календарь уже на другом листе — в `Code.gs` поменять `SHEET_NAME` и при необходимости порядок колонок.

## Что ещё дать для запуска бота (не таблица)

| Поле `.env` | Откуда |
|---|---|
| `BOT_TOKEN` | @BotFather |
| `OWNER_CHAT_ID` | numeric id чата владельца (можно узнать у `@userinfobot`) |
| `PAYMENT_INSTRUCTIONS` | текст реквизитов для залога |

## Если «доступа к таблице нет» у разработчика

Это нормально. Достаточно, чтобы **владелец** вставил скрипт в *свою* таблицу и прислал только:
- URL web app
- token

Структуру старого календаря смотреть не обязательно: бот пишет/читает нормализованный лист `Bookings`.

## Позже уточнить у владельца (не блокирует запуск)

- граница крупной собаки: 20 vs 25 кг  
- VIP vs VIP+, фото `А+А` / `unknown`  
- праздники / early booking / soft-hold TTL  
- единица тарифа натурального питания (150–250 ₽)
