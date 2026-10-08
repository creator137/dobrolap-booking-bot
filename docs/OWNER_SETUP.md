# Что попросить у владельца (календарь Лист1)

Бот читает **реальный календарь занятости** (лист `Лист1`):
- колонка A — категория, B — комната/номер, C+ — даты;
- ручные пометки хозяйки учитываются;
- против прода по умолчанию `GOOGLE_SHEETS_READONLY=true` (запись выключена).

Готовый скрипт: [`integrations/apps_script/Code.gs`](../integrations/apps_script/Code.gs)
(Apps Script Web App + `LockService` для атомарного reserve).

Альтернатива: service account JSON + `GOOGLE_SHEETS_SPREADSHEET_ID`
(тот же grid-формат; атомарность слабее, чем у Apps Script).

## Строки календаря уже сняты с прод-таблицы

Таблица «Размещение добролап» прочитана service account’ом. Подписи строк
и маппинг на каталог лежат в:

- `config/sheets_mapping.yaml` (`room_aliases`)
- `config/accommodations.yaml` (`sheet_unit_id` / `sheet_unit_ids`)

Соответствие на момент съёмки: все рабочие строки Лист1 замаплены, кроме
**«Ванная»** (категория «Резерв») — в каталог намеренно не включена.

Спрашивать владельца «какие подписи в таблице» не нужно — они уже известны.
Уточнять имеет смысл только бизнес-решения (пулы вроде Комфорт 1/2/3,
два домика VIP+, тариф для А+А), не сами названия ячеек.

## Обязательно у владельца (запуск / запись)

1. Открыть таблицу «Размещение добролап».
2. **Расширения → Apps Script** → вставить `Code.gs`.
3. Проверить `CALENDAR_SHEET = "Лист1"`.
4. Задать `SCRIPT_TOKEN` (длинный секрет).
5. Deploy → Web app → Execute as **Me**, Who has access: **Anyone**.
6. Прислать URL + token → в `.env`:
   ```env
   GOOGLE_SHEETS_ENABLED=true
   GAS_WEBAPP_URL=https://script.google.com/macros/s/.../exec
   GAS_WEBAPP_TOKEN=секрет
   ```

### Либо через service account

1. Расшарить таблицу на email сервисного аккаунта (Редактор).
2. Spreadsheet ID уже известен (см. `.env` локально; в Git не коммитить).
3. В `.env`:
   ```env
   GOOGLE_SHEETS_ENABLED=true
   GOOGLE_SHEETS_SPREADSHEET_ID=...
   GOOGLE_SERVICE_ACCOUNT_FILE=secrets/google-service-account.json
   GOOGLE_SHEETS_READONLY=true
   ```

Если `GOOGLE_SHEETS_ENABLED=true`, но доступ не настроен — бот **не** показывает
свободные места (fail-closed), а не притворяется, что всё свободно.

Испытания с записью — только на **копии** таблицы (`READONLY=false` только там).

## Для запуска бота

| Поле | Откуда |
|---|---|
| `BOT_TOKEN` | @BotFather |
| `OWNER_CHAT_ID` | numeric id (@userinfobot) |
| `PAYMENT_INSTRUCTIONS` | текст реквизитов залога |

## Позже уточнить (не блокирует старт)

- подтвердить отнесение ровно 10 кг к средней категории; тарифы «Домик кухня» и «Домик под лестницей»
- праздники / early booking; условия реального промокода `ДОБРОЛАПКИ` уже настроены, но нужна история гостей вне бота
- единица натурального питания 150–250 ₽  
- количество выгулов/зоотакси в анкете  
