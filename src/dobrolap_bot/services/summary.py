from __future__ import annotations

from dobrolap_bot.config.loader import Catalog
from dobrolap_bot.domain.enums import FeedingOption
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.repositories.sqlite import BookingRecord

FEEDING_LABELS = {
    FeedingOption.OWNER_FOOD.value: "Корм владельца",
    FeedingOption.HOTEL_RATION.value: "Рацион гостиницы",
    FeedingOption.NATURAL_COOKED.value: "Натуральное с приготовлением",
}


def format_owner_summary(booking: BookingRecord, catalog: Catalog) -> str:
    pets = [PetProfile.model_validate(p) for p in booking.payload.get("pets") or []]
    unit = catalog.get_accommodation(booking.unit_id) if booking.unit_id else None
    username = booking.payload.get("client_username")
    client = f"@{username}" if username else str(booking.customer_telegram_id)
    lines = [
        f"🆕 Заявка `{booking.id}`",
        f"Статус: {booking.status.value}",
        f"Клиент: {client} ({booking.customer_name or '—'})",
        f"Даты: {booking.date_from.isoformat()} → {booking.date_to.isoformat()}",
    ]
    if unit:
        lines.append(f"Место: {unit.name} (`{unit.id}`)")
    elif booking.payload.get("manual_matching"):
        lines.append("Место: ручной подбор")
    else:
        lines.append("Место: не выбрано")

    feeding = booking.payload.get("feeding")
    lines.append(f"Питание: {FEEDING_LABELS.get(feeding, feeding or '—')}")

    service_ids = booking.payload.get("service_ids") or []
    if service_ids:
        names = []
        for sid in service_ids:
            svc = catalog.get_service(sid)
            names.append(svc.name if svc else sid)
        lines.append("Услуги: " + ", ".join(names))

    lines.append("Питомцы:")
    for pet in pets:
        bits = [pet.kind.value, pet.name]
        if pet.weight_kg is not None:
            bits.append(f"{pet.weight_kg} кг")
        bits.append("вакц.+" if pet.vaccinated else "вакц.-")
        bits.append("паразиты+" if pet.parasite_treated else "паразиты-")
        lines.append("• " + ", ".join(bits))
        if pet.health_notes:
            lines.append(f"  здоровье: {pet.health_notes}")
        behavior_on = [k for k, v in pet.behavior.model_dump().items() if v]
        if behavior_on:
            lines.append("  поведение: " + ", ".join(behavior_on))
        if pet.passport_file_ids:
            lines.append(f"  паспорт: {len(pet.passport_file_ids)} фото")

    flags = booking.payload.get("placement_flags") or []
    if flags:
        lines.append("Флаги: " + ", ".join(flags))
    if any(str(f).startswith("incomplete_passport") for f in flags):
        lines.append("⚠️ Анкета неполная: нет фото ветпаспорта")
    if booking.hold_expires_at is not None:
        lines.append(f"Резерв до: {booking.hold_expires_at.isoformat()}")
    refund = booking.payload.get("refund") or {}
    if refund.get("status"):
        lines.append(f"Возврат залога: {refund.get('status')}")
        if refund.get("note"):
            lines.append(f"  комментарий: {refund['note']}")
    if booking.price_total is not None:
        lines.append(f"Предварительно: {booking.price_total} ₽")
    if booking.deposit_amount is not None:
        lines.append(f"Залог: {booking.deposit_amount} ₽")
    if booking.payload.get("quote_provisional"):
        lines.append("⚠️ Часть сумм ориентировочная — подтвердите вручную")
    if booking.payload.get("quote_explanation"):
        lines.append(str(booking.payload["quote_explanation"]))
    return "\n".join(lines)


def format_client_status(booking: BookingRecord, catalog: Catalog) -> str:
    unit = catalog.get_accommodation(booking.unit_id) if booking.unit_id else None
    place = unit.name if unit else "ручной подбор"
    return (
        f"Заявка {booking.id}\n"
        f"Статус: {booking.status.value}\n"
        f"Даты: {booking.date_from} → {booking.date_to}\n"
        f"Место: {place}\n"
        f"Сумма: {booking.price_total or '—'} ₽\n"
        f"Залог: {booking.deposit_amount or '—'} ₽"
    )
