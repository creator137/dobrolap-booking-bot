# План реализации

Основано на [ARCHITECTURE.md](ARCHITECTURE.md).

## Фазы

| Фаза | Содержание | Статус |
|---|---|---|
| 0 | Скелет пакета, pyproject, `.env.example` | ✅ |
| 1 | Domain models + YAML-каталоги | ✅ |
| 2 | PlacementRules + PricingService + тесты | ✅ |
| 3 | SQLite + переходы статусов | ✅ |
| 4 | aiogram FSM клиента | ✅ |
| 5 | Sheets через Apps Script Web App (+ stub/SA fallback) | ✅ |
| 6 | Оператор, реквизиты, чек, услуги, отмена | ✅ |
| 7 | Optional LLM | stub готов, выключен |
| 8 | Docker-образ | ✅ Dockerfile |

Инструкция владельцу по таблице: [OWNER_SETUP.md](OWNER_SETUP.md).

## Полный поток MVP

1. Клиент: `/start` → согласие → даты → анкета → паспорт → подбор → питание → услуги → отправка.
2. Владелец получает сводку + кнопки: подтвердить / вопрос / другой вариант / отклонить.
3. После подтверждения клиенту уходят `PAYMENT_INSTRUCTIONS`, статус `WAITING_PAYMENT`.
4. Клиент шлёт чек (фото/PDF) → владельцу кнопка «Оплата получена».
5. `CONFIRMED` + upsert через Apps Script в лист `Bookings`.

Команды клиента: `/start`, `/cancel`, `/status`, `/cancel_booking`.

## Что попросить у владельца

См. [OWNER_SETUP.md](OWNER_SETUP.md): Apps Script deploy + `BOT_TOKEN` / `OWNER_CHAT_ID` / `PAYMENT_INSTRUCTIONS`.
