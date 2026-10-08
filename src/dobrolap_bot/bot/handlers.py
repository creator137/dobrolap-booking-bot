from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InputMediaPhoto,
    Message,
    ReplyKeyboardRemove,
)

from dobrolap_bot.bot.calendar_kb import (
    build_calendar,
    dates_prompt,
    parse_day,
    parse_nav,
)
from dobrolap_bot.bot.helpers import (
    FEED_MAP,
    KIND_MAP,
    is_young,
    normalize_phone,
    parse_age_months,
    parse_dates,
    parse_yes,
)
from dobrolap_bot.bot.keyboards import (
    add_pet_kb,
    behavior_kb,
    behavior_options,
    consent_kb,
    contact_kb,
    extraction_review_kb,
    feeding_kb,
    no_kb,
    owner_actions_kb,
    owner_cancel_kb,
    owner_paid_kb,
    passport_kb,
    pet_kind_kb,
    services_kb,
    submit_kb,
    unit_choice_kb,
    yes_no_kb,
)
from dobrolap_bot.bot.presentation import (
    format_draft_summary,
    placement_reason_label,
    status_label,
)
from dobrolap_bot.bot.states import BookingForm
from dobrolap_bot.config.loader import Catalog
from dobrolap_bot.domain.enums import BookingStatus, FeedingOption, PetKind
from dobrolap_bot.domain.models import BehaviorFlags, PetProfile
from dobrolap_bot.integrations.google_sheets import SheetsGateway, SheetsUnavailableError
from dobrolap_bot.services.booking import BookingService
from dobrolap_bot.services.placement import PlacementService
from dobrolap_bot.services.pricing import PricingService
from dobrolap_bot.integrations.llm import DisabledLlmAdapter, LlmAdapter, LlmUnavailableError
from dobrolap_bot.bot.presentation import BEHAVIOR_LABELS, format_age
from dobrolap_bot.services.summary import format_client_status, format_owner_summary

router = Router(name="client")
logger = logging.getLogger(__name__)


def _available_services(catalog: Catalog, pets: list[PetProfile]) -> list:
    preferred = [
        "nail_trim",
        "med_care",
        "bath_dry_dog",
        "grooming_cat",
        "zoo_taxi",
        "walk",
        "hygiene_complex_dog",
    ]
    pet_kinds = {pet.kind for pet in pets}
    by_id = {
        service.id: service
        for service in catalog.services
        if service.active
        and service.id != "natural_feeding"
        and (not service.applies_to or bool(set(service.applies_to) & pet_kinds))
    }
    ordered = [by_id[i] for i in preferred if i in by_id]
    for s in catalog.services:
        if s.id in by_id and s not in ordered:
            ordered.append(s)
    return ordered[:10]


def _resolve_photo(path_str: str, assets_dir: Path) -> Path | None:
    p = Path(path_str)
    if not p.is_absolute():
        # paths in yaml are like assets/rooms/...
        cand = Path.cwd() / p
        if cand.exists():
            return cand
        cand = assets_dir / "rooms" / p.name
        if cand.exists():
            return cand
        # strip leading assets/
        if path_str.startswith("assets/"):
            cand = Path.cwd() / path_str
            if cand.exists():
                return cand
    return p if p.exists() else None


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, llm: LlmAdapter) -> None:
    await state.clear()
    await state.set_state(BookingForm.consent)
    llm_notice = (
        "\nСвободный текст о возрасте, поведении и здоровье будет передан сервису OpenAI "
        "для распознавания; результат можно проверить и исправить."
        if not isinstance(llm, DisabledLlmAdapter) else ""
    )
    await message.answer(
        "Здравствуйте! Я бот зоогостиницы «Добролап».\n\n"
        "Помогу заполнить анкету, подобрать свободное место и посчитать "
        "предварительную стоимость. Бронь подтверждает владелец вручную.\n\n"
        "Для продолжения нужно согласие на обработку данных питомца и ваших контактов."
        + llm_notice,
        reply_markup=consent_kb(),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Диалог сброшен. /start — новая заявка.")


@router.message(Command("status"))
async def cmd_status(
    message: Message,
    booking_service: BookingService,
    catalog: Catalog,
) -> None:
    booking = await booking_service.repo.find_latest_by_telegram(
        message.from_user.id,
        statuses=[
            BookingStatus.WAITING_OWNER,
            BookingStatus.OWNER_APPROVED,
            BookingStatus.WAITING_PAYMENT,
            BookingStatus.CONFIRMED,
        ],
    )
    if not booking:
        await message.answer("Активных заявок не нашёл. /start — создать новую.")
        return
    await message.answer(format_client_status(booking, catalog))


@router.message(Command("cancel_booking"))
async def cmd_cancel_booking(
    message: Message,
    booking_service: BookingService,
    owner_chat_id: int | None,
) -> None:
    booking = await booking_service.repo.find_latest_by_telegram(
        message.from_user.id,
        statuses=[
            BookingStatus.WAITING_OWNER,
            BookingStatus.OWNER_APPROVED,
            BookingStatus.WAITING_PAYMENT,
            BookingStatus.CONFIRMED,
        ],
    )
    if not booking:
        await message.answer("Активной заявки нет.")
        return
    if booking.status == BookingStatus.WAITING_OWNER:
        await booking_service.cancel(booking.id, "client_request")
        await message.answer(f"Заявка №{booking.id} отменена.")
        if owner_chat_id and message.bot:
            await message.bot.send_message(
                owner_chat_id,
                f"Клиент отменил заявку {booking.id} до подтверждения.",
            )
        return

    await message.answer(
        f"Запрос на отмену заявки №{booking.id} отправлен владельцу.\n"
        "Политика возврата залога: более чем за 24 часа — полный возврат, "
        "за 24 часа и менее — 50%. Окончательное решение за владельцем."
    )
    if owner_chat_id and message.bot:
        await message.bot.send_message(
            owner_chat_id,
            f"⚠️ Клиент просит отменить заявку №{booking.id}.\n"
            f"Текущий статус: {status_label(booking.status)}.",
            reply_markup=owner_cancel_kb(booking.id),
        )


def _calendar_kb(*, pick_from: date | None = None, year: int | None = None, month: int | None = None):
    today = date.today()
    anchor = pick_from or today
    y = year or anchor.year
    m = month or anchor.month
    min_date = (pick_from + timedelta(days=1)) if pick_from else today
    return build_calendar(year=y, month=m, today=today, pick_from=pick_from, min_date=min_date)


async def _finish_dates(message: Message, state: FSMContext, date_from: date, date_to: date) -> None:
    await state.update_data(
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        cal_pick_from=None,
    )
    await state.set_state(BookingForm.pet_kind)
    await message.answer(
        f"Даты: {date_from.strftime('%d.%m.%Y')} → {date_to.strftime('%d.%m.%Y')}\n"
        "Кто ваш питомец?",
        reply_markup=pet_kind_kb(),
    )


@router.callback_query(BookingForm.consent, F.data == "consent:yes")
async def consent_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(
        consent_at=datetime.now(timezone.utc).isoformat(),
        pets=[],
        service_ids=[],
        cal_pick_from=None,
    )
    await state.set_state(BookingForm.contact)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Оставьте номер телефона для связи по заявке.\n"
        "Можно безопасно отправить свой номер кнопкой Telegram или ввести его вручную.",
        reply_markup=contact_kb(),
    )
    await callback.answer()


@router.callback_query(BookingForm.consent, F.data == "consent:no")
async def consent_no(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Без согласия продолжить нельзя. Если передумаете — /start.")
    await callback.answer()


async def _start_dates(message: Message, state: FSMContext) -> None:
    today = date.today()
    await state.set_state(BookingForm.dates)
    await message.answer(
        dates_prompt(),
        reply_markup=_calendar_kb(year=today.year, month=today.month),
        parse_mode="HTML",
    )


@router.message(BookingForm.contact, F.contact)
async def set_contact_from_telegram(message: Message, state: FSMContext) -> None:
    if not message.contact or message.contact.user_id not in {None, message.from_user.id}:
        await message.answer("Пожалуйста, отправьте свой номер или введите его вручную.")
        return
    phone = normalize_phone(message.contact.phone_number)
    if not phone:
        await message.answer("Не удалось распознать номер. Введите его вручную, например +7 900 123-45-67.")
        return
    await state.update_data(customer_contact=phone)
    await message.answer(f"Телефон сохранён: {phone}", reply_markup=ReplyKeyboardRemove())
    await _start_dates(message, state)


@router.message(BookingForm.contact)
async def set_contact_manually(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text.lower() == "ввести номер вручную":
        await message.answer(
            "Введите номер телефона, например +7 900 123-45-67.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    phone = normalize_phone(text)
    if not phone:
        await message.answer("Проверьте номер. Нужны 10–15 цифр, например +7 900 123-45-67.")
        return
    await state.update_data(customer_contact=phone)
    await message.answer(f"Телефон сохранён: {phone}", reply_markup=ReplyKeyboardRemove())
    await _start_dates(message, state)


@router.callback_query(BookingForm.dates, F.data == "cal:noop")
async def cal_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(BookingForm.dates, F.data == "cal:text")
async def cal_text_hint(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "Напишите даты одним сообщением:\n<code>10.10.2026 - 15.10.2026</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(BookingForm.dates, F.data == "cal:reset")
async def cal_reset(callback: CallbackQuery, state: FSMContext) -> None:
    today = date.today()
    await state.update_data(cal_pick_from=None)
    await callback.message.edit_text(
        dates_prompt(),
        reply_markup=_calendar_kb(year=today.year, month=today.month),
        parse_mode="HTML",
    )
    await callback.answer("Сброшено")


@router.callback_query(BookingForm.dates, F.data.startswith("cal:nav:"))
async def cal_nav(callback: CallbackQuery, state: FSMContext) -> None:
    parsed = parse_nav(callback.data or "")
    if not parsed:
        await callback.answer()
        return
    year, month = parsed
    data = await state.get_data()
    pick_raw = data.get("cal_pick_from")
    pick_from = date.fromisoformat(pick_raw) if pick_raw else None
    await callback.message.edit_reply_markup(
        reply_markup=_calendar_kb(pick_from=pick_from, year=year, month=month)
    )
    await callback.answer()


@router.callback_query(BookingForm.dates, F.data.startswith("cal:day:"))
async def cal_day(callback: CallbackQuery, state: FSMContext) -> None:
    chosen = parse_day(callback.data or "")
    if not chosen:
        await callback.answer("Некорректная дата", show_alert=True)
        return
    today = date.today()
    data = await state.get_data()
    pick_raw = data.get("cal_pick_from")

    if not pick_raw:
        if chosen < today:
            await callback.answer("Дата в прошлом", show_alert=True)
            return
        await state.update_data(cal_pick_from=chosen.isoformat())
        await callback.message.edit_text(
            dates_prompt(pick_from=chosen),
            reply_markup=_calendar_kb(
                pick_from=chosen, year=chosen.year, month=chosen.month
            ),
            parse_mode="HTML",
        )
        await callback.answer(f"Заезд {chosen.strftime('%d.%m.%Y')}")
        return

    date_from = date.fromisoformat(pick_raw)
    if chosen <= date_from:
        await callback.answer("Выезд должен быть позже заезда", show_alert=True)
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer()
    await _finish_dates(callback.message, state, date_from, chosen)


@router.message(BookingForm.dates)
async def set_dates(message: Message, state: FSMContext) -> None:
    parsed = parse_dates(message.text or "")
    if not parsed:
        today = date.today()
        data = await state.get_data()
        pick_raw = data.get("cal_pick_from")
        pick_from = date.fromisoformat(pick_raw) if pick_raw else None
        await message.answer(
            "Не разобрал даты. Выберите в календаре или формат: 10.10.2026 - 15.10.2026",
            reply_markup=_calendar_kb(
                pick_from=pick_from,
                year=(pick_from or today).year,
                month=(pick_from or today).month,
            ),
            parse_mode="HTML",
        )
        return
    date_from, date_to = parsed
    today = date.today()
    if date_from < today:
        await message.answer(
            f"Дата заезда не может быть в прошлом (сегодня {today.strftime('%d.%m.%Y')})."
        )
        return
    await _finish_dates(message, state, date_from, date_to)


@router.message(BookingForm.pet_kind)
async def set_pet_kind(message: Message, state: FSMContext) -> None:
    kind = KIND_MAP.get((message.text or "").strip().lower())
    if not kind:
        await message.answer("Выберите вариант с клавиатуры.", reply_markup=pet_kind_kb())
        return
    await state.update_data(draft_kind=kind.value)
    await state.set_state(BookingForm.pet_name)
    await message.answer("Кличка питомца?")


@router.message(BookingForm.pet_name)
async def set_pet_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 1:
        await message.answer("Введите кличку.")
        return
    await state.update_data(draft_name=name)
    data = await state.get_data()
    kind = PetKind(data["draft_kind"])
    if kind not in {PetKind.DOG, PetKind.CAT}:
        await _store_current_pet(message, state)
        return
    await state.set_state(BookingForm.pet_breed)
    await message.answer(
        "Какая порода? Если порода неизвестна или питомец — метис, нажмите «Нет».",
        reply_markup=no_kb(),
    )


async def _store_current_pet(
    message: Message,
    state: FSMContext,
    *,
    passport_ids: list[str] | None = None,
) -> None:
    data = await state.get_data()
    kind = PetKind(data["draft_kind"])
    age_months = data.get("draft_age_months")
    pet = PetProfile(
        kind=kind,
        name=data["draft_name"],
        breed=data.get("draft_breed"),
        age_months=age_months,
        weight_kg=data.get("draft_weight"),
        is_puppy_or_kitten=is_young(kind, age_months),
        vaccinated=data.get("draft_vaccinated"),
        parasite_treated=data.get("draft_parasite"),
        behavior=BehaviorFlags.model_validate(data.get("draft_behavior") or {}),
        behavior_notes=data.get("draft_behavior_raw"),
        health_notes=data.get("draft_health"),
        passport_file_ids=list(passport_ids or []),
    )
    pets = list(data.get("pets") or [])
    pets.append(pet.model_dump(mode="json"))
    await state.update_data(
        pets=pets,
        draft_kind=None,
        draft_name=None,
        draft_breed=None,
        draft_age_months=None,
        draft_weight=None,
        draft_vaccinated=None,
        draft_parasite=None,
        draft_behavior=None,
        draft_behavior_raw=None,
        draft_health=None,
        draft_passport_ids=[],
    )
    await state.set_state(BookingForm.add_another_pet)
    young = " (щенок/котёнок)" if pet.is_puppy_or_kitten else ""
    await message.answer(
        f"Питомец «{pet.name}»{young} добавлен. Всего питомцев: {len(pets)}.",
        reply_markup=add_pet_kb(),
    )


@router.message(BookingForm.pet_breed)
async def set_pet_breed(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    breed = None if text.lower() in {"нет", "-", "метьс", "метис", "не знаю"} else text
    await state.update_data(draft_breed=breed)
    await state.set_state(BookingForm.pet_age)
    await message.answer(
        "Сколько питомцу лет и месяцев? Например: «2 года 3 месяца» или «8 месяцев». "
        "Если меньше месяца, напишите число недель."
    )


@router.message(BookingForm.pet_age)
async def set_pet_age(message: Message, state: FSMContext, llm: LlmAdapter) -> None:
    raw = (message.text or "").strip()
    age = None
    try:
        signals = await llm.extract_pet_signals(raw, field="age")
        if not signals.needs_clarification:
            age = signals.age_months
    except LlmUnavailableError:
        age = parse_age_months(raw)
    if age is None:
        await message.answer(
            "Не удалось однозначно понять возраст. Напишите, например: «2 года 3 месяца» "
            "или точное число месяцев."
        )
        return
    await state.update_data(draft_age_candidate=age)
    await state.set_state(BookingForm.pet_age_review)
    await message.answer(
        f"Возраст: {format_age(age)}. Верно?",
        reply_markup=extraction_review_kb("age"),
    )


@router.callback_query(BookingForm.pet_age_review, F.data.startswith("review:age:"))
async def review_pet_age(callback: CallbackQuery, state: FSMContext) -> None:
    action = (callback.data or "").split(":")[-1]
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    if action != "yes":
        await state.set_state(BookingForm.pet_age)
        await callback.message.answer("Напишите точный возраст ещё раз, например «18 месяцев».")
        return
    data = await state.get_data()
    age = data.get("draft_age_candidate")
    if age is None:
        await state.set_state(BookingForm.pet_age)
        await callback.message.answer("Напишите возраст ещё раз.")
        return
    await state.update_data(draft_age_months=age, draft_age_candidate=None)
    data = await state.get_data()
    if data.get("draft_kind") == PetKind.DOG.value:
        await state.set_state(BookingForm.pet_weight)
        await callback.message.answer("Вес собаки в кг (число)?")
    else:
        await state.update_data(draft_weight=None)
        await state.set_state(BookingForm.pet_vaccinated)
        await callback.message.answer("Есть действующая вакцинация?", reply_markup=yes_no_kb())


@router.message(BookingForm.pet_weight)
async def set_pet_weight(message: Message, state: FSMContext) -> None:
    try:
        weight = float((message.text or "").replace(",", ".").strip())
        if weight <= 0 or weight > 120:
            raise ValueError
    except ValueError:
        await message.answer("Введите вес числом, например 8.5")
        return
    await state.update_data(draft_weight=weight)
    await state.set_state(BookingForm.pet_vaccinated)
    await message.answer("Есть действующая вакцинация?", reply_markup=yes_no_kb())


@router.message(BookingForm.pet_vaccinated)
async def set_vaccinated(message: Message, state: FSMContext) -> None:
    val = parse_yes(message.text or "")
    if val is None:
        await message.answer("Ответьте «Да» или «Нет».", reply_markup=yes_no_kb())
        return
    await state.update_data(draft_vaccinated=val)
    await state.set_state(BookingForm.pet_parasite)
    await message.answer("Обработка от паразитов сделана?", reply_markup=yes_no_kb())


@router.message(BookingForm.pet_parasite)
async def set_parasite(message: Message, state: FSMContext) -> None:
    val = parse_yes(message.text or "")
    if val is None:
        await message.answer("Ответьте «Да» или «Нет».", reply_markup=yes_no_kb())
        return
    await state.update_data(draft_parasite=val)
    await state.set_state(BookingForm.pet_behavior)
    data = await state.get_data()
    kind = PetKind(data["draft_kind"])
    await state.update_data(draft_behavior_selected=[])
    await message.answer(
        "Расскажите обычным текстом об особенностях поведения и ухода — например, «боится людей, но не агрессивен». "
        "Можно также выбрать несколько пунктов кнопками. Если особенностей нет, нажмите «Особенностей нет».",
        reply_markup=behavior_kb(kind),
    )


async def _finish_behavior(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    selected = set(data.get("draft_behavior_selected") or [])
    flags = BehaviorFlags(**{key: True for key in selected})
    await state.update_data(draft_behavior=flags.model_dump())
    await state.set_state(BookingForm.pet_health)
    await message.answer(
        "Есть дополнительные сведения о здоровье, лекарствах или уходе?\n"
        "Можно написать обычным текстом или нажать «Нет».",
        reply_markup=no_kb(),
    )


@router.callback_query(BookingForm.pet_behavior, F.data.startswith("beh:"))
async def toggle_behavior(callback: CallbackQuery, state: FSMContext) -> None:
    action = (callback.data or "").split(":", 1)[1]
    data = await state.get_data()
    kind = PetKind(data["draft_kind"])
    selected = set(data.get("draft_behavior_selected") or [])
    if action == "none":
        selected.clear()
        await state.update_data(draft_behavior_selected=[])
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer()
        await _finish_behavior(callback.message, state)
        return
    if action == "done":
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer()
        await _finish_behavior(callback.message, state)
        return
    allowed = set(behavior_options(kind))
    if action not in allowed:
        await callback.answer("Неизвестный вариант", show_alert=True)
        return
    if action in selected:
        selected.remove(action)
    else:
        selected.add(action)
    await state.update_data(draft_behavior_selected=sorted(selected))
    await callback.message.edit_reply_markup(reply_markup=behavior_kb(kind, selected))
    await callback.answer()


@router.message(BookingForm.pet_behavior)
async def set_behavior_text(message: Message, state: FSMContext, llm: LlmAdapter) -> None:
    raw = (message.text or "").strip()
    data = await state.get_data()
    kind = PetKind(data["draft_kind"])
    if not raw:
        await message.answer("Опишите поведение текстом или выберите пункты кнопками.", reply_markup=behavior_kb(kind))
        return
    await state.update_data(draft_behavior_raw=raw)
    if raw.lower() in {"нет", "нет особенностей", "-"}:
        await state.update_data(draft_behavior_selected=[])
        await _finish_behavior(message, state)
        return
    try:
        signals = await llm.extract_pet_signals(raw, field="behavior")
    except LlmUnavailableError:
        await message.answer(
            "Текст сохранил для владельца. Автоматический разбор сейчас недоступен. "
            "Отметьте известные особенности кнопками; остальные владелец увидит в заявке.",
            reply_markup=behavior_kb(kind),
        )
        return
    selected = (set(signals.behavior_flags) & set(behavior_options(kind))) if not signals.needs_clarification else set()
    await state.update_data(draft_behavior_selected=sorted(selected))
    labels = ", ".join(BEHAVIOR_LABELS[key] for key in sorted(selected)) or "явных особенностей не выделено"
    suffix = "\nЕсли смысл не передан полностью, исправьте кнопками: исходный текст сохранён для владельца."
    if signals.needs_clarification:
        suffix = "\nФормулировка неоднозначна: отметьте нужные пункты кнопками или уточните текст. Исходный текст сохранён."
    await state.set_state(BookingForm.pet_behavior_review)
    await message.answer(
        f"Я понял: {labels}.{suffix}", reply_markup=extraction_review_kb("behavior")
    )


@router.callback_query(BookingForm.pet_behavior_review, F.data.startswith("review:behavior:"))
async def review_behavior(callback: CallbackQuery, state: FSMContext) -> None:
    action = (callback.data or "").split(":")[-1]
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    if action == "yes":
        await _finish_behavior(callback.message, state)
        return
    data = await state.get_data()
    await state.set_state(BookingForm.pet_behavior)
    await callback.message.answer(
        "Исправьте отмеченные пункты кнопками или напишите описание заново.",
        reply_markup=behavior_kb(PetKind(data["draft_kind"]), set(data.get("draft_behavior_selected") or [])),
    )


@router.message(BookingForm.pet_health)
async def set_health(message: Message, state: FSMContext, llm: LlmAdapter) -> None:
    text = (message.text or "").strip()
    health = None if text.lower() in {"нет", "-"} else text
    if not text:
        await message.answer("Опишите особенности здоровья текстом или нажмите «Нет».", reply_markup=no_kb())
        return
    if health is None:
        await _finish_health(message, state, health=None, flags=[])
        return
    try:
        signals = await llm.extract_pet_signals(health, field="health")
        flags = [] if signals.needs_clarification else signals.health_flags
    except LlmUnavailableError:
        flags = []
        await message.answer(
            "Автоматический разбор недоступен. Сохраню ваше описание дословно "
            "и передам владельцу на ручную проверку."
        )
    await state.update_data(draft_health_candidate=health, draft_health_flags_candidate=flags)
    await state.set_state(BookingForm.pet_health_review)
    labels = ", ".join(BEHAVIOR_LABELS[key] for key in flags) or "автоматических отметок нет"
    await message.answer(
        f"Описание: {health}\nОтметки: {labels}. Всё верно?",
        reply_markup=extraction_review_kb("health"),
    )


async def _finish_health(message: Message, state: FSMContext, *, health: str | None, flags: list[str]) -> None:
    behavior_data = (await state.get_data()).get("draft_behavior") or {}
    current = BehaviorFlags.model_validate(behavior_data)
    for key in flags:
        if key in BehaviorFlags.model_fields:
            setattr(current, key, True)
    await state.update_data(draft_health=health, draft_behavior=current.model_dump())
    await state.set_state(BookingForm.pet_passport)
    await message.answer(
        "Пришлите фото страниц ветпаспорта (данные, прививки, обработки).\n"
        "Можно несколько фото. Когда закончите — «Готово».\n"
        "Если фото нет — «Без фото» (заявка уйдёт владельцу как неполная).",
        reply_markup=passport_kb(),
    )


@router.callback_query(BookingForm.pet_health_review, F.data.startswith("review:health:"))
async def review_health(callback: CallbackQuery, state: FSMContext) -> None:
    action = (callback.data or "").split(":")[-1]
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    if action != "yes":
        await state.set_state(BookingForm.pet_health)
        await callback.message.answer("Напишите уточнённое описание здоровья или нажмите «Нет».", reply_markup=no_kb())
        return
    data = await state.get_data()
    await _finish_health(
        callback.message, state,
        health=data.get("draft_health_candidate"),
        flags=list(data.get("draft_health_flags_candidate") or []),
    )


@router.message(BookingForm.pet_passport, F.photo)
async def passport_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    files = list(data.get("draft_passport_ids") or [])
    files.append(message.photo[-1].file_id)
    await state.update_data(draft_passport_ids=files)
    await message.answer(
        f"Фото сохранено ({len(files)}). Ещё фото или «Готово».",
        reply_markup=passport_kb(),
    )


@router.message(BookingForm.pet_passport)
async def passport_done(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().lower()
    if text not in {"готово", "далее", "ok", "ок", "без фото", "пропустить"}:
        await message.answer(
            "Пришлите фото паспорта или нажмите «Готово».\n"
            "Если фото нет — «Без фото» (заявка уйдёт владельцу как неполная).",
            reply_markup=passport_kb(),
        )
        return

    data = await state.get_data()
    passport_ids = list(data.get("draft_passport_ids") or [])
    incomplete_flags = list(data.get("placement_flags") or [])
    if not passport_ids:
        incomplete_flags.append(f"incomplete_passport:{data.get('draft_name') or '?'}")
        await message.answer(
            "Фото паспорта нет — помечу заявку как неполную для владельца."
        )

    await state.update_data(
        placement_flags=sorted(set(incomplete_flags)),
    )
    await _store_current_pet(message, state, passport_ids=passport_ids)


@router.message(BookingForm.add_another_pet)
async def add_another(
    message: Message,
    state: FSMContext,
    catalog: Catalog,
    sheets: SheetsGateway,
    booking_service: BookingService,
    assets_dir: Path,
) -> None:
    text = (message.text or "").strip().lower()
    if "добавить" in text:
        await state.set_state(BookingForm.pet_kind)
        await message.answer("Кто следующий питомец?", reply_markup=pet_kind_kb())
        return
    if "подбор" in text or "далее" in text:
        await _run_placement(message, state, catalog, sheets, booking_service, assets_dir)
        return
    await message.answer("Выберите кнопку.", reply_markup=add_pet_kb())


async def _run_placement(
    message: Message,
    state: FSMContext,
    catalog: Catalog,
    sheets: SheetsGateway,
    booking_service: BookingService,
    assets_dir: Path,
) -> None:
    data = await state.get_data()
    pets = [PetProfile.model_validate(p) for p in data.get("pets") or []]
    date_from = date.fromisoformat(data["date_from"])
    date_to = date.fromisoformat(data["date_to"])
    nights = (date_to - date_from).days

    try:
        occupied = booking_service.occupied_catalog_ids(date_from, date_to)
    except SheetsUnavailableError:
        logger.exception(
            "availability check failed date_from=%s date_to=%s", date_from, date_to
        )
        flags = sorted(set(data.get("placement_flags") or []) | {"sheets_unavailable"})
        await state.update_data(unit_id=None, manual_matching=True, placement_flags=flags)
        await state.set_state(BookingForm.feeding)
        await message.answer(
            "Календарь занятости сейчас недоступен — не могу показать свободные места.\n"
            "Заявку отправлю владельцу на ручной подбор.\n\nКак будем кормить?",
            reply_markup=feeding_kb(),
        )
        if message.bot:
            # owner notified later on submit; flag is enough
            pass
        return

    result = PlacementService(catalog).suggest(pets, occupied_unit_ids=occupied)
    flags = sorted(set(data.get("placement_flags") or []) | set(result.owner_flags))
    await state.update_data(
        placement_flags=flags,
        requires_manual=result.requires_manual_matching,
    )

    if not result.candidates:
        await state.update_data(unit_id=None, manual_matching=True)
        await state.set_state(BookingForm.feeding)
        await message.answer(
            "Автоматически подходящих свободных мест не нашёл. "
            "Заявку всё равно отправлю владельцу на ручной подбор.\n\n"
            "Как будем кормить?",
            reply_markup=feeding_kb(),
        )
        return

    pricing = PricingService(catalog)
    choices: list[tuple[str, str]] = []
    offered_labels: dict[str, str] = {}
    await message.answer("Подобрал свободные варианты:")

    for i, cand in enumerate(result.candidates, 1):
        acc = cand.accommodation
        try:
            label = booking_service.resolve_free_sheet_label(acc.id, date_from, date_to)
        except ValueError:
            continue  # Occupancy changed since the first calendar read.
        except SheetsUnavailableError:
            await state.update_data(unit_id=None, manual_matching=True)
            await state.set_state(BookingForm.feeding)
            await message.answer(
                "Календарь стал недоступен. Передам заявку владельцу на ручной подбор. "
                "Как будем кормить?", reply_markup=feeding_kb(),
            )
            return
        offered_labels[acc.id] = label
        quote = pricing.quote(
            pets=pets,
            unit=acc,
            date_from=date_from,
            date_to=date_to,
            feeding=FeedingOption.OWNER_FOOD,
        )
        day_hint = quote.total_rub // nights if nights else quote.total_rub
        caption = (
            f"{i}. {acc.name}\n"
            f"≈ {day_hint} ₽/сут., предварительно за {nights} сут.: {quote.total_rub} ₽\n"
            f"Залог: {quote.deposit_rub} ₽"
        )
        if cand.reasons:
            caption += "\nПочему подходит: " + "; ".join(
                placement_reason_label(reason) for reason in cand.reasons[:2]
            )
        if quote.provisional or cand.requires_owner_review:
            caption += "\n⚠️ требует подтверждения владельцем"
        if acc.photo_paths_by_species and len(acc.calendar_labels()) > 1:
            caption += "\nФото показывает тип размещения; конкретный бокс подтвердит владелец."

        choices.append((acc.id, f"{i}. {acc.name} — {quote.total_rub} ₽"))

        photos = []
        for path_str in acc.photos_for(pets, sheet_label=label)[:5]:
            resolved = _resolve_photo(path_str, assets_dir)
            if resolved:
                photos.append(resolved)
        if photos:
            media = []
            for idx, photo_path in enumerate(photos):
                media.append(
                    InputMediaPhoto(
                        media=FSInputFile(photo_path),
                        caption=caption if idx == 0 else None,
                    )
                )
            try:
                await message.answer_media_group(media)
            except Exception:
                await message.answer(caption)
        else:
            await message.answer(caption)

    if not choices:
        await state.update_data(unit_id=None, manual_matching=True)
        await state.set_state(BookingForm.feeding)
        await message.answer(
            "Свободные варианты изменились. Передам заявку владельцу на ручной подбор. "
            "Как будем кормить?", reply_markup=feeding_kb(),
        )
        return
    if result.requires_manual_matching:
        await message.answer("⚠️ Заявка всё равно уйдёт на ручное подтверждение.")

    await state.set_state(BookingForm.choose_unit)
    await state.update_data(offered_sheet_labels=offered_labels)
    await message.answer("Выберите вариант:", reply_markup=unit_choice_kb(choices))


@router.callback_query(BookingForm.choose_unit, F.data.startswith("unit:"))
async def choose_unit(callback: CallbackQuery, state: FSMContext) -> None:
    unit_id = callback.data.split(":", 1)[1]
    offered = (await state.get_data()).get("offered_sheet_labels") or {}
    if unit_id == "manual":
        await state.update_data(unit_id=None, requested_sheet_label=None, manual_matching=True)
    else:
        if unit_id not in offered:
            await callback.answer("Вариант больше не доступен. Повторите подбор.", show_alert=True)
            return
        await state.update_data(
            unit_id=unit_id,
            requested_sheet_label=offered[unit_id],
            manual_matching=False,
        )
    await state.set_state(BookingForm.feeding)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Как будем кормить?", reply_markup=feeding_kb())
    await callback.answer()


@router.message(BookingForm.feeding)
async def set_feeding(message: Message, state: FSMContext, catalog: Catalog) -> None:
    feeding = FEED_MAP.get((message.text or "").strip().lower())
    if not feeding:
        await message.answer("Выберите вариант с клавиатуры.", reply_markup=feeding_kb())
        return
    await state.update_data(feeding=feeding.value, service_ids=[])
    await state.set_state(BookingForm.services)
    data = await state.get_data()
    pets = [PetProfile.model_validate(p) for p in data.get("pets") or []]
    available = _available_services(catalog, pets)
    items = [(s.id, s.name, False) for s in available]
    if not items:
        await state.set_state(BookingForm.promo)
        await message.answer(
            "Для этих питомцев дополнительных услуг в каталоге пока нет.\n"
            "Есть промокод? Пришлите его или нажмите «Нет».",
            reply_markup=no_kb(),
        )
        return
    await message.answer(
        "Дополнительные услуги (можно несколько). Нажмите «Готово», когда закончите.",
        reply_markup=services_kb(items),
    )


@router.callback_query(BookingForm.services, F.data.startswith("svc:"))
async def toggle_service(callback: CallbackQuery, state: FSMContext, catalog: Catalog) -> None:
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected = set(data.get("service_ids") or [])
    pets = [PetProfile.model_validate(p) for p in data.get("pets") or []]
    available = _available_services(catalog, pets)
    allowed_ids = {service.id for service in available}

    if action in {"none", "done"}:
        if action == "none":
            await state.update_data(service_ids=[])
        await state.set_state(BookingForm.promo)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.answer(
            "Есть промокод? Пришлите его или нажмите «Нет».",
            reply_markup=no_kb(),
        )
        await callback.answer()
        return

    if action not in allowed_ids:
        await callback.answer("Эта услуга не подходит выбранным питомцам", show_alert=True)
        return
    if action in selected:
        selected.remove(action)
    else:
        selected.add(action)
    await state.update_data(service_ids=sorted(selected))
    items = [(s.id, s.name, s.id in selected) for s in available]
    await callback.message.edit_reply_markup(reply_markup=services_kb(items))
    await callback.answer()


@router.message(BookingForm.promo)
async def set_promo(
    message: Message, state: FSMContext, catalog: Catalog,
    booking_service: BookingService,
) -> None:
    text = (message.text or "").strip()
    promo = None if text.lower() in {"нет", "-", "нет промокода"} else text.strip().upper()
    if promo:
        data = await state.get_data()
        pricing = PricingService(catalog)
        rule = pricing.find_active_promo(
            promo,
            on_date=pricing.promo_today(),
        )
        if rule is None:
            await message.answer(
                "Такой промокод не найден, ещё не действует или уже закончился.\n"
                "Проверьте написание либо нажмите «Нет».",
                reply_markup=no_kb(),
            )
            return
        if rule.condition.get("first_placement") and await booking_service.repo.has_prior_placement_by_telegram(message.from_user.id, data.get("customer_contact")):
            await message.answer(
                "Этот промокод действует только на первое размещение. "
                "По вашему аккаунту уже есть действующая или подтверждённая заявка. "
                "Если это ошибка, сообщите владельцу; продолжить можно без промокода."
            )
            return
        await message.answer("Промокод принят — скидка появится в расчёте.")
    await state.update_data(promo_code=promo, promo_verified=bool(promo))
    # Build a fake callback-like summary via helper
    await _show_summary_message(message, state, catalog)


async def _show_summary_message(message: Message, state: FSMContext, catalog: Catalog) -> None:
    data = await state.get_data()
    pets = [PetProfile.model_validate(p) for p in data.get("pets") or []]
    feeding_opt = FeedingOption(data["feeding"]) if data.get("feeding") else None
    service_ids = list(data.get("service_ids") or [])
    unit_id = data.get("unit_id")
    promo = data.get("promo_code")

    quote = None
    if unit_id:
        unit = catalog.get_accommodation(unit_id)
        if unit:
            quote = PricingService(catalog).quote(
                pets=pets,
                unit=unit,
                date_from=date.fromisoformat(data["date_from"]),
                date_to=date.fromisoformat(data["date_to"]),
                feeding=feeding_opt,
                service_ids=service_ids,
                promo_code=promo,
                promo_eligible=bool(data.get("promo_verified")),
            )
            await state.update_data(
                price_total=quote.total_rub,
                deposit_amount=quote.deposit_rub,
                quote_explanation=quote.explanation,
                quote_provisional=quote.provisional,
            )
    else:
        deposit = PricingService(catalog).deposit_amount(len(pets) or 1)
        await state.update_data(price_total=None, deposit_amount=deposit)

    await state.set_state(BookingForm.confirm_submit)
    refreshed = await state.get_data()
    await message.answer(
        format_draft_summary(data=refreshed, pets=pets, catalog=catalog, quote=quote),
        reply_markup=submit_kb(),
    )


@router.callback_query(BookingForm.confirm_submit, F.data == "submit:yes")
async def submit_yes(
    callback: CallbackQuery,
    state: FSMContext,
    booking_service: BookingService,
    catalog: Catalog,
    owner_chat_id: int | None,
) -> None:
    data = await state.get_data()
    pets = [PetProfile.model_validate(p) for p in data.get("pets") or []]
    feeding = FeedingOption(data["feeding"]) if data.get("feeding") else None
    consent_raw = data.get("consent_at")
    consent_at = datetime.fromisoformat(consent_raw) if consent_raw else None

    try:
        booking, _quote = await booking_service.submit_booking(
            telegram_user_id=callback.from_user.id,
            customer_name=callback.from_user.full_name,
            username=callback.from_user.username,
            consent_at=consent_at,
            date_from=date.fromisoformat(data["date_from"]),
            date_to=date.fromisoformat(data["date_to"]),
            pets=pets,
            unit_id=data.get("unit_id"),
            feeding=feeding,
            service_ids=list(data.get("service_ids") or []),
            placement_flags=list(data.get("placement_flags") or []),
            manual_matching=bool(data.get("manual_matching") or data.get("requires_manual")),
            promo_code=data.get("promo_code"),
            customer_contact=data.get("customer_contact"),
            requested_sheet_label=data.get("requested_sheet_label"),
        )
    except SheetsUnavailableError:
        logger.exception("booking submit failed: Sheets unavailable")
        await callback.message.answer(
            "Календарь недоступен — заявку сейчас сохранить с проверкой занятости нельзя. "
            "Попробуйте позже или напишите владельцу напрямую."
        )
        await callback.answer()
        return
    except ValueError as exc:
        if str(exc) in {"promo_not_first_placement", "promo_invalid_or_expired"}:
            await state.update_data(promo_code=None, promo_verified=False)
            await state.set_state(BookingForm.promo)
            await callback.message.answer(
                "Промокод больше не применим: срок истёк или право на первое размещение уже использовано. "
                "Введите другой промокод или нажмите «Нет».", reply_markup=no_kb(),
            )
            await callback.answer()
            return
        if str(exc) == "selected_unit_occupied":
            await callback.message.answer(
                "Выбранное место только что заняли. Начните подбор заново: /start"
            )
            await callback.answer()
            return
        logger.exception("booking submit failed with invalid data: %s", exc)
        await callback.message.answer(
            "Не удалось отправить заявку из-за ошибки в данных. Проверьте анкету или начните заново: /start"
        )
        await callback.answer()
        return

    summary = format_owner_summary(booking, catalog)
    if owner_chat_id and callback.bot:
        await callback.bot.send_message(
            owner_chat_id,
            summary,
            reply_markup=owner_actions_kb(booking.id),
        )
        for pet in pets:
            for file_id in pet.passport_file_ids:
                try:
                    await callback.bot.send_photo(
                        owner_chat_id,
                        file_id,
                        caption=f"Паспорт: {pet.name} / заявка {booking.id}",
                    )
                except Exception:
                    pass
        await callback.message.answer(
            f"Заявка №{booking.id} отправлена владельцу.\n"
            "Ожидайте решения. Реквизиты придут только после подтверждения.\n"
            "Статус: /status"
        )
    else:
        await callback.message.answer(
            "Заявка сохранена, но уведомление владельцу сейчас недоступно. "
            "Пожалуйста, свяжитесь с зоогостиницей напрямую."
        )

    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer()


@router.callback_query(BookingForm.confirm_submit, F.data == "submit:no")
async def submit_no(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Заявку отменил. /start — начать снова.")
    await callback.answer()


async def _accept_receipt(
    message: Message,
    booking_service: BookingService,
    owner_chat_id: int | None,
    file_id: str,
    *,
    as_document: bool = False,
    booking_id: str | None = None,
) -> bool:
    """Attach receipt for WAITING_PAYMENT booking (FSM or SQLite recovery)."""
    bookings = await booking_service.repo.list_by_telegram(
        message.from_user.id,
        statuses=[BookingStatus.WAITING_PAYMENT],
    )
    if not bookings:
        return False
    if booking_id:
        booking = next((item for item in bookings if item.id == booking_id), None)
        if booking is None:
            await message.answer("Эта заявка уже не ожидает оплату. Проверьте /status.")
            return True
    elif len(bookings) == 1:
        booking = bookings[0]
    else:
        ids = ", ".join(item.id for item in bookings)
        await message.answer(
            f"У вас несколько заявок на оплату: {ids}. "
            "Выберите нужную командой /receipt НОМЕР_ЗАЯВКИ и пришлите чек ещё раз."
        )
        return True
    try:
        booking = await booking_service.attach_receipt(booking.id, file_id)
    except Exception:
        logger.exception("receipt attach failed booking=%s", booking.id)
        await message.answer(
            "Не удалось сохранить чек. Попробуйте отправить его ещё раз немного позже."
        )
        return True

    await message.answer(
        "Чек получил и передал владельцу на проверку. "
        "После подтверждения оплаты бронь будет зафиксирована."
    )
    if owner_chat_id and message.bot:
        if as_document:
            await message.bot.send_document(
                owner_chat_id,
                file_id,
                caption=f"Чек по заявке {booking.id}",
                reply_markup=owner_paid_kb(booking.id),
            )
        else:
            await message.bot.send_photo(
                owner_chat_id,
                file_id,
                caption=f"Чек по заявке {booking.id}",
                reply_markup=owner_paid_kb(booking.id),
            )
    return True


@router.message(Command("receipt"))
async def cmd_receipt(message: Message, state: FSMContext, booking_service: BookingService) -> None:
    parts = (message.text or "").split(maxsplit=1)
    booking_id = parts[1].strip() if len(parts) == 2 else ""
    bookings = await booking_service.repo.list_by_telegram(
        message.from_user.id, statuses=[BookingStatus.WAITING_PAYMENT]
    )
    if not bookings:
        await message.answer("Заявок, ожидающих оплату, нет.")
        return
    if not booking_id and len(bookings) == 1:
        booking_id = bookings[0].id
    if booking_id not in {item.id for item in bookings}:
        ids = ", ".join(item.id for item in bookings)
        await message.answer(f"Укажите номер своей заявки: /receipt НОМЕР_ЗАЯВКИ. Доступные: {ids}")
        return
    await state.set_state(BookingForm.waiting_receipt)
    await state.update_data(booking_id=booking_id)
    await message.answer(f"Пришлите чек по заявке {booking_id} фото или документом.")


@router.message(BookingForm.waiting_receipt, F.photo)
async def receipt_photo_fsm(
    message: Message,
    state: FSMContext,
    booking_service: BookingService,
    owner_chat_id: int | None,
) -> None:
    data = await state.get_data()
    await _accept_receipt(
        message, booking_service, owner_chat_id, message.photo[-1].file_id,
        booking_id=data.get("booking_id"),
    )


@router.message(BookingForm.waiting_receipt, F.document)
async def receipt_document_fsm(
    message: Message,
    state: FSMContext,
    booking_service: BookingService,
    owner_chat_id: int | None,
) -> None:
    if not message.document:
        return
    data = await state.get_data()
    await _accept_receipt(
        message,
        booking_service,
        owner_chat_id,
        message.document.file_id,
        as_document=True,
        booking_id=data.get("booking_id"),
    )


# Recovery after bot restart: accept receipt by SQLite status, not only FSM.
@router.message(F.photo)
async def receipt_photo_recovery(
    message: Message,
    state: FSMContext,
    booking_service: BookingService,
    owner_chat_id: int | None,
) -> None:
    current = await state.get_state()
    if current is not None:
        return
    handled = await _accept_receipt(
        message, booking_service, owner_chat_id, message.photo[-1].file_id
    )
    if not handled:
        return


@router.message(F.document)
async def receipt_document_recovery(
    message: Message,
    state: FSMContext,
    booking_service: BookingService,
    owner_chat_id: int | None,
) -> None:
    current = await state.get_state()
    if current is not None or not message.document:
        return
    await _accept_receipt(
        message,
        booking_service,
        owner_chat_id,
        message.document.file_id,
        as_document=True,
    )


@router.callback_query(F.data.startswith("cli:reply:"))
async def client_reply_start(callback: CallbackQuery, state: FSMContext) -> None:
    booking_id = callback.data.split(":")[-1]
    await state.set_state(BookingForm.reply_to_owner)
    await state.update_data(booking_id=booking_id)
    await callback.message.answer("Напишите ответ владельцу одним сообщением.")
    await callback.answer()


@router.message(BookingForm.reply_to_owner)
async def client_reply_send(
    message: Message,
    state: FSMContext,
    booking_service: BookingService,
    owner_chat_id: int | None,
) -> None:
    data = await state.get_data()
    booking_id = data.get("booking_id")
    if not booking_id:
        await state.clear()
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пустой ответ. Напишите текст.")
        return
    await booking_service.add_client_reply(booking_id, text)
    if owner_chat_id and message.bot:
        await message.bot.send_message(
            owner_chat_id,
            f"💬 Ответ клиента по заявке {booking_id}:\n{text}",
            reply_markup=owner_actions_kb(booking_id),
        )
    await message.answer("Ответ отправил владельцу.")
    await state.clear()
