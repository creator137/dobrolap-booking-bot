from __future__ import annotations

from datetime import date

import logging

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import CallbackQuery, Message, TelegramObject

from dobrolap_bot.bot.keyboards import (
    OWNER_MENU_CLIENTS,
    OWNER_MENU_CONFIRMED,
    OWNER_MENU_HOME,
    OWNER_MENU_PENDING,
    OWNER_MENU_UNPAID,
    client_reply_kb,
    owner_actions_kb,
    owner_admin_bookings_kb,
    owner_admin_kb,
    owner_booking_kb,
    owner_menu_kb,
    owner_refund_kb,
    owner_unit_choice_kb,
)
from dobrolap_bot.bot.presentation import (
    admin_booking_button_title,
    format_admin_bookings_list,
    format_admin_clients,
    format_admin_overview,
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


async def _offer_owner_units(
    *,
    message,
    booking_service: BookingService,
    catalog: Catalog,
    booking,
    booking_id: str,
    intro: str | None = None,
) -> bool:
    """Show free suitable units for the owner to pick. Returns False if none."""
    try:
        occupied = booking_service.occupied_catalog_ids(
            booking.date_from,
            booking.date_to,
            exclude_booking_id=booking.id,
        )
    except SheetsUnavailableError:
        logger.exception("owner unit picker sheets unavailable booking=%s", booking_id)
        await message.answer(
            "Не удалось проверить календарь Google Sheets. Свободные помещения не показаны, "
            "чтобы случайно не предложить занятое место. Попробуйте позже."
        )
        return False

    pets = [PetProfile.model_validate(item) for item in booking.payload.get("pets") or []]
    result = booking_service.placement.suggest(
        pets,
        occupied_unit_ids=occupied,
        limit=len(catalog.accommodations),
        for_owner=True,
    )
    choices: list[tuple[str, str]] = []
    for candidate in result.candidates:
        unit = candidate.accommodation
        if booking.unit_id and unit.id == booking.unit_id:
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
                arrival_time=booking.payload.get("arrival_time"),
            )
            price = (
                f" — {quote.total_rub:,} ₽".replace(",", " ")
                if quote.has_accommodation_amount
                else " — расчёт оператора"
            )
        except Exception:
            logger.exception(
                "owner alternative quote failed booking=%s unit=%s", booking_id, unit.id
            )
            price = " — цена уточняется"
        choices.append((unit.id, f"{unit.name}{price}"))

    if not choices:
        flags = ", ".join(result.owner_flags) if result.owner_flags else "—"
        await message.answer(
            f"На даты {booking.date_from.strftime('%d.%m.%Y')}–"
            f"{booking.date_to.strftime('%d.%m.%Y')} автоподбор не нашёл вариантов "
            f"(флаги: {flags}).\n"
            "Календарь теста сейчас покрывает 21.08.2026–31.12.2026; "
            "проверьте занятость вручную в таблице или отклоните заявку."
        )
        return False

    review_note = ""
    if result.owner_flags:
        review_note = (
            "\n⚠️ Заявка с ручными флагами: "
            + ", ".join(result.owner_flags)
            + " — назначение помещения остаётся на вашей ответственности."
        )

    if intro is None:
        intro = (
            f"В заявке №{booking_id} ещё нет помещения — выберите свободный вариант:"
            if not booking.unit_id
            else f"Выберите другое подходящее свободное помещение для заявки №{booking_id}:"
        )
    await message.answer(
        intro + review_note,
        reply_markup=owner_unit_choice_kb(booking_id, choices),
    )
    return True


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
        logger.warning("owner approve invalid transition booking=%s", booking_id)
        current = await booking_service.get(booking_id)
        if current is not None and current.status in (
            BookingStatus.OWNER_APPROVED,
            BookingStatus.WAITING_PAYMENT,
        ):
            # Old card / admin list: the reserve is already approved and waits
            # for the deposit — offer the actions that make sense now.
            await callback.message.answer(
                f"Заявка №{booking_id} уже подтверждена, место зарезервировано и ждёт оплату залога.\n"
                "Когда залог получен — нажмите «Оплата получена».",
                reply_markup=owner_booking_kb(
                    booking_id, current.status, has_unit=bool(current.unit_id)
                ),
            )
        else:
            await callback.message.answer(
                "Действие уже неактуально: статус заявки изменился. Откройте свежую карточку."
            )
        await callback.answer()
        return
    except ValueError as exc:
        msg = str(exc)
        if msg == "unit_required":
            booking = await booking_service.get(booking_id)
            if booking is None:
                await callback.answer("Заявка не найдена", show_alert=True)
                return
            await callback.message.answer(
                "В заявке не выбрано помещение (клиент ушёл на ручной подбор). "
                "Сначала выберите вариант ниже, затем снова нажмите «Подтвердить»."
            )
            await _offer_owner_units(
                message=callback.message,
                booking_service=booking_service,
                catalog=catalog,
                booking=booking,
                booking_id=booking_id,
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
        "Когда залог получен (с чеком от клиента или без) — откройте заявку во вкладке "
        "«💳 Ждут оплату» и нажмите «Оплата получена».\n\n"
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
    await _offer_owner_units(
        message=callback.message,
        booking_service=booking_service,
        catalog=catalog,
        booking=booking,
        booking_id=booking_id,
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
        reply_markup=owner_actions_kb(booking_id, has_unit=bool(booking.unit_id)),
    )
    client_id = booking.customer_telegram_id
    unit = catalog.get_accommodation(unit_id)
    if client_id and callback.bot and unit:
        total = f"{quote.total_rub:,}".replace(",", " ") if quote.has_accommodation_amount else "рассчитает оператор"
        deposit = f"{quote.deposit_rub:,}".replace(",", " ")
        await callback.bot.send_message(
            client_id,
            "Владелец предложил другой вариант размещения:\n"
            f"{unit.name}\n"
            f"Предварительная стоимость: {total}{' ₽' if quote.has_accommodation_amount else ''}\n"
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
        if str(exc) == "unit_required":
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
    manual_note = (
        "Оплата отмечена вами вручную (чек от клиента не загружен).\n"
        if (booking.payload.get("payment") or {}).get("manual")
        else ""
    )
    await callback.message.answer(
        f"Бронь №{booking_id} подтверждена.\n"
        + manual_note
        + format_owner_summary(booking, catalog)
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


async def _send_admin_home(
    message: Message, booking_service: BookingService, *, with_menu: bool = False
) -> None:
    counts = await booking_service.repo.count_by_status()
    text = format_admin_overview(counts)
    if with_menu:
        await message.answer(
            "Панель владельца «Добролап».\nВыберите раздел кнопками ниже или /admin.",
            reply_markup=owner_menu_kb(),
        )
    await message.answer(text, reply_markup=owner_admin_kb())


async def _send_admin_bookings(
    message: Message,
    booking_service: BookingService,
    catalog: Catalog,
    *,
    statuses: list[BookingStatus],
    title: str,
    empty_text: str,
) -> None:
    bookings = await booking_service.repo.list_bookings(statuses=statuses, limit=20)
    text = format_admin_bookings_list(title, bookings, catalog, empty_text=empty_text)
    buttons = [(b.id, admin_booking_button_title(b)) for b in bookings]
    await message.answer(
        text,
        reply_markup=owner_admin_bookings_kb(buttons) if buttons else owner_admin_kb(),
    )


@router.message(CommandStart())
async def owner_start(message: Message, state: FSMContext, booking_service: BookingService) -> None:
    await state.clear()
    await _send_admin_home(message, booking_service, with_menu=True)


@router.message(Command("admin", "panel"))
async def owner_admin(message: Message, booking_service: BookingService) -> None:
    await _send_admin_home(message, booking_service, with_menu=True)


@router.message(F.text == OWNER_MENU_HOME)
async def owner_menu_home(message: Message, booking_service: BookingService) -> None:
    await _send_admin_home(message, booking_service)


@router.message(F.text == OWNER_MENU_PENDING)
async def owner_menu_pending(
    message: Message, booking_service: BookingService, catalog: Catalog
) -> None:
    await _send_admin_bookings(
        message,
        booking_service,
        catalog,
        statuses=[BookingStatus.WAITING_OWNER],
        title="⏳ Заявки, которые ждут вашего решения",
        empty_text="Сейчас нет заявок на рассмотрении.",
    )


@router.message(F.text == OWNER_MENU_UNPAID)
async def owner_menu_unpaid(
    message: Message, booking_service: BookingService, catalog: Catalog
) -> None:
    await _send_admin_bookings(
        message,
        booking_service,
        catalog,
        statuses=[BookingStatus.WAITING_PAYMENT],
        title="💳 Неоплаченные резервы (ждут залог / чек)",
        empty_text="Неоплаченных резервов сейчас нет.",
    )


@router.message(F.text == OWNER_MENU_CONFIRMED)
async def owner_menu_confirmed(
    message: Message, booking_service: BookingService, catalog: Catalog
) -> None:
    await _send_admin_bookings(
        message,
        booking_service,
        catalog,
        statuses=[BookingStatus.CONFIRMED],
        title="✅ Подтверждённые брони",
        empty_text="Подтверждённых броней пока нет.",
    )


@router.message(F.text == OWNER_MENU_CLIENTS)
async def owner_menu_clients(message: Message, booking_service: BookingService) -> None:
    clients = await booking_service.repo.list_customers(limit=40)
    await message.answer(format_admin_clients(clients), reply_markup=owner_admin_kb())


@router.callback_query(F.data == "adm:home")
async def admin_home(callback: CallbackQuery, booking_service: BookingService) -> None:
    counts = await booking_service.repo.count_by_status()
    try:
        await callback.message.edit_text(
            format_admin_overview(counts), reply_markup=owner_admin_kb()
        )
    except Exception:
        await callback.message.answer(
            format_admin_overview(counts), reply_markup=owner_admin_kb()
        )
    await callback.answer()


@router.callback_query(F.data == "adm:pending")
async def admin_pending(
    callback: CallbackQuery, booking_service: BookingService, catalog: Catalog
) -> None:
    await _send_admin_bookings(
        callback.message,
        booking_service,
        catalog,
        statuses=[BookingStatus.WAITING_OWNER],
        title="⏳ Заявки, которые ждут вашего решения",
        empty_text="Сейчас нет заявок на рассмотрении.",
    )
    await callback.answer()


@router.callback_query(F.data == "adm:unpaid")
async def admin_unpaid(
    callback: CallbackQuery, booking_service: BookingService, catalog: Catalog
) -> None:
    await _send_admin_bookings(
        callback.message,
        booking_service,
        catalog,
        statuses=[BookingStatus.WAITING_PAYMENT],
        title="💳 Неоплаченные резервы (ждут залог / чек)",
        empty_text="Неоплаченных резервов сейчас нет.",
    )
    await callback.answer()


@router.callback_query(F.data == "adm:confirmed")
async def admin_confirmed(
    callback: CallbackQuery, booking_service: BookingService, catalog: Catalog
) -> None:
    await _send_admin_bookings(
        callback.message,
        booking_service,
        catalog,
        statuses=[BookingStatus.CONFIRMED],
        title="✅ Подтверждённые брони",
        empty_text="Подтверждённых броней пока нет.",
    )
    await callback.answer()


@router.callback_query(F.data == "adm:clients")
async def admin_clients(callback: CallbackQuery, booking_service: BookingService) -> None:
    clients = await booking_service.repo.list_customers(limit=40)
    text = format_admin_clients(clients)
    try:
        await callback.message.edit_text(text, reply_markup=owner_admin_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=owner_admin_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("adm:open:"))
async def admin_open_booking(
    callback: CallbackQuery,
    booking_service: BookingService,
    catalog: Catalog,
) -> None:
    booking_id = (callback.data or "").removeprefix("adm:open:")
    booking = await booking_service.get(booking_id)
    if booking is None:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    await callback.message.answer(
        format_owner_summary(booking, catalog),
        reply_markup=owner_booking_kb(
            booking.id, booking.status, has_unit=bool(booking.unit_id)
        ),
    )
    await callback.answer()
