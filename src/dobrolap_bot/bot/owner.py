from __future__ import annotations

from datetime import date

import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import CallbackQuery, Message, TelegramObject

from dobrolap_bot.bot.keyboards import (
    client_reply_kb,
    owner_actions_kb,
    owner_refund_kb,
    owner_unit_choice_kb,
)
from dobrolap_bot.bot.states import BookingForm, OwnerForm
from dobrolap_bot.config.loader import Catalog
from dobrolap_bot.domain.enums import BookingStatus, FeedingOption
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.integrations.google_sheets import SheetsUnavailableError
from dobrolap_bot.services.booking import BookingService, InvalidTransitionError
from dobrolap_bot.services.summary import format_client_status, format_owner_summary

router = Router(name="owner")
logger = logging.getLogger(__name__)


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
    except InvalidTransitionError:
        logger.exception("owner approve invalid transition booking=%s", booking_id)
        await callback.message.answer(
            "Действие уже неактуально: статус заявки изменился. Откройте свежую карточку."
        )
        await callback.answer()
        return
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
            logger.warning("owner approve rejected booking=%s reason=%s", booking_id, exc)
            await callback.message.answer(
                "Не удалось подтвердить заявку. Обновите карточку и попробуйте ещё раз."
            )
        await callback.answer()
        return
    except Exception:
        logger.exception("owner approve failed booking=%s", booking_id)
        await callback.message.answer(
            "Не удалось проверить календарь Google Sheets. Бронь не подтверждена — попробуйте позже."
        )
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
        pay_text = payment_instructions.strip()
        if not pay_text:
            logger.error("payment instructions are not configured booking=%s", booking_id)
            pay_text = (
                "Платёжные реквизиты временно недоступны. "
                "Владелец зоогостиницы свяжется с вами отдельно."
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
async def owner_reject_start(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    parsed = _parse_owner_cb(callback.data or "")
    if not parsed:
        await callback.answer()
        return
    _, booking_id = parsed
    booking = await booking_service.get(booking_id)
    if booking and booking.status != BookingStatus.WAITING_OWNER:
        await callback.message.answer(
            "«Отклонить» только для новых заявок. "
            "После одобрения используйте «Отменить бронь»."
        )
        await callback.answer()
        return
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
    try:
        booking = await booking_service.reject(booking_id, reason)
    except InvalidTransitionError:
        logger.exception("owner reject invalid transition booking=%s", booking_id)
        await state.clear()
        await message.answer("Заявку уже нельзя отклонить: её статус изменился.")
        return
    await state.clear()
    await message.answer(f"Заявка {booking_id} отклонена.")
    client_id = booking.customer_telegram_id
    if client_id and message.bot:
        text = "К сожалению, заявка отклонена."
        if reason:
            text += f"\nПричина: {reason}"
        text += "\nМожно создать новую: /start"
        await message.bot.send_message(client_id, text)


@router.callback_query(F.data.startswith("own:cancel:"))
async def owner_cancel_start(callback: CallbackQuery, state: FSMContext) -> None:
    parsed = _parse_owner_cb(callback.data or "")
    if not parsed:
        await callback.answer()
        return
    _, booking_id = parsed
    await state.set_state(OwnerForm.cancel_reason)
    await state.update_data(owner_booking_id=booking_id)
    await callback.message.answer(
        f"Причина отмены брони {booking_id}? (или «-» без причины).\n"
        "Место в календаре будет освобождено. Возврат залога — отдельной кнопкой после отмены."
    )
    await callback.answer()


@router.message(OwnerForm.cancel_reason)
async def owner_cancel_finish(
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
    try:
        before = await booking_service.get(booking_id)
        was_confirmed = bool(before and before.status == BookingStatus.CONFIRMED)
        booking = await booking_service.cancel(
            booking_id,
            reason,
            actor="owner",
            refund_pending=was_confirmed,
        )
    except InvalidTransitionError:
        logger.exception("owner cancel invalid transition booking=%s", booking_id)
        await state.clear()
        await message.answer("Бронь уже нельзя отменить: её статус изменился.")
        return
    except Exception:
        logger.exception("owner cancel failed booking=%s", booking_id)
        await message.answer(
            "Не удалось освободить место в календаре. Бронь не изменена; попробуйте позже."
        )
        return

    await state.clear()
    try:
        await message.answer(
            f"Бронь №{booking_id} отменена.\n" + format_owner_summary(booking, catalog),
            reply_markup=owner_refund_kb(booking_id)
            if (booking.payload.get("refund") or {}).get("status") == "pending"
            else None,
        )
    except Exception:
        await message.answer(f"Бронь {booking_id} отменена.")

    client_id = booking.customer_telegram_id
    if client_id and message.bot:
        text = f"Бронь {booking_id} отменена владельцем."
        if reason:
            text += f"\nПричина: {reason}"
        refund = booking.payload.get("refund") or {}
        if refund.get("status") == "pending":
            text += (
                "\nВозврат залога выполняется вручную — статус возврата придёт отдельно, "
                "когда владелец его отметит."
            )
        text += "\nНовая заявка: /start"
        await message.bot.send_message(client_id, text)


@router.callback_query(F.data.startswith("own:refund:"))
async def owner_refund_start(callback: CallbackQuery, state: FSMContext) -> None:
    parsed = _parse_owner_cb(callback.data or "")
    if not parsed:
        await callback.answer()
        return
    _, booking_id = parsed
    await state.set_state(OwnerForm.refund_note)
    await state.update_data(owner_booking_id=booking_id)
    await callback.message.answer(
        f"Отметьте возврат по заявке {booking_id}: сумма/комментарий (или «-»)."
    )
    await callback.answer()


@router.message(OwnerForm.refund_note)
async def owner_refund_finish(
    message: Message,
    state: FSMContext,
    booking_service: BookingService,
) -> None:
    data = await state.get_data()
    booking_id = data.get("owner_booking_id")
    if not booking_id:
        await state.clear()
        return
    note = (message.text or "").strip()
    if note == "-":
        note = None
    try:
        booking = await booking_service.mark_refund(booking_id, note)
    except InvalidTransitionError:
        logger.exception("owner refund invalid transition booking=%s", booking_id)
        await state.clear()
        await message.answer("Возврат сейчас нельзя отметить: статус заявки изменился.")
        return
    await state.clear()
    await message.answer(f"Возврат по {booking_id} отмечен.")
    client_id = booking.customer_telegram_id
    if client_id and message.bot:
        text = f"Владелец отметил возврат залога по заявке {booking_id}."
        if note:
            text += f"\nКомментарий: {note}"
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
async def owner_alt_start(
    callback: CallbackQuery,
    booking_service: BookingService,
    catalog: Catalog,
) -> None:
    parsed = _parse_owner_cb(callback.data or "")
    if not parsed:
        await callback.answer()
        return
    _, booking_id = parsed
    booking = await booking_service.get(booking_id)
    if booking is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    try:
        occupied = booking_service.occupied_catalog_ids(
            booking.date_from,
            booking.date_to,
            exclude_booking_id=booking.id,
        )
    except SheetsUnavailableError:
        logger.exception("owner alternatives sheets unavailable booking=%s", booking_id)
        await callback.message.answer(
            "Не удалось проверить календарь Google Sheets. Свободные помещения не показаны, "
            "чтобы случайно не предложить занятое место. Попробуйте позже."
        )
        await callback.answer()
        return

    pets = [PetProfile.model_validate(item) for item in booking.payload.get("pets") or []]
    result = booking_service.placement.suggest(
        pets,
        occupied_unit_ids=occupied,
        limit=len(catalog.accommodations),
    )
    choices: list[tuple[str, str]] = []
    for candidate in result.candidates:
        unit = candidate.accommodation
        if unit.id == booking.unit_id:
            continue
        try:
            feeding_raw = booking.payload.get("feeding")
            feeding = FeedingOption(feeding_raw) if feeding_raw else None
            quote = booking_service.pricing.quote(
                pets=pets,
                unit=unit,
                date_from=booking.date_from,
                date_to=booking.date_to,
                feeding=feeding,
                service_ids=list(booking.payload.get("service_ids") or []),
                promo_code=booking.payload.get("promo_code"),
                promo_eligible=bool(booking.payload.get("promo_rule_id")),
                promo_at=date.fromisoformat(booking.payload["promo_at"])
                if booking.payload.get("promo_at") else None,
            )
            price = f" — {quote.total_rub:,} ₽".replace(",", " ")
        except Exception:
            logger.exception(
                "owner alternative quote failed booking=%s unit=%s", booking_id, unit.id
            )
            price = " — цена уточняется"
        choices.append((unit.id, f"{unit.name}{price}"))

    if not choices:
        await callback.message.answer(
            "Других подходящих свободных помещений на эти даты сейчас нет."
        )
        await callback.answer()
        return
    await callback.message.answer(
        f"Выберите другое подходящее свободное помещение для заявки №{booking_id}:",
        reply_markup=owner_unit_choice_kb(booking_id, choices),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ownunit:"))
async def owner_alt_finish(
    callback: CallbackQuery,
    booking_service: BookingService,
    catalog: Catalog,
) -> None:
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3:
        await callback.answer()
        return
    _, booking_id, unit_id = parts
    if unit_id == "close":
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Список закрыт")
        return
    try:
        booking, quote = await booking_service.suggest_unit(booking_id, unit_id)
    except SheetsUnavailableError:
        logger.exception("owner suggest sheets unavailable booking=%s", booking_id)
        await callback.message.answer(
            "Календарь Google Sheets сейчас недоступен. Помещение не изменено."
        )
        await callback.answer()
        return
    except InvalidTransitionError:
        logger.exception("owner suggest invalid transition booking=%s", booking_id)
        await callback.message.answer(
            "Помещение не изменено: статус заявки уже изменился."
        )
        await callback.answer()
        return
    except ValueError as exc:
        logger.warning(
            "owner suggest rejected booking=%s unit=%s reason=%s", booking_id, unit_id, exc
        )
        await callback.message.answer(
            "Это помещение уже занято или больше не подходит. Откройте список вариантов заново."
        )
        await callback.answer()
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    summary = format_owner_summary(booking, catalog)
    await callback.message.answer(
        f"Помещение в заявке обновлено.\n\n{summary}",
        reply_markup=owner_actions_kb(booking_id),
    )
    client_id = booking.customer_telegram_id
    unit = catalog.get_accommodation(unit_id)
    if client_id and callback.bot and unit:
        total = f"{quote.total_rub:,}".replace(",", " ")
        deposit = f"{quote.deposit_rub:,}".replace(",", " ")
        await callback.bot.send_message(
            client_id,
            "Владелец предложил другой вариант размещения:\n"
            f"{unit.name}\n"
            f"Предварительная стоимость: {total} ₽\n"
            f"Залог: {deposit} ₽\n"
            "Ожидайте подтверждения или ответьте на вопрос, если он придёт.",
        )
    await callback.answer("Помещение изменено")


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
    except InvalidTransitionError:
        logger.exception("owner payment invalid transition booking=%s", booking_id)
        await callback.message.answer(
            "Действие уже неактуально: статус заявки изменился."
        )
        await callback.answer()
        return
    except ValueError as exc:
        if str(exc) == "receipt_required":
            await callback.message.answer(
                "Сначала дождитесь чека от клиента — кнопка сработает после загрузки чека."
            )
        elif str(exc) == "unit_required":
            await callback.message.answer("Для этой заявки не выбрано место в календаре. Выберите место и подтвердите заявку заново.")
        else:
            logger.warning("owner payment rejected booking=%s reason=%s", booking_id, exc)
            await callback.message.answer(
                "Не удалось подтвердить оплату. Проверьте заявку и попробуйте ещё раз."
            )
        await callback.answer()
        return
    except Exception:
        logger.exception("owner payment confirmation failed booking=%s", booking_id)
        await callback.message.answer(
            "Не удалось обновить бронь в Google Sheets. Оплата не отмечена; попробуйте позже."
        )
        await callback.answer()
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        f"Бронь №{booking_id} подтверждена.\n" + format_owner_summary(booking, catalog)
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
