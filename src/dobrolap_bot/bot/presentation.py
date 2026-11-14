from __future__ import annotations

from dobrolap_bot.bot.grooming import QUESTIONS as GROOMING_QUESTIONS

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from dobrolap_bot.config.loader import Catalog
from dobrolap_bot.domain.enums import BookingStatus, FeedingOption, PetKind
from dobrolap_bot.domain.models import PetProfile, PriceQuote, ServiceOffering
from dobrolap_bot.repositories.sqlite import BookingRecord
from dobrolap_bot.services.arrival import arrival_price_notice

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

TARIFF_LABELS = {
    "vip_plus": "VIP+ (отдельная комната)",
    "vip": "VIP",
    "comfort_plus": "Комфорт+",
    "comfort": "Комфорт",
    "premium": "Премиум (усиленный вольер XXL)",
    "standard_l": "Стандарт L (вольер)",
    "standard_m": "Стандарт M (вольер)",
    "optimal_s": "Оптимальный S (вольер)",
    "economy": "Эконом",
    "outdoor_comfort": "Уличный вольер Комфорт",
    "home": "Домашнее размещение",
}

TARIFF_ANY_LABEL = "Любой подходящий"


def tariff_label(tariff_kind: str) -> str:
    return TARIFF_LABELS.get(tariff_kind, tariff_kind)


STATUS_LABELS = {
    BookingStatus.DRAFT: "Черновик",
    BookingStatus.WAITING_OWNER: "Ожидает решения руководителя зоогостиницы",
    BookingStatus.OWNER_APPROVED: "Одобрена руководителем зоогостиницы",
    BookingStatus.WAITING_PAYMENT: "Место зарезервировано, ожидается оплата",
    BookingStatus.CONFIRMED: "Бронь подтверждена",
    BookingStatus.OWNER_REJECTED: "Отклонена руководителем зоогостиницы",
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
    PetKind.FERRET: "Хорёк",
    PetKind.OTHER: "Другой питомец",
}

FEEDING_LABELS = {
    FeedingOption.OWNER_FOOD: "Корм привозит хозяин питомца",
    FeedingOption.HOTEL_RATION: "Рацион зоогостиницы (платно, индивидуальный расчёт)",
    FeedingOption.NATURAL_COOKED: "Натуральное питание с приготовлением",
    FeedingOption.NATURAL_READY: "Натуральное питание: готовое, минимум нарезки (150 ₽/сутки)",
    FeedingOption.NATURAL_PORRIDGE: "Натуральное питание: приготовить кашу (250 ₽/сутки)",
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
    "separate_placement": "клиент выбрал раздельное размещение — подберите помещение каждому питомцу",
    "service_only": "разовая услуга без размещения — помещение не нужно",
    "non_dog_cat_species": "размещение небольшого питомца нужно подтвердить вручную",
    "no_matching_units": "автоматически подходящее помещение не найдено",
    "no_shared_unit_for_group": "для всех питомцев не найдено общее помещение",
    "needs_review:parasite_not_treated": "нет обязательной обработки от паразитов",
    "needs_review:dog_special_condition": "у собаки есть особенности поведения или здоровья",
    "needs_review:dog_unvaccinated": "у собаки нет действующей вакцинации",
    "needs_review:health_notes": "указаны особенности здоровья",
    "needs_review:behavior_notes": "поведение описано свободным текстом — проверьте исходное описание",
    "sheets_unavailable": "календарь Google Sheets был недоступен — свободное место не проверено",
    "calendar_dates_missing": "в календаре нет столбцов на выбранные даты — свободное место не проверено",
    "arrival_price_review": "время заезда требует ручного расчёта доплаты",
}

PLACEMENT_REASON_LABELS = {
    "priority:elderly_or_incontinence": "подходит пожилым питомцам и при проблемах с мочеиспусканием",
    "priority:treatment_or_disability": "подходит для питомцев, которым нужен уход или лечение",
    "priority:loud_barking_separate_house": "отдельное размещение для питомца, который громко лает",
    "priority:marks_territory_balcony": "под особенности питомца, который метит территорию",
    "priority:marks_territory_safe_room": "под особенности питомца, который метит территорию",
    "cat_requires_vip": "изолированное размещение с учётом особенностей кошки",
    "seasonal_unit": "сезонное помещение",
}

MARKING_RELOCATION_NOTE = (
    "Под особенности ваших питомцев больше подходит этот вариант. "
    "Готовы обсудить детали других видов размещения. "
    "В первый день передержки будет видно, подходят ли условия; "
    "при плохой реакции или стрессе можно переселить животных в другую комнату."
)

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
    if months == 0:
        return "младше 1 месяца"
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
    if flag.startswith("tariff_requested:"):
        tariff_kind = flag.split(":", 1)[1]
        return f"клиент выбрал тариф: {tariff_label(tariff_kind)}"
    return PLACEMENT_FLAG_LABELS.get(flag, "есть особенность, которую нужно проверить вручную")


def placement_reason_label(reason: str) -> str:
    return PLACEMENT_REASON_LABELS.get(reason, "вариант подобран по анкете питомца")


def _pet_lines(pet: PetProfile, *, prefix: str = "", service_only: bool = False) -> list[str]:
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
    if pet.sex:
        details.append(f"пол: {pet.sex}")
        details.append(f"кастрирован/стерилизована: {yes_no_unknown(pet.neutered)}")
        if pet.sex == "женский":
            details.append(f"течка: {yes_no_unknown(pet.in_heat)}")
    if details:
        lines.append(f"{indent}  " + "; ".join(details))
    if pet.grooming_answers:
        lines.append(f"{indent}  Анкета груминга:")
        for key, label, _, _ in GROOMING_QUESTIONS:
            value = pet.grooming_answers.get(key)
            if value is not None:
                text = ("Да" if value else "Нет") if isinstance(value, bool) else value
                lines.append(f"{indent}  {label}: {text}")
        if pet.grooming_reference_file_id:
            lines.append(f"{indent}  Фото-референс: приложено")
        return lines
    if pet.kind in {PetKind.DOG, PetKind.CAT}:
        lines.append(
            f"{indent}  Вакцинация: {yes_no_unknown(pet.vaccinated)}; "
            f"обработка от паразитов: {yes_no_unknown(pet.parasite_treated)}"
        )
        lines.append(
            f"{indent}  Ветпаспорт: "
            + (f"загружено фото — {len(pet.passport_file_ids)}" if pet.passport_file_ids else "фото не загружено")
        )
    elif pet.kind in {
        PetKind.BIRD,
        PetKind.RABBIT,
        PetKind.RAT,
        PetKind.HAMSTER,
        PetKind.GUINEA_PIG,
        PetKind.FERRET,
    }:
        if not service_only:
            lines.append(f"{indent}  Владелец должен привезти собственную клетку (обязательно).")
    features = behavior_labels(pet)
    lines.append(f"{indent}  Поведение: " + (", ".join(features) if features else "особенности не отмечены"))
    if pet.behavior_notes and pet.behavior_notes.strip().lower() not in {"нет", "нет особенностей", "-"}:
        lines.append(f"{indent}  Описание поведения: {pet.behavior_notes}")
    lines.append(f"{indent}  Здоровье: {pet.health_notes or 'особенности не указаны'}")
    return lines


def service_option_label(service: ServiceOffering) -> str:
    low, high = service.price_from_rub, service.price_to_rub
    if low is not None and high is not None and low != high:
        price = f"{format_money(low)}–{format_money(high)}"
    elif low is not None:
        price = f"от {format_money(low)}" if high is None else format_money(low)
    elif high is not None:
        price = f"до {format_money(high)}"
    else:
        price = "по согласованию"
    unit = {"per_day": "/сутки", "visit": "/визит", "session": "/занятие", "one_way": "/в одну сторону"}.get(service.unit, "")
    return f"{service.name} — {price}{unit}"


def _service_category_label(data: dict) -> str | None:
    details = data.get("service_details") or {}
    category = data.get("service_category") or details.get("service_category")
    return {
        "grooming": "Груминг",
        "taxi": "Зоотакси",
        "walk": "Выгул (собаки)",
        "trainer": "Кинолог (собаки)",
        "zoopsych": "Зоопсихолог (кошки)",
        "care": "МедУход",
        "home": "Выезд на дом (зооняня)",
    }.get(category)


def _service_location_text(data: dict) -> str:
    details = data.get("service_details") or {}
    location = data.get("service_location") or details.get("service_location")
    category = data.get("service_category") or details.get("service_category")
    if location == "hotel":
        if category in {None, "", "grooming"}:
            return "В зоогостинице — груминг"
        if category == "trainer":
            return "Кинолог (собаки): по адресу зоогостиницы"
        if category == "zoopsych":
            return "Зоопсихолог (кошки): по адресу зоогостиницы"
        return "По адресу зоогостиницы"
    if location == "home":
        if category in {None, "", "home"}:
            return "Выезд на дом (зооняня)"
        if category == "walk":
            return "Выгул (собаки): по адресу клиента"
        if category == "trainer":
            return "Кинолог (собаки): по вашему адресу"
        if category == "zoopsych":
            return "Зоопсихолог (кошки): по вашему адресу"
        if category == "taxi":
            return "Зоотакси: адрес клиента"
        return "По вашему адресу"
    return "Место услуги: уточняется"


def _trainer_program_text(data: dict) -> str | None:
    details = data.get("service_details") or {}
    label = data.get("trainer_program_label") or details.get("trainer_program_label")
    if label:
        return f"Программа кинолога: {label}"
    program = data.get("trainer_program") or details.get("trainer_program")
    return f"Программа кинолога: {program}" if program else None


def _service_time_text(data: dict) -> str:
    details = data.get("service_details") or {}
    schedule = data.get("walk_schedule") or details.get("walk_schedule")
    if (data.get("service_category") or details.get("service_category")) == "walk" and schedule:
        return f"Расписание выгула (пожелание, подтвердит оператор): {schedule}"
    return f"Время визита: {data.get('arrival_time') or 'Не указано'}"


def _service_visit_dates_text(data: dict) -> str:
    date_from = date.fromisoformat(data["date_from"])
    date_to = date.fromisoformat(data["date_to"])
    if (date_to - date_from).days > 1:
        return f"Период услуги: {format_date(date_from)} — {format_date(date_to)}"
    return f"Дата визита: {format_date(date_from)}"


def _arrival_notice(data: dict) -> str:
    try:
        value = time.fromisoformat(data.get("arrival_time") or "")
    except ValueError:
        return ""
    return arrival_price_notice(value)


def _services_text(service_ids: list[str], catalog: Catalog) -> str:
    names = []
    for service_id in service_ids:
        service = catalog.get_service(service_id)
        if service:
            names.append(service_option_label(service))
    return ", ".join(names) if names else "Не выбраны"


def placement_mode_label(data: dict) -> str:
    assignments = data.get("room_assignments") or []
    if len(assignments) > 1 and any(len(item["pet_indices"]) > 1 for item in assignments):
        return "частично"
    return "вместе" if data.get("placement_together", True) else "раздельно"


def room_assignment_lines(data: dict, pets: list[PetProfile], catalog: Catalog) -> list[str]:
    lines = []
    for item in data.get("room_assignments") or []:
        names = ", ".join(pets[index].name for index in item["pet_indices"])
        if item.get("manual") or not item.get("unit_id"):
            lines.append(f"{names} → подбирает руководитель зоогостиницы")
            continue
        unit = catalog.get_accommodation(item["unit_id"])
        label = item.get("sheet_label") or "—"
        lines.append(f"{names} → {unit.name if unit else item['unit_id']} ({label})")
    return lines


def format_owner_summary(booking: BookingRecord, catalog: Catalog) -> str:
    pets = [PetProfile.model_validate(p) for p in booking.payload.get("pets") or []]
    service_only = bool(booking.payload.get("service_only"))
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
    ]
    if service_only:
        lines.append(
            _service_visit_dates_text(
                {
                    "date_from": booking.date_from.isoformat(),
                    "date_to": booking.date_to.isoformat(),
                }
            )
        )
        lines.append(_service_time_text(booking.payload))
        lines.append(f"Адрес: {booking.payload.get('service_address') or 'Не указан'}")
        lines.append(_service_location_text(booking.payload))
        program = _trainer_program_text(booking.payload)
        if program:
            lines.append(program)
    else:
        lines.append(f"Даты: {format_date(booking.date_from)} — {format_date(booking.date_to)}")
        lines.append(f"Время заезда: {booking.payload.get('arrival_time') or 'Не указано'}")
        lines.append(_arrival_notice(booking.payload))
    lines.append("")
    lines.append("Питомцы")
    if pets:
        for index, pet in enumerate(pets, 1):
            lines.extend(_pet_lines(pet, prefix=f"{index}. " if len(pets) > 1 else "• ", service_only=service_only))
        if len(pets) > 1 and not service_only:
            lines.append("Размещение питомцев: " + placement_mode_label(booking.payload))
    else:
        lines.append("Не указаны")

    lines.append("")
    lines.append("Размещение и услуги")
    if service_only:
        lines.append("Формат: разовая услуга без размещения")
    else:
        lines.append(f"Помещение: {unit.name if unit else 'Подбирается руководителем зоогостиницы'}")
        lines.extend(room_assignment_lines(booking.payload, pets, catalog))
        lines.append(f"Питание: {feeding_label(booking.payload.get('feeding'))}")
    lines.extend(
        [
            f"Дополнительные услуги: {_services_text(list(booking.payload.get('service_ids') or []), catalog)}",
            f"Промокод: {booking.payload.get('promo_code') or 'Нет'}",
            *(["Запрос скидки за отзыв: оператор проверит подтверждение и площадку"] if booking.payload.get("review_discount_claim") else []),
            f"Предварительная стоимость: {format_money(booking.price_total) if booking.price_total is not None else 'рассчитает оператор'}",
            f"Залог: {format_money(booking.deposit_amount)}",
        ]
    )
    taxi_address = (booking.payload.get("service_details") or {}).get("taxi_address")
    for item in booking.payload.get("quote_lines") or []:
        if item.get("scope") in {"accommodation", "discount"}:
            lines.append(f"{item['label']}: {format_money(item['amount_rub'])}")
    if booking.payload.get("quote_explanation"):
        lines.append(booking.payload["quote_explanation"])
    if taxi_address:
        lines.append(f"Адрес для зоотакси: {taxi_address}")
    food_source = (booking.payload.get("service_details") or {}).get("natural_food_source")
    if food_source:
        lines.append("Продукты для натурального питания: " + ("предоставляет хозяин питомца" if food_source == "owner_provides" else "покупает гостиница, передаёт чеки"))
    if booking.payload.get("service_ids"):
        lines.append("Стоимость дополнительных услуг определит оператор.")
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
    service_only = bool(booking.payload.get("service_only"))
    unit = catalog.get_accommodation(booking.unit_id) if booking.unit_id else None
    pets = [PetProfile.model_validate(p) for p in booking.payload.get("pets") or []]
    pet_names = ", ".join(p.name for p in pets) or "Не указаны"
    lines = [
        f"Заявка №{booking.id}",
        f"Статус: {status_label(booking.status)}",
    ]
    if service_only:
        lines.append(
            _service_visit_dates_text(
                {
                    "date_from": booking.date_from.isoformat(),
                    "date_to": booking.date_to.isoformat(),
                }
            )
        )
        lines.append(_service_time_text(booking.payload))
        lines.append(f"Адрес: {booking.payload.get('service_address') or 'Не указан'}")
        lines.append(_service_location_text(booking.payload))
        program = _trainer_program_text(booking.payload)
        if program:
            lines.append(program)
    else:
        lines.append(f"Даты: {format_date(booking.date_from)} — {format_date(booking.date_to)}")
        lines.append(f"Время заезда: {booking.payload.get('arrival_time') or 'Не указано'}")
        lines.append(_arrival_notice(booking.payload))
    lines.append(
        f"Питомцы: {pet_names}"
        + (
            f" ({placement_mode_label(booking.payload)})"
            if len(pets) > 1 and not service_only else ""
        )
    )
    if service_only:
        lines.append("Формат: разовая услуга без размещения")
    else:
        lines.append(f"Размещение: {unit.name if unit else 'подбирает руководитель зоогостиницы'}")
        lines.extend(room_assignment_lines(booking.payload, pets, catalog))
        lines.append(f"Питание: {feeding_label(booking.payload.get('feeding'))}")
    lines.append(f"Услуги: {_services_text(list(booking.payload.get('service_ids') or []), catalog)}")
    lines.append(f"Предварительная стоимость: {format_money(booking.price_total)}")
    lines.append(f"Залог: {format_money(booking.deposit_amount)}")
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
    service_only = bool(data.get("service_only"))
    unit = catalog.get_accommodation(data.get("unit_id")) if data.get("unit_id") else None
    lines = ["Проверьте заявку", f"Телефон: {data.get('customer_contact') or 'Не указан'}"]
    if service_only:
        lines.append(_service_visit_dates_text(data))
        lines.append(_service_time_text(data))
        lines.append(f"Адрес: {data.get('service_address') or 'Не указан'}")
        lines.append(_service_location_text(data))
        program = _trainer_program_text(data)
        if program:
            lines.append(program)
    else:
        lines.append(
            f"Даты: {format_date(date.fromisoformat(data['date_from']))} — "
            f"{format_date(date.fromisoformat(data['date_to']))}"
        )
        lines.append(f"Время заезда: {data.get('arrival_time') or 'Не указано'}")
        lines.append(_arrival_notice(data))
    lines.append("")
    lines.append("Питомцы")
    for index, pet in enumerate(pets, 1):
        lines.extend(_pet_lines(pet, prefix=f"{index}. " if len(pets) > 1 else "• ", service_only=service_only))
    if len(pets) > 1 and not service_only:
        lines.append("Размещение питомцев: " + placement_mode_label(data))
    lines.append("")
    if service_only:
        lines.append("Формат: разовая услуга без размещения")
    else:
        lines.append(f"Размещение: {unit.name if unit else 'подбирает руководитель зоогостиницы'}")
        lines.extend(room_assignment_lines(data, pets, catalog))
        lines.append(f"Питание: {feeding_label(data.get('feeding'))}")
    lines.extend(
        [
            f"Дополнительные услуги: {_services_text(list(data.get('service_ids') or []), catalog)}",
        f"Промокод: {data.get('promo_code') or 'Нет'}",
        *(["Запрос скидки за отзыв: оператор проверит подтверждение и площадку"] if data.get("review_discount_claim") else []),
        ]
    )
    if "zoo_taxi" in set(data.get("service_ids") or []) and data.get("taxi_address"):
        lines.append(f"Адрес для зоотакси: {data['taxi_address']}")
    if data.get("natural_food_source"):
        lines.append("Продукты для натурального питания: " + ("предоставляет хозяин питомца" if data["natural_food_source"] == "owner_provides" else "покупает гостиница, передаёт чеки"))
    if quote:
        nights = (
            date.fromisoformat(data["date_to"]) - date.fromisoformat(data["date_from"])
        ).days
        if quote.has_accommodation_amount or any(
            line.scope.value in {"accommodation", "discount"} for line in quote.lines
        ):
            for line in quote.lines:
                if line.scope.value in {"accommodation", "discount"}:
                    lines.append(f"{line.label}: {format_money(line.amount_rub)}")
            gross = sum(
                line.amount_rub for line in quote.lines if line.scope.value == "accommodation"
            )
            discounts = sum(
                line.amount_rub for line in quote.lines if line.scope.value == "discount"
            )
            net = gross + discounts
            if discounts:
                lines.append(f"Проживание без скидки: {format_money(gross)}")
                lines.append(f"Скидка на питомцев: {format_money(discounts)}")
                lines.append(f"Предварительно со скидкой: {format_money(net)}")
                if nights > 0:
                    lines.append(
                        f"≈ {net // nights} ₽/сут. со скидкой "
                        f"(без скидки ≈ {gross // nights} ₽/сут.)"
                    )
            else:
                lines.append(f"Предварительная стоимость проживания: {format_money(net)}")
                if nights > 0:
                    lines.append(f"≈ {net // nights} ₽/сут.")
            if quote.total_rub != net:
                lines.append(f"Итого с питанием/услугами: {format_money(quote.total_rub)}")
            if data.get("review_discount_claim"):
                lines.append(
                    "Заявлена скидка за отзыв: после проверки оператор согласует окончательную цену со скидкой."
                )
            lines.append(quote.explanation)
        else:
            lines.append("Стоимость проживания сообщит оператор после уточнения условий.")
            if data.get("review_discount_claim"):
                lines.append(
                    "Заявлена скидка за отзыв: после проверки оператор согласует окончательную цену со скидкой."
                )
        lines.append(f"Залог: {format_money(quote.deposit_rub)}")
        if quote.provisional:
            lines.append("⚠️ В расчёте есть ориентировочные суммы. Итог подтвердит руководитель зоогостиницы.")
    elif service_only:
        lines.append(f"Залог: {format_money(data.get('deposit_amount'))}")
        lines.append("Стоимость услуг сообщит руководитель зоогостиницы.")
    else:
        lines.append(f"Залог: {format_money(data.get('deposit_amount'))}")
        lines.append("Стоимость проживания сообщит руководитель зоогостиницы после подбора помещения.")
    if data.get("service_ids") and not service_only:
        lines.append("Стоимость дополнительных услуг сообщит оператор отдельно.")
    return "\n".join(lines)


SHORT_STATUS_LABELS = {
    BookingStatus.DRAFT: "черновик",
    BookingStatus.WAITING_OWNER: "ждёт решения",
    BookingStatus.OWNER_APPROVED: "одобрена",
    BookingStatus.WAITING_PAYMENT: "ждёт оплату",
    BookingStatus.CONFIRMED: "подтверждена",
    BookingStatus.OWNER_REJECTED: "отклонена",
    BookingStatus.CANCELLED: "отменена",
    BookingStatus.EXPIRED: "истекла",
}


def short_status_label(status: BookingStatus | str | None) -> str:
    try:
        normalized = status if isinstance(status, BookingStatus) else BookingStatus(str(status))
    except ValueError:
        return str(status or "?")
    return SHORT_STATUS_LABELS.get(normalized, status_label(normalized))


def _pet_names(booking: BookingRecord) -> str:
    names = []
    for raw in booking.payload.get("pets") or []:
        name = str((raw or {}).get("name") or "").strip()
        if name:
            names.append(name)
    return ", ".join(names) if names else "—"


def format_admin_overview(counts: dict[str, int]) -> str:
    pending = counts.get(BookingStatus.WAITING_OWNER.value, 0)
    unpaid = counts.get(BookingStatus.WAITING_PAYMENT.value, 0)
    confirmed = counts.get(BookingStatus.CONFIRMED.value, 0)
    cancelled = counts.get(BookingStatus.CANCELLED.value, 0)
    expired = counts.get(BookingStatus.EXPIRED.value, 0)
    rejected = counts.get(BookingStatus.OWNER_REJECTED.value, 0)
    total = sum(counts.values())
    return "\n".join(
        [
            "📋 Админка Добролап",
            "",
            f"Всего заявок в базе: {total}",
            f"⏳ Ждут вашего решения: {pending}",
            f"💳 Ждут оплату залога: {unpaid}",
            f"✅ Подтверждённые брони: {confirmed}",
            f"❌ Отменены / отклонены / истекли: {cancelled + rejected + expired}",
            "",
            "Выберите раздел кнопками ниже.",
        ]
    )


def format_admin_booking_line(booking: BookingRecord, catalog: Catalog) -> str:
    unit = catalog.get_accommodation(booking.unit_id) if booking.unit_id else None
    unit_name = unit.name if unit else (booking.unit_id or "без помещения")
    client = booking.customer_name or booking.customer_contact or "клиент"
    hold = ""
    if booking.status == BookingStatus.WAITING_PAYMENT and booking.hold_expires_at:
        hold = f", оплатить до {format_datetime(booking.hold_expires_at)}"
    return (
        f"• #{booking.id[:8]} · {short_status_label(booking.status)}\n"
        f"  {format_date(booking.date_from)}–{format_date(booking.date_to)} · {unit_name}\n"
        f"  {client} · {_pet_names(booking)} · залог {format_money(booking.deposit_amount)}{hold}"
    )


def format_admin_bookings_list(
    title: str,
    bookings: list[BookingRecord],
    catalog: Catalog,
    *,
    empty_text: str,
) -> str:
    if not bookings:
        return f"{title}\n\n{empty_text}"
    lines = [title, ""]
    for booking in bookings:
        lines.append(format_admin_booking_line(booking, catalog))
        lines.append("")
    return "\n".join(lines).rstrip()


def format_admin_clients(clients: list[dict]) -> str:
    if not clients:
        return "👥 Клиенты\n\nПока нет клиентов в базе."
    lines = ["👥 Клиенты", ""]
    for item in clients:
        name = item.get("name") or "Без имени"
        contact = item.get("contact") or "телефон не указан"
        tg = item.get("telegram_user_id")
        lines.append(
            f"• {name} · {contact}\n"
            f"  tg:{tg} · заявок {item.get('bookings_total', 0)}"
            f" (активных {item.get('bookings_active', 0)})"
        )
        lines.append("")
    return "\n".join(lines).rstrip()


def admin_booking_button_title(booking: BookingRecord) -> str:
    client = booking.customer_name or booking.customer_contact or _pet_names(booking)
    return f"{booking.id[:8]} · {format_date(booking.date_from)} · {client}"[:64]
