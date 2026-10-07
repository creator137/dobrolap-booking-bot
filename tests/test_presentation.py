from datetime import date, datetime, timezone
from pathlib import Path

from dobrolap_bot.bot.handlers import _available_services
from dobrolap_bot.bot.keyboards import behavior_kb, owner_unit_choice_kb
from dobrolap_bot.bot.presentation import (
    feeding_label,
    format_client_status,
    format_owner_summary,
    pet_kind_label,
    placement_flag_label,
    status_label,
)
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.enums import BookingStatus, FeedingOption, PetKind
from dobrolap_bot.domain.models import BehaviorFlags, PetProfile
from dobrolap_bot.repositories.sqlite import BookingRecord


def _catalog():
    return load_catalog(Path(__file__).resolve().parents[1] / "config")


def _booking() -> BookingRecord:
    pet = PetProfile(
        kind=PetKind.DOG,
        name="Бим",
        age_months=30,
        breed="Корги",
        weight_kg=12.5,
        vaccinated=True,
        parasite_treated=True,
        behavior=BehaviorFlags(high_stress=True, loud_barking=True),
        health_notes="Нужны таблетки вечером",
        passport_file_ids=["photo-1", "photo-2"],
    )
    return BookingRecord(
        id="abc123",
        customer_id=1,
        date_from=date(2026, 11, 10),
        date_to=date(2026, 11, 13),
        status=BookingStatus.WAITING_OWNER,
        unit_id="comfort",
        price_total=6000,
        deposit_amount=2000,
        owner_note=None,
        sheet_external_id="abc123",
        payload={
            "pets": [pet.model_dump(mode="json")],
            "feeding": FeedingOption.HOTEL_RATION.value,
            "service_ids": ["nail_trim"],
            "promo_code": None,
            "placement_flags": ["needs_review:health_notes", "sheets_unavailable"],
            "client_username": "client",
            "customer_contact": "+79001234567",
        },
        customer_telegram_id=123,
        customer_name="Иван",
        customer_contact="+79001234567",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def test_all_public_labels_are_russian():
    assert status_label(BookingStatus.WAITING_OWNER) == "Ожидает решения владельца"
    assert pet_kind_label(PetKind.DOG) == "Собака"
    assert feeding_label(FeedingOption.HOTEL_RATION) == "Рацион зоогостиницы"
    assert "Google Sheets" in placement_flag_label("sheets_unavailable")


def test_owner_card_is_complete_and_hides_internal_values():
    text = format_owner_summary(_booking(), _catalog())
    for expected in (
        "Иван",
        "+79001234567",
        "10.11.2026 — 13.11.2026",
        "Собака — Бим",
        "2 года 6 мес.",
        "Корги",
        "12.5 кг",
        "Вакцинация: Да",
        "загружено фото — 2",
        "Нужны таблетки вечером",
        "Стрижка когтей",
        "Комфорт",
        "6 000 ₽",
    ):
        assert expected in text
    for leaked in (
        "WAITING_OWNER",
        "hotel_ration",
        "needs_review:health_notes",
        "sheets_unavailable",
        "comfort`",
    ):
        assert leaked not in text


def test_client_card_hides_internal_values():
    text = format_client_status(_booking(), _catalog())
    assert "Ожидает решения владельца" in text
    assert "Рацион зоогостиницы" in text
    assert "WAITING_OWNER" not in text
    assert "hotel_ration" not in text


def test_services_are_filtered_by_pet_species():
    catalog = _catalog()
    dog = PetProfile(kind=PetKind.DOG, name="Бим")
    cat = PetProfile(kind=PetKind.CAT, name="Мурка")
    dog_ids = {service.id for service in _available_services(catalog, [dog])}
    cat_ids = {service.id for service in _available_services(catalog, [cat])}
    assert "hygiene_complex_dog" in dog_ids
    assert "grooming_cat" not in dog_ids
    assert "grooming_cat" in cat_ids
    assert "dogsitter" not in cat_ids
    assert "natural_feeding" not in dog_ids


def test_behavior_and_owner_unit_keyboards_show_labels_not_ids():
    behavior = behavior_kb(PetKind.CAT, {"high_stress"})
    visible = [button.text for row in behavior.inline_keyboard for button in row]
    assert any("Сильный стресс" in text for text in visible)
    assert all("high_stress" not in text for text in visible)

    units = owner_unit_choice_kb("booking1", [("comfort_plus", "Комфорт+ — 5 000 ₽")])
    button = units.inline_keyboard[0][0]
    assert button.text == "Комфорт+ — 5 000 ₽"
    assert "comfort_plus" not in button.text
    assert button.callback_data == "ownunit:booking1:comfort_plus"
