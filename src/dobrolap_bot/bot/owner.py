from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import CallbackQuery, Message, TelegramObject

from dobrolap_bot.bot.keyboards import client_reply_kb, owner_actions_kb
from dobrolap_bot.bot.states import BookingForm, OwnerForm
from dobrolap_bot.config.loader import Catalog
from dobrolap_bot.services.booking import BookingService, InvalidTransitionError
from dobrolap_bot.services.summary import format_client_status, format_owner_summary

router = Router(name="owner")


class OwnerOnly(BaseFilter):
    async def __call__(self, event: TelegramObject, owner_chat_id: int | None) -> bool:
        if owner_chat_id is None:
            return False
        user = getattr(event, "from_user", None)
        return bool(user and user.id == owner_chat_id)


router.message.filter(OwnerOnly())
router.callback_query.filter(OwnerOnly())


def _parse_owner_cb(data: str) -> tuple[str, str] | None:
    # own:action:booking_id
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "own":
        return None
    return parts[1], parts[2]


@router.callback_query(F.data.startswith("own:approve:"))
async def owner_approve(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
    catalog: Catalog,
    payment_instructions: str,
) -> None:
    parsed = _parse_owner_cb(callback.data or "")
    if not parsed:
        await callback.answer()
        return
    _, booking_id = parsed
    try:
        booking = await booking_service.approve(booking_id)
    except ValueError as exc:
        msg = str(exc)
        if msg == "unit_required":
            await callback.message.answer(
                "Сначала выберите помещение кнопкой «Другой вариант», затем подтвердите заявку."
            )
        elif "unit_occupied" in msg:
            await callback.message.answer(
                "Место уже занято в календаре (возможно, вручную). "
                "Предложите другой вариант или отклоните заявку."
            )
        else:
            await callback.message.answer(f"Не могу подтвердить: {exc}")
        await callback.answer()
        return
    except InvalidTransitionError as exc:
        await callback.message.answer(f"Неверный статус: {exc}")
        await callback.answer()
        return
    except Exception as exc:
        await callback.message.answer(f"Календарь недоступен: {exc}")
        await callback.answer()
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"Заявка {booking_id} подтверждена, ждём оплату и чек.\n"
        "Кнопка «Оплата получена» появится после того, как клиент пришлёт чек.\n\n"
        + format_owner_summary(booking, catalog),
    )

    client_id = booking.customer_telegram_id
    if client_id and callback.bot:
        pay_text = payment_instructions.strip() or (
            "Реквизиты не заданы в .env (PAYMENT_INSTRUCTIONS). "
            "Свяжитесь с владельцем напрямую."
        )
        await callback.bot.send_message(
            client_id,
            "Вашу заявку подтвердили ✅\n\n"
            f"{format_client_status(booking, catalog)}\n\n"
            "Оплатите залог по инструкции ниже и пришлите чек (фото или PDF):\n\n"
            f"{pay_text}",
        )
        waiting = await booking_service.repo.list_by_telegram(
            client_id, statuses=[booking.status]
        )
        if len(waiting) > 1:
            await callback.bot.send_message(
                client_id,
                f"У вас несколько заявок на оплату. Перед отправкой чека выберите эту: /receipt {booking_id}",
            )
        # Best-effort FSM hint; receipt also accepted via SQLite lookup.
        key = StorageKey(
            bot_id=callback.bot.id,
            chat_id=client_id,
            user_id=client_id,
        )
        await state.storage.set_state(key, BookingForm.waiting_receipt)
        await state.storage.set_data(key, {"booking_id": booking_id} if len(waiting) == 1 else {})

    await callback.answer("Подтверждено")


@router.callback_query(F.data.startswith("own:reject:"))
async def owner_reject_start(callback: CallbackQuery, state: FSMContext) -> None:
    parsed = _parse_owner_cb(callback.data or "")
    if not parsed:
        await callback.answer()
        return
    _, booking_id = parsed
    await state.set_state(OwnerForm.reject_reason)
    await state.update_data(owner_booking_id=booking_id)
    await callback.message.answer(
        f"Укажите причину отклонения заявки {booking_id} (или «-» без причины)."
    )
    await callback.answer()


@router.message(OwnerForm.reject_reason)
async def owner_reject_finish(
    message: Message,
    state: FSMContext,
    booking_service: BookingService,
    catalog: Catalog,
) -> None:
    data = await state.get_data()
    booking_id = data.get("owner_booking_id")
    if not booking_id:
        await state.clear()
        return
    reason = (message.text or "").strip()
    if reason == "-":
        reason = None
    booking = await booking_service.reject(booking_id, reason)
    await state.clear()
    await message.answer(f"Заявка {booking_id} отклонена.")
    client_id = booking.customer_telegram_id
    if client_id and message.bot:
        text = "К сожалению, заявка отклонена."
        if reason:
            text += f"\nПричина: {reason}"
        text += "\nМожно создать новую: /start"
        await message.bot.send_message(client_id, text)


@router.callback_query(F.data.startswith("own:ask:"))
async def owner_ask_start(callback: CallbackQuery, state: FSMContext) -> None:
    parsed = _parse_owner_cb(callback.data or "")
    if not parsed:
        await callback.answer()
        return
    _, booking_id = parsed
    await state.set_state(OwnerForm.ask_question)
    await state.update_data(owner_booking_id=booking_id)
    await callback.message.answer(f"Вопрос клиенту по заявке {booking_id}:")
    await callback.answer()


@router.message(OwnerForm.ask_question)
async def owner_ask_finish(
    message: Message,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    data = await state.get_data()
    booking_id = data.get("owner_booking_id")
    text = (message.text or "").strip()
    if not booking_id or not text:
        await message.answer("Нужен текст вопроса.")
        return
    booking = await booking_service.add_owner_question(booking_id, text)
    await state.clear()
    await message.answer("Вопрос отправлен клиенту.")
    client_id = booking.customer_telegram_id
    if client_id and message.bot:
        await message.bot.send_message(
            client_id,
            f"Вопрос от владельца по заявке {booking_id}:\n{text}",
            reply_markup=client_reply_kb(booking_id),
        )


@router.callback_query(F.data.startswith("own:alt:"))
async def owner_alt_start(callback: CallbackQuery, state: FSMContext, catalog: Catalog) -> None:
    parsed = _parse_owner_cb(callback.data or "")
    if not parsed:
        await callback.answer()
        return
    _, booking_id = parsed
    await state.set_state(OwnerForm.suggest_unit)
    await state.update_data(owner_booking_id=booking_id)
    units = "\n".join(f"• `{a.id}` — {a.name}" for a in catalog.active_accommodations())
    await callback.message.answer(
        f"Предложите другой вариант для {booking_id}.\n"
        f"Пришлите id помещения:\n{units}"
    )
    await callback.answer()


@router.message(OwnerForm.suggest_unit)
async def owner_alt_finish(
    message: Message,
    state: FSMContext,
    booking_service: BookingService,
    catalog: Catalog,
) -> None:
    data = await state.get_data()
    booking_id = data.get("owner_booking_id")
    unit_id = (message.text or "").strip().strip("`")
    if not booking_id:
        await state.clear()
        return
    try:
        booking, quote = await booking_service.suggest_unit(booking_id, unit_id)
    except ValueError as exc:
        await message.answer(f"Не получилось: {exc}. Пришлите другой id.")
        return
    except InvalidTransitionError as exc:
        await message.answer(f"Статус не позволяет: {exc}")
        await state.clear()
        return

    await state.clear()
    summary = format_owner_summary(booking, catalog)
    await message.answer(
        f"Вариант обновлён.\n{summary}\nПредварительно: {quote.total_rub} ₽",
        reply_markup=owner_actions_kb(booking_id),
    )
    client_id = booking.customer_telegram_id
    unit = catalog.get_accommodation(unit_id)
    if client_id and message.bot and unit:
        await message.bot.send_message(
            client_id,
            "Владелец предложил другой вариант размещения:\n"
            f"{unit.name}\n"
            f"Предварительно: {quote.total_rub} ₽, залог {quote.deposit_rub} ₽\n"
            "Ожидайте подтверждения или ответьте на вопрос, если он придёт.",
        )


@router.callback_query(F.data.startswith("own:paid:"))
async def owner_paid(
    callback: CallbackQuery,
    booking_service: BookingService,
    catalog: Catalog,
) -> None:
    parsed = _parse_owner_cb(callback.data or "")
    if not parsed:
        await callback.answer()
        return
    _, booking_id = parsed
    try:
        booking = await booking_service.confirm_payment(booking_id)
    except ValueError as exc:
        if str(exc) == "receipt_required":
            await callback.message.answer(
                "Сначала дождитесь чека от клиента — кнопка сработает после загрузки чека."
            )
        elif str(exc) == "unit_required":
            await callback.message.answer("Для этой заявки не выбрано место в календаре. Выберите место и подтвердите заявку заново.")
        else:
            await callback.message.answer(f"Не могу зафиксировать: {exc}")
        await callback.answer()
        return
    except InvalidTransitionError as exc:
        await callback.message.answer(f"Неверный статус: {exc}")
        await callback.answer()
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        f"Бронь {booking_id} подтверждена (CONFIRMED).\n" + format_owner_summary(booking, catalog)
    )
    client_id = booking.customer_telegram_id
    if client_id and callback.bot:
        await callback.bot.send_message(
            client_id,
            "Оплата подтверждена, бронь зафиксирована ✅\n"
            + format_client_status(booking, catalog)
            + "\nДо встречи!",
        )
    await callback.answer("Оплата принята")
