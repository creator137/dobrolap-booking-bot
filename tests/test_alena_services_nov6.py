from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dobrolap_bot.bot import handlers as h
from dobrolap_bot.bot.keyboards import pet_kind_kb, service_location_kb, trainer_program_kb
from dobrolap_bot.bot.presentation import (
    _service_location_text,
    _service_visit_dates_text,
    _trainer_program_text,
    format_draft_summary,
)
from dobrolap_bot.bot.states import BookingForm
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.enums import PetKind
from dobrolap_bot.domain.models import PetProfile

ROOT = Path(__file__).resolve().parents[1]


class State:
    def __init__(self, **data):
        self.data = data
        self.current = None

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, state):
        self.current = state


def message(text):
    return SimpleNamespace(text=text, answer=AsyncMock(), answer_photo=AsyncMock())


def test_menu_has_zoopsych_and_trainer_programs():
    labels = [b.text for row in service_location_kb().keyboard for b in row]
    assert "Кинолог (собаки)" in labels
    assert "Зоопсихолог (кошки)" in labels
    assert "Выгул (собаки)" in labels
    assert "МедУход" not in labels
    programs = [b.text for row in trainer_program_kb().keyboard for b in row]
    assert "Коррекция проблемного поведения" in programs
    assert "Курс «Управляемая городская собака»" in programs
    assert "Адаптация собаки из приюта" in programs


def test_walk_and_trainer_pet_kind_dogs_only():
    assert [b.text for row in pet_kind_kb(dogs_only=True).keyboard for b in row] == ["Собака"]
    assert [b.text for row in pet_kind_kb(cats_only=True).keyboard for b in row] == ["Кошка"]


@pytest.mark.asyncio
async def test_trainer_asks_hotel_or_client_address():
    catalog = load_catalog(ROOT / "config")
    state = State(service_only=True)
    msg = message("Кинолог (собаки)")
    await h.set_service_location(msg, state, ROOT / "assets", catalog)
    assert state.current == BookingForm.service_place
    assert state.data["service_category"] == "trainer"
    assert "зоогостиницы" in msg.answer.call_args.args[0].lower()

    await h.set_service_place(message("Адрес зоогостиницы"), state, catalog)
    assert state.data["service_address"] == h.HOTEL_ADDRESS
    assert state.data["service_location"] == "hotel"
    assert state.current == BookingForm.trainer_program

    await h.set_trainer_program(message("Обучение командам"), state, catalog)
    assert state.data["trainer_program"] == "commands"
    assert state.current == BookingForm.service_date


@pytest.mark.asyncio
async def test_trainer_client_address_then_program():
    catalog = load_catalog(ROOT / "config")
    state = State(service_only=True)
    await h.set_service_location(message("Кинолог (собаки)"), state, ROOT / "assets", catalog)
    await h.set_service_place(message("Ваш адрес"), state, catalog)
    assert state.current == BookingForm.service_address
    await h.set_service_address(message("ул. Ленина, 1"), state, catalog)
    assert state.data["service_address"] == "ул. Ленина, 1"
    assert state.current == BookingForm.trainer_program


@pytest.mark.asyncio
async def test_walk_allows_date_range():
    state = State(service_only=True, service_category="walk")
    msg = message("10.11.2027 - 15.11.2027")
    await h.set_service_date(msg, state)
    assert state.data["date_from"] == "2027-11-10"
    assert state.data["date_to"] == "2027-11-15"
    assert state.current == BookingForm.service_time


@pytest.mark.asyncio
async def test_grooming_stays_single_day():
    state = State(service_only=True, service_category="grooming")
    await h.set_service_date(message("10.11.2027"), state)
    assert state.data["date_from"] == "2027-11-10"
    assert state.data["date_to"] == "2027-11-11"
    assert state.current == BookingForm.service_time


@pytest.mark.asyncio
async def test_walk_rejects_cat():
    state = State(service_only=True, service_category="walk")
    msg = message("Кошка")
    await h.set_pet_kind(msg, state)
    assert "только для собак" in msg.answer.call_args.args[0].lower()
    assert "draft_kind" not in state.data


@pytest.mark.asyncio
async def test_zoopsych_cats_only_flow():
    catalog = load_catalog(ROOT / "config")
    state = State(service_only=True)
    await h.set_service_location(message("Зоопсихолог (кошки)"), state, ROOT / "assets", catalog)
    assert state.data["service_category"] == "zoopsych"
    assert state.current == BookingForm.service_place
    await h.set_service_place(message("Адрес зоогостиницы"), state, catalog)
    assert state.current == BookingForm.service_date  # no trainer program
    pets = [PetProfile(kind=PetKind.CAT, name="Мурка")]
    ids = {s.id for s in h._available_services(catalog, pets, service_only=True, service_category="zoopsych")}
    assert ids == {"zoopsychologist"}


@pytest.mark.asyncio
async def test_mixed_together_shows_priced_orientation_not_zero():
    from datetime import date
    from dobrolap_bot.services.placement import PlacementService
    from dobrolap_bot.services.pricing import PricingService
    from dobrolap_bot.domain.enums import FeedingOption

    catalog = load_catalog(ROOT / "config")
    cat = PetProfile(kind=PetKind.CAT, name="О", weight_kg=3, vaccinated=True, parasite_treated=True)
    dog = PetProfile(kind=PetKind.DOG, name="Собака", weight_kg=3, vaccinated=True, parasite_treated=True)
    result = PlacementService(catalog).suggest([cat, dog], tariff_kind="comfort")
    assert result.candidates
    assert all(c.requires_owner_review for c in result.candidates)
    assert "mixed_species_together_request" in result.owner_flags

    quote = PricingService(catalog).quote(
        pets=[cat, dog],
        unit=catalog.get_accommodation("comfort"),
        date_from=date(2026, 11, 27),
        date_to=date(2026, 11, 30),
        together=True,
        feeding=FeedingOption.OWNER_FOOD,
        room_assignments=[
            {"pet_indices": [0, 1], "unit_id": None, "sheet_label": None, "manual": True}
        ],
    )
    assert quote.total_rub > 0
    assert "со скидкой" in quote.explanation
    text = format_draft_summary(
        data={
            "date_from": "2026-11-27",
            "date_to": "2026-11-30",
            "unit_id": None,
            "customer_contact": "+7",
            "feeding": "owner_food",
            "placement_together": True,
            "room_assignments": [
                {"pet_indices": [0, 1], "unit_id": None, "manual": True}
            ],
            "tariff_choice": "comfort",
        },
        pets=[cat, dog],
        catalog=catalog,
        quote=quote,
    )
    assert "≈ 0 ₽/сут" not in text
    assert "1900 ₽/сут" in text or "₽/сут" in text
    assert "без скидки" in text.lower()
    assert "Предварительная стоимость проживания: 0 ₽" not in text


@pytest.mark.asyncio
async def test_needs_treatment_preselects_medcare_for_boarding():
    from dobrolap_bot.domain.models import BehaviorFlags

    catalog = load_catalog(ROOT / "config")
    pet = PetProfile(
        kind=PetKind.DOG,
        name="Бобик",
        weight_kg=8,
        behavior=BehaviorFlags(needs_treatment=True),
    )
    state = State(service_only=False, pets=[pet.model_dump(mode="json")], service_ids=[])
    msg = message("")
    await h._ask_services(msg, state, catalog)
    assert "med_care" in state.data["service_ids"]
    answered = " ".join(c.args[0] for c in msg.answer.call_args_list if c.args)
    assert "МедУход" in answered


def test_summary_shows_program_and_period():
    catalog = load_catalog(ROOT / "config")
    data = {
        "service_only": True,
        "date_from": "2027-11-10",
        "date_to": "2027-11-15",
        "arrival_time": "14:00",
        "service_address": h.HOTEL_ADDRESS,
        "service_location": "hotel",
        "service_category": "trainer",
        "trainer_program": "city_dog",
        "trainer_program_label": "Курс «Управляемая городская собака»",
        "customer_contact": "+7000",
        "service_ids": ["dog_trainer"],
    }
    text = format_draft_summary(
        data=data,
        pets=[PetProfile(kind=PetKind.DOG, name="Бобик", weight_kg=10)],
        catalog=catalog,
        quote=None,
    )
    assert "Период услуги" in text
    assert "Программа кинолога" in text
    assert "Управляемая городская собака" in text
    assert _service_visit_dates_text(data).startswith("Период")
    assert "зоогостиницы" in _service_location_text(data).lower()
    assert "Управляемая" in (_trainer_program_text(data) or "")
