from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from dobrolap_bot.config.loader import Catalog
from dobrolap_bot.domain.enums import BookingStatus, FeedingOption, PetKind
from dobrolap_bot.domain.models import PetProfile, PriceQuote
from dobrolap_bot.repositories.sqlite import BookingRecord

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

STATUS_LABELS = {
    BookingStatus.DRAFT: "Черновик",
    BookingStatus.WAITING_OWNER: "Ожидает решения владельца",
    BookingStatus.OWNER_APPROVED: "Одобрена владельцем",
    BookingStatus.WAITING_PAYMENT: "Место зарезервировано, ожидается оплата",
    BookingStatus.CONFIRMED: "Бронь подтверждена",
    BookingStatus.OWNER_REJECTED: "Отклонена владельцем",
    BookingStatus.CANCELLED: "Отменена",
    BookingStatus.EXPIRED: "Срок резерва истёк",
}

PET_KIND_LABELS = {
    PetKind.DOG: "Собака",
    PetKind.CAT: "Кошка",
    PetKind.RABBIT: "Кролик",
    PetKind.RAT: "Крыса",
    PetKind.HAMSTER: "Хомяк",
    PetKind.BIRD: "Птица",
    PetKind.GUINEA_PIG: "Морская свинка",
    PetKind.OTHER: "Другой питомец",
}

FEEDING_LABELS = {
    FeedingOption.OWNER_FOOD: "Корм привозит владелец",
    FeedingOption.HOTEL_RATION: "Рацион зоогостиницы",
    FeedingOption.NATURAL_COOKED: "Натуральное питание с приготовлением",
}

BEHAVIOR_LABELS = {
    "aggression": "агрессия к людям или животным",
    "zoo_aggression": "агрессия к животным",
    "high_stress": "сильный стресс",
    "distrust_humans": "не доверяет незнакомым людям",
    "marks_territory": "метит территорию",
    "chews_furniture": "грызёт мебель",
    "loud_barking": "громко или часто лает",
    "elderly": "пожилой питомец",
    "mobility_limited": "ограничена подвижность",
    "incontinence": "есть проблемы с мочеиспусканием",
    "needs_treatment": "нужны лекарства или процедуры",
    "disability": "есть инвалидность",
}

PLACEMENT_FLAG_LABELS = {
    "empty_pet_list": "в заявке нет питомцев",
    "multi_pet_group": "несколько питомцев — совместное размещение нужно подтвердить",
    "non_dog_cat_species": "размещение небольшого питомца нужно подтвердить вручную",
    "no_matching_units": "автоматически подходящее помещение не найдено",
    "no_shared_unit_for_group": "для всех питомцев не найдено общее помещение",
    "needs_review:parasite_not_treated": "нет обязательной обработки от паразитов",
    "needs_review:dog_special_condition": "у собаки есть особенности поведения или здоровья",
    "needs_review:dog_unvaccinated": "у собаки нет действующей вакцинации",
    "needs_review:health_notes": "указаны особенности здоровья",
    "sheets_unavailable": "календарь Google Sheets был недоступен — свободное место не проверено",
}

PLACEMENT_REASON_LABELS = {
    "priority:elderly_or_incontinence": "подходит пожилым питомцам и при проблемах с мочеиспусканием",
    "priority:treatment_or_disability": "подходит для питомцев, которым нужен уход или лечение",
    "priority:loud_barking_separate_house": "отдельное размещение для питомца, который громко лает",
    "cat_requires_vip": "изолированное размещение с учётом особенностей кошки",
    "seasonal_unit": "сезонное помещение",
}

REFUND_STATUS_LABELS = {
    "pending": "ожидает ручного возврата",
    "done": "возвращён",
}


def status_label(status: BookingStatus | str | None) -> str:
    if status is None:
        return "Не указан"
    try:
        normalized = status if isinstance(status, BookingStatus) else BookingStatus(status)
    except ValueError:
        return "Требует уточнения"
    return STATUS_LABELS[normalized]


def pet_kind_label(kind: PetKind | str | None) -> str:
    if kind is None:
        return "Не указан"
    try:
        normalized = kind if isinstance(kind, PetKind) else PetKind(kind)
    except ValueError:
        return "Другой питомец"
    return PET_KIND_LABELS[normalized]


def feeding_label(value: FeedingOption | str | None) -> str:
    if not value:
        return "Не указано"
    try:
        normalized = value if isinstance(value, FeedingOption) else FeedingOption(value)
    except ValueError:
        return "Требует уточнения"
    return FEEDING_LABELS[normalized]


def format_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "Не указано"
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y в %H:%M")


def format_money(value: int | None) -> str:
    return "Не рассчитана" if value is None else f"{value:,} ₽".replace(",", " ")


def yes_no_unknown(value: bool | None) -> str:
    if value is True:
        return "Да"
    if value is False:
        return "Нет"
    return "Не указано"


def format_age(months: int | None) -> str:
    if months is None:
        return "не указан"
    if months < 12:
        suffix = "месяц" if months % 10 == 1 and months % 100 != 11 else "месяца"
        if months % 10 not in {1, 2, 3, 4} or months % 100 in {11, 12, 13, 14}:
            suffix = "месяцев"
        return f"{months} {suffix}"
    years, rest = divmod(months, 12)
    year_suffix = "год" if years % 10 == 1 and years % 100 != 11 else "года"
    if years % 10 not in {1, 2, 3, 4} or years % 100 in {11, 12, 13, 14}:
        year_suffix = "лет"
    return f"{years} {year_suffix}" + (f" {rest} мес." if rest else "")


def behavior_labels(pet: PetProfile) -> list[str]:
    return [
        BEHAVIOR_LABELS[key]
        for key, enabled in pet.behavior.model_dump().items()
        if enabled and key in BEHAVIOR_LABELS
    ]


def placement_flag_label(flag: str) -> str:
    if flag.startswith("incomplete_passport:"):
        name = flag.split(":", 1)[1]
        return f"нет фото ветпаспорта ({name})"
    return PLACEMENT_FLAG_LABELS.get(flag, "есть особенность, которую нужно проверить вручную")


def placement_reason_label(reason: str) -> str:
    return PLACEMENT_REASON_LABELS.get(reason, "вариант подобран по анкете питомца")


def _pet_lines(pet: PetProfile, *, prefix: str = "") -> list[str]:
    title = f"{pet_kind_label(pet.kind)} — {pet.name}"
    lines = [f"{prefix}{title}"]
    indent = " " * len(prefix)
    details: list[str] = []
    if pet.age_months is not None:
        details.append(f"возраст: {format_age(pet.age_months)}")
    if pet.breed:
        details.append(f"порода: {pet.breed}")
    if pet.weight_kg is not None:
        details.append(f"вес: {pet.weight_kg:g} кг")
    if details:
        lines.append(f"{indent}  " + "; ".join(details))
    if pet.kind in {PetKind.DOG, PetKind.CAT}:
        lines.append(
            f"{indent}  Вакцинация: {yes_no_unknown(pet.vaccinated)}; "
            f"обработка от паразитов: {yes_no_unknown(pet.parasite_treated)}"
        )
        lines.append(
            f"{indent}  Ветпаспорт: "
            + (f"загружено фото — {len(pet.passport_file_ids)}" if pet.passport_file_ids else "фото не загружено")
        )
    features = behavior_labels(pet)
    lines.append(f"{indent}  Поведение: " + (", ".join(features) if features else "особенности не отмечены"))
    lines.append(f"{indent}  Здоровье: {pet.health_notes or 'особенности не указаны'}")
    return lines


def _services_text(service_ids: list[str], catalog: Catalog) -> str:
    names = []
    for service_id in service_ids:
        service = catalog.get_service(service_id)
        if service:
            names.append(service.name)
    return ", ".join(names) if names else "Не выбраны"


def format_owner_summary(booking: BookingRecord, catalog: Catalog) -> str:
    pets = [PetProfile.model_validate(p) for p in booking.payload.get("pets") or []]
    unit = catalog.get_accommodation(booking.unit_id) if booking.unit_id else None
    username = booking.payload.get("client_username")
    contact = booking.customer_contact or booking.payload.get("customer_contact")
    if contact and str(contact).startswith("@"):
        username = username or str(contact).removeprefix("@")
        contact = None
    telegram = f"@{username}" if username else "профиль без username"
    lines = [
        f"Заявка №{booking.id}",
        f"Статус: {status_label(booking.status)}",
        "",
        "Клиент",
        f"Имя: {booking.customer_name or 'Не указано'}",
        f"Телефон: {contact or 'Не указан'}",
        f"Telegram: {telegram}",
        f"Даты: {format_date(booking.date_from)} — {format_date(booking.date_to)}",
        "",
        "Питомцы",
    ]
    if pets:
        for index, pet in enumerate(pets, 1):
            lines.extend(_pet_lines(pet, prefix=f"{index}. " if len(pets) > 1 else "• "))
    else:
        lines.append("Не указаны")

    lines.extend(
        [
            "",
            "Размещение и услуги",
            f"Помещение: {unit.name if unit else 'Подбирается владельцем'}",
            f"Питание: {feeding_label(booking.payload.get('feeding'))}",
            f"Дополнительные услуги: {_services_text(list(booking.payload.get('service_ids') or []), catalog)}",
            f"Промокод: {booking.payload.get('promo_code') or 'Нет'}",
            f"Предварительная стоимость: {format_money(booking.price_total)}",
            f"Залог: {format_money(booking.deposit_amount)}",
        ]
    )
    if booking.payload.get("quote_provisional"):
        lines.append("⚠️ В расчёте есть ориентировочные суммы — проверьте их перед подтверждением.")

    flags = sorted(set(booking.payload.get("placement_flags") or []))
    if flags:
        lines.append("")
        lines.append("Что нужно проверить")
        lines.extend(f"• {placement_flag_label(flag)}" for flag in flags)
    if booking.hold_expires_at:
        lines.append(f"Резерв действует до: {format_datetime(booking.hold_expires_at)} (МСК)")
    refund = booking.payload.get("refund") or {}
    if refund.get("status"):
        lines.append(f"Возврат залога: {REFUND_STATUS_LABELS.get(refund['status'], 'требует уточнения')}")
        if refund.get("note"):
            lines.append(f"Комментарий по возврату: {refund['note']}")
    return "\n".join(lines)


def format_client_status(booking: BookingRecord, catalog: Catalog) -> str:
    unit = catalog.get_accommodation(booking.unit_id) if booking.unit_id else None
    pets = [PetProfile.model_validate(p) for p in booking.payload.get("pets") or []]
    pet_names = ", ".join(p.name for p in pets) or "Не указаны"
    lines = [
        f"Заявка №{booking.id}",
        f"Статус: {status_label(booking.status)}",
        f"Даты: {format_date(booking.date_from)} — {format_date(booking.date_to)}",
        f"Питомцы: {pet_names}",
        f"Размещение: {unit.name if unit else 'подбирает владелец'}",
        f"Питание: {feeding_label(booking.payload.get('feeding'))}",
        f"Услуги: {_services_text(list(booking.payload.get('service_ids') or []), catalog)}",
        f"Предварительная стоимость: {format_money(booking.price_total)}",
        f"Залог: {format_money(booking.deposit_amount)}",
    ]
    if booking.hold_expires_at and booking.status == BookingStatus.WAITING_PAYMENT:
        lines.append(f"Оплатить нужно до: {format_datetime(booking.hold_expires_at)} (МСК)")
    return "\n".join(lines)


def format_draft_summary(
    *,
    data: dict,
    pets: list[PetProfile],
    catalog: Catalog,
    quote: PriceQuote | None,
) -> str:
    unit = catalog.get_accommodation(data.get("unit_id")) if data.get("unit_id") else None
    lines = [
        "Проверьте заявку",
        f"Телефон: {data.get('customer_contact') or 'Не указан'}",
        f"Даты: {format_date(date.fromisoformat(data['date_from']))} — {format_date(date.fromisoformat(data['date_to']))}",
        "",
        "Питомцы",
    ]
    for index, pet in enumerate(pets, 1):
        lines.extend(_pet_lines(pet, prefix=f"{index}. " if len(pets) > 1 else "• "))
    lines.extend(
        [
            "",
            f"Размещение: {unit.name if unit else 'подбирает владелец'}",
            f"Питание: {feeding_label(data.get('feeding'))}",
            f"Дополнительные услуги: {_services_text(list(data.get('service_ids') or []), catalog)}",
            f"Промокод: {data.get('promo_code') or 'Нет'}",
        ]
    )
    if quote:
        lines.extend(
            [
                f"Предварительная стоимость: {format_money(quote.total_rub)}",
                f"Залог: {format_money(quote.deposit_rub)}",
            ]
        )
        if quote.provisional:
            lines.append("⚠️ В расчёте есть ориентировочные суммы. Итог подтвердит владелец.")
    else:
        lines.append(f"Залог: {format_money(data.get('deposit_amount'))}")
        lines.append("Стоимость проживания сообщит владелец после подбора помещения.")
    return "\n".join(lines)
