# Что попросить у владельца (календарь Лист1)

Бот читает **реальный календарь занятости** (лист `Лист1`):
- колонка A — категория, B — комната/номер, C+ — даты;
- ручные пометки хозяйки учитываются;
- против прода по умолчанию `GOOGLE_SHEETS_READONLY=true` (запись выключена).

Готовый скрипт: [`integrations/apps_script/Code.gs`](../integrations/apps_script/Code.gs)
(Apps Script Web App + `LockService` для атомарного reserve).

Альтернатива: service account JSON + `GOOGLE_SHEETS_SPREADSHEET_ID`
(тот же grid-формат; атомарность слабее, чем у Apps Script).

## Обязательно у владельца

1. Открыть таблицу «Размещение добролап».
2. **Расширения → Apps Script** → вставить `Code.gs`.
3. Проверить `CALENDAR_SHEET = "Лист1"` (или фактическое имя листа-календаря).
4. Задать `SCRIPT_TOKEN` (длинный секрет).
5. Deploy → Web app → Execute as **Me**, Who has access: **Anyone**.
6. Прислать URL + token → в `.env`:
   ```env
   GOOGLE_SHEETS_ENABLED=true
   GAS_WEBAPP_URL=https://script.google.com/macros/s/.../exec
   GAS_WEBAPP_TOKEN=секрет
   ```
7. Сверить, что названия комнат в колонке A совпадают с `sheet_unit_id`
   в `config/accommodations.yaml` (сейчас = русские имена из каталога).
   Если в таблице другие подписи — прислать список строк A, подправим mapping.

### Либо через service account

1. Расшарить таблицу на email сервисного аккаунта (Редактор).
2. Прислать spreadsheet ID из URL.
3. В `.env`:
   ```env
   GOOGLE_SHEETS_ENABLED=true
   GOOGLE_SHEETS_SPREADSHEET_ID=...
   GOOGLE_SERVICE_ACCOUNT_FILE=secrets/google-service-account.json
   ```

Если `GOOGLE_SHEETS_ENABLED=true`, но доступ не настроен — бот **не** показывает
свободные места (fail-closed), а не притворяется, что всё свободно.

## Для запуска бота

| Поле | Откуда |
|---|---|
| `BOT_TOKEN` | @BotFather |
| `OWNER_CHAT_ID` | numeric id (@userinfobot) |
| `PAYMENT_INSTRUCTIONS` | текст реквизитов залога |

## Позже уточнить (не блокирует старт)

- точные подписи строк комнат в Лист1  
- граница крупной собаки 20 vs 25 кг, VIP vs VIP+  
- праздники / early booking / реальный промокод  
- единица натурального питания 150–250 ₽  
- количество выгулов/зоотакси в анкете  
