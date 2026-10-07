from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InputMediaPhoto,
    Message,
)

from dobrolap_bot.bot.helpers import FEED_MAP, KIND_MAP, is_young, parse_dates, parse_yes
from dobrolap_bot.bot.keyboards import (
    add_pet_kb,
    consent_kb,
    feeding_kb,
    owner_actions_kb,
    owner_paid_kb,
    pet_kind_kb,
    services_kb,
    submit_kb,
    unit_choice_kb,
    yes_no_kb,
)
from dobrolap_bot.bot.states import BookingForm
from dobrolap_bot.config.loader import Catalog
from dobrolap_bot.domain.enums import BookingStatus, FeedingOption, PetKind
from dobrolap_bot.domain.models import BehaviorFlags, PetProfile
from dobrolap_bot.integrations.google_sheets import SheetsGateway, SheetsUnavailableError
from dobrolap_bot.services.booking import BookingService
from dobrolap_bot.services.placement import PlacementService
from dobrolap_bot.services.pricing import PricingService
from dobrolap_bot.services.summary import format_client_status, format_owner_summary

router = Router(name="client")


def _popular_services(catalog: Catalog) -> list:
    preferred = [
        "nail_trim",
        "med_care",
        "bath_dry_dog",
        "grooming_cat",
        "zoo_taxi",
        "walk",
        "hygiene_complex_dog",
    ]
    by_id = {s.id: s for s in catalog.services if s.active}
    ordered = [by_id[i] for i in preferred if i in by_id]
    for s in catalog.services:
        if s.active and s not in ordered:
            ordered.append(s)
    return ordered[:10]


def _resolve_photo(path_str: str, assets_dir: Path) -> Path | None:
    p = Path(path_str)
    if not p.is_absolute():
        # paths in yaml are like assets/rooms/...
        cand = Path.cwd() / p
        if cand.exists():
            return cand
        cand = assets_dir / p.name
        if cand.exists():
            return cand
        # strip leading assets/
        if path_str.startswith("assets/"):
            cand = Path.cwd() / path_str
            if cand.exists():
                return cand
    return p if p.exists() else None


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(BookingForm.consent)
    await message.answer(
        "Здравствуйте! Я бот зоогостиницы «Добролап».\n\n"
        "Помогу заполнить анкету, подобрать свободное место и посчитать "
        "предварительную стоимость. Бронь подтверждает владелец вручную.\n\n"
        "Для продолжения нужно согласие на обработку данных питомца и ваших контактов.",
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
        await message.answer(f"Заявку {booking.id} отменил.")
        if owner_chat_id and message.bot:
            await message.bot.send_message(
                owner_chat_id,
                f"Клиент отменил заявку {booking.id} до подтверждения.",
            )
        return

    await message.answer(
        f"Запрос на отмену заявки {booking.id} отправил владельцу.\n"
        "Политика возврата залога: более чем за 24 часа — полный возврат, "
        "за 24 часа и менее — 50%. Окончательное решение за владельцем."
    )
    if owner_chat_id and message.bot:
        await message.bot.send_message(
            owner_chat_id,
            f"⚠️ Клиент просит отменить заявку {booking.id} (статус {booking.status.value}).",
            reply_markup=owner_actions_kb(booking.id),
        )


@router.callback_query(BookingForm.consent, F.data == "consent:yes")
async def consent_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(
        consent_at=datetime.now(timezone.utc).isoformat(),
        pets=[],
        service_ids=[],
    )
    await state.set_state(BookingForm.dates)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Укажите даты заезда и выезда в формате ДД.ММ.ГГГГ - ДД.ММ.ГГГГ\n"
        "Пример: 10.10.2026 - 15.10.2026"
    )
    await callback.answer()


@router.callback_query(BookingForm.consent, F.data == "consent:no")
async def consent_no(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("Без согласия продолжить нельзя. Если передумаете — /start.")
    await callback.answer()


@router.message(BookingForm.dates)
async def set_dates(message: Message, state: FSMContext) -> None:
    parsed = parse_dates(message.text or "")
    if not parsed:
        await message.answer("Не разобрал даты. Формат: 10.10.2026 - 15.10.2026")
        return
    date_from, date_to = parsed
    await state.update_data(date_from=date_from.isoformat(), date_to=date_to.isoformat())
    await state.set_state(BookingForm.pet_kind)
    await message.answer("Кто ваш питомец?", reply_markup=pet_kind_kb())


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
    await state.set_state(BookingForm.pet_breed)
    await message.answer("Порода? Если неизвестна — напишите «нет» или «метьс».")


@router.message(BookingForm.pet_breed)
async def set_pet_breed(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    breed = None if text.lower() in {"нет", "-", "метьс", "метис", "не знаю"} else text
    await state.update_data(draft_breed=breed)
    await state.set_state(BookingForm.pet_age)
    await message.answer("Возраст в месяцах (число)? Например 18. Для щенка/котёнка важно.")


@router.message(BookingForm.pet_age)
async def set_pet_age(message: Message, state: FSMContext) -> None:
    try:
        age = int((message.text or "").strip().replace(",", ".").split(".")[0])
        if age < 0 or age > 400:
            raise ValueError
    except ValueError:
        await message.answer("Введите возраст целым числом месяцев, например 8")
        return
    await state.update_data(draft_age_months=age)
    data = await state.get_data()
    if data.get("draft_kind") == PetKind.DOG.value:
        await state.set_state(BookingForm.pet_weight)
        await message.answer("Вес собаки в кг (число)?")
    else:
        await state.update_data(draft_weight=None)
        await state.set_state(BookingForm.pet_vaccinated)
        await message.answer("Есть действующая вакцинация?", reply_markup=yes_no_kb())


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
    await message.answer(
        "Кратко опишите поведение (агрессия, стресс, лай, метки) или напишите «нет»."
    )


@router.message(BookingForm.pet_behavior)
async def set_behavior(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().lower()
    flags = BehaviorFlags()
    raw = ""
    if text not in {"нет", "нет особенностей", "-"}:
        raw = message.text or ""
        if "агресс" in text:
            flags.aggression = True
            flags.zoo_aggression = True
        if "стресс" in text:
            flags.high_stress = True
        if "лай" in text or "лает" in text:
            flags.loud_barking = True
        if "метит" in text or "метк" in text:
            flags.marks_territory = True
        if "грыз" in text:
            flags.chews_furniture = True
        if "стар" in text or "пожил" in text:
            flags.elderly = True
        if "подвиж" in text or "хромот" in text or "не ходит" in text:
            flags.mobility_limited = True
    await state.update_data(draft_behavior=flags.model_dump(), draft_behavior_raw=raw)
    await state.set_state(BookingForm.pet_health)
    await message.answer("Особенности здоровья / лечение / инвалидность? Или «нет».")


@router.message(BookingForm.pet_health)
async def set_health(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    health = None if text.lower() in {"нет", "-"} else text
    behavior_data = (await state.get_data()).get("draft_behavior") or {}
    flags = BehaviorFlags.model_validate(behavior_data)
    if health:
        low = health.lower()
        if "инвалид" in low:
            flags.disability = True
        if "лечен" in low or "укол" in low or "таблет" in low:
            flags.needs_treatment = True
        if "моч" in low:
            flags.incontinence = True
        if "подвиж" in low or "хромот" in low or "не ходит" in low:
            flags.mobility_limited = True
    await state.update_data(draft_health=health, draft_behavior=flags.model_dump())
    await state.set_state(BookingForm.pet_passport)
    await message.answer(
        "Пришлите фото страниц ветпаспорта (данные, прививки, обработки).\n"
        "Можно несколько фото. Когда закончите — напишите «готово»."
    )


@router.message(BookingForm.pet_passport, F.photo)
async def passport_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    files = list(data.get("draft_passport_ids") or [])
    files.append(message.photo[-1].file_id)
    await state.update_data(draft_passport_ids=files)
    await message.answer(f"Фото сохранено ({len(files)}). Ещё фото или «готово».")


@router.message(BookingForm.pet_passport)
async def passport_done(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().lower()
    if text not in {"готово", "далее", "ok", "ок"}:
        await message.answer("Пришлите фото или напишите «готово».")
        return

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
        health_notes=data.get("draft_health"),
        passport_file_ids=list(data.get("draft_passport_ids") or []),
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
        f"Питомец «{pet.name}»{young} добавлен. Всего: {len(pets)}.",
        reply_markup=add_pet_kb(),
    )


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
        await state.update_data(unit_id=None, manual_matching=True, placement_flags=["sheets_unavailable"])
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
    await state.update_data(
        placement_flags=result.owner_flags,
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
    await message.answer("Подобрал свободные варианты:")

    for i, cand in enumerate(result.candidates, 1):
        acc = cand.accommodation
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
            caption += "\n" + ", ".join(cand.reasons[:2])
        if quote.provisional or cand.requires_owner_review:
            caption += "\n⚠️ требует подтверждения владельцем"

        choices.append((acc.id, f"{i}. {acc.name} — {quote.total_rub} ₽"))

        photos = []
        for path_str in acc.photo_paths[:5]:
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

    if result.requires_manual_matching:
        await message.answer("⚠️ Заявка всё равно уйдёт на ручное подтверждение.")

    await state.set_state(BookingForm.choose_unit)
    await message.answer("Выберите вариант:", reply_markup=unit_choice_kb(choices))


@router.callback_query(BookingForm.choose_unit, F.data.startswith("unit:"))
async def choose_unit(callback: CallbackQuery, state: FSMContext) -> None:
    unit_id = callback.data.split(":", 1)[1]
    if unit_id == "manual":
        await state.update_data(unit_id=None, manual_matching=True)
    else:
        await state.update_data(unit_id=unit_id, manual_matching=False)
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
    items = [(s.id, s.name, False) for s in _popular_services(catalog)]
    await message.answer(
        "Дополнительные услуги (можно несколько). Нажмите «Готово», когда закончите.",
        reply_markup=services_kb(items),
    )


@router.callback_query(BookingForm.services, F.data.startswith("svc:"))
async def toggle_service(callback: CallbackQuery, state: FSMContext, catalog: Catalog) -> None:
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected = set(data.get("service_ids") or [])

    if action in {"none", "done"}:
        if action == "none":
            await state.update_data(service_ids=[])
        await state.set_state(BookingForm.promo)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.answer(
            "Есть промокод? Пришлите его или напишите «нет»."
        )
        await callback.answer()
        return

    if action in selected:
        selected.remove(action)
    else:
        selected.add(action)
    await state.update_data(service_ids=sorted(selected))
    items = [(s.id, s.name, s.id in selected) for s in _popular_services(catalog)]
    await callback.message.edit_reply_markup(reply_markup=services_kb(items))
    await callback.answer()


@router.message(BookingForm.promo)
async def set_promo(message: Message, state: FSMContext, catalog: Catalog) -> None:
    text = (message.text or "").strip()
    promo = None if text.lower() in {"нет", "-", "нет промокода"} else text
    await state.update_data(promo_code=promo)
    # Build a fake callback-like summary via helper
    await _show_summary_message(message, state, catalog)


async def _show_summary_message(message: Message, state: FSMContext, catalog: Catalog) -> None:
    data = await state.get_data()
    pets = [PetProfile.model_validate(p) for p in data.get("pets") or []]
    feeding_opt = FeedingOption(data["feeding"]) if data.get("feeding") else None
    service_ids = list(data.get("service_ids") or [])
    unit_id = data.get("unit_id")
    promo = data.get("promo_code")

    lines = [
        "Проверьте заявку:",
        f"Даты: {data['date_from']} → {data['date_to']}",
        f"Питомцы: {', '.join(p.name for p in pets)}",
        f"Питание: {data.get('feeding')}",
    ]
    if service_ids:
        names = [catalog.get_service(sid).name if catalog.get_service(sid) else sid for sid in service_ids]
        lines.append("Услуги: " + ", ".join(names))
    else:
        lines.append("Услуги: нет")
    lines.append(f"Промокод: {promo or '—'}")

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
            )
            await state.update_data(
                price_total=quote.total_rub,
                deposit_amount=quote.deposit_rub,
                quote_explanation=quote.explanation,
                quote_provisional=quote.provisional,
            )
            lines.append(f"Место: {unit.name}")
            lines.append(f"Предварительно: {quote.total_rub} ₽")
            lines.append(f"Залог: {quote.deposit_rub} ₽")
            if quote.provisional:
                lines.append("(часть сумм ориентировочная)")
    else:
        deposit = PricingService(catalog).deposit_amount(len(pets) or 1)
        await state.update_data(price_total=None, deposit_amount=deposit)
        lines.append("Место: ручной подбор владельцем")
        lines.append(f"Залог (ориентир): {deposit} ₽")

    if data.get("requires_manual") or data.get("manual_matching"):
        lines.append("Флаги: " + ", ".join(data.get("placement_flags") or ["manual"]))

    await state.set_state(BookingForm.confirm_submit)
    await message.answer("\n".join(lines), reply_markup=submit_kb())


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
        )
    except SheetsUnavailableError:
        await callback.message.answer(
            "Календарь недоступен — заявку сейчас сохранить с проверкой занятости нельзя. "
            "Попробуйте позже или напишите владельцу напрямую."
        )
        await callback.answer()
        return
    except ValueError as exc:
        if str(exc) == "selected_unit_occupied":
            await callback.message.answer(
                "Выбранное место только что заняли. Начните подбор заново: /start"
            )
            await callback.answer()
            return
        raise

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
            f"Заявку {booking.id} отправил владельцу.\n"
            "Ожидайте решения. Реквизиты придут только после подтверждения.\n"
            "Статус: /status"
        )
    else:
        await callback.message.answer(
            f"Заявку {booking.id} сохранил, но OWNER_CHAT_ID не задан."
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
    except Exception as exc:
        await message.answer(f"Не принял чек: {exc}")
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
