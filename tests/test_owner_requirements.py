from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dobrolap_bot.bot.handlers import _available_services, cal_day, set_placement_groups
from dobrolap_bot.bot.helpers import parse_single_date
from dobrolap_bot.bot.presentation import format_draft_summary
from dobrolap_bot.bot.states import BookingForm
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.enums import PetKind
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.integrations.google_sheets import InMemorySheetsGateway
from dobrolap_bot.repositories.sqlite import SqliteRepository
from dobrolap_bot.services.booking import BookingService
from dobrolap_bot.services.placement import PlacementService
from dobrolap_bot.services.pricing import PricingService


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def catalog():
    return load_catalog(ROOT / "config")


def dog(weight=6, **kwargs):
    return PetProfile(kind=PetKind.DOG, name="Пёс", weight_kg=weight, vaccinated=True, parasite_treated=True, **kwargs)


def offered(catalog, pets):
    return {candidate.accommodation.id for candidate in PlacementService(catalog).suggest(pets, limit=100).candidates}


def test_house_species_and_fallback_order(catalog):
    cat = PetProfile(kind=PetKind.CAT, name="Кошка")
    assert "vip_plus_house_reserve" not in offered(catalog, [cat])
    assert "house_kitchen" not in offered(catalog, [cat])
    assert "seasonal_vip_under_stairs" not in offered(catalog, [cat])
    assert "house_second_floor" in offered(catalog, [cat])
    assert "house_second_floor" not in offered(catalog, [dog(11)])
    assert {"house_kitchen", "seasonal_vip_under_stairs"}.issubset(offered(catalog, [dog()]))
    result = PlacementService(catalog).suggest([dog()], limit=100)
    assert result.candidates[-1].score <= -100


@pytest.mark.parametrize("weight,allowed", [(10, False), (10.1, True), (30, True)])
def test_reinforced_enclosure_rejects_small_dogs(catalog, weight, allowed):
    assert ("premium_xxl" in offered(catalog, [dog(weight)])) is allowed


@pytest.mark.parametrize("unit_id,count,weight,allowed", [
    ("comfort", 2, 20, True), ("comfort", 2, 20.1, False),
    ("comfort", 3, 6, False), ("comfort_plus", 2, 25, True),
    ("comfort_plus", 3, 15, True), ("comfort_plus", 3, 15.1, False),
    ("standard_m", 3, 10, True), ("standard_l", 4, 10, False),
    ("standard_l", 1, 11, False), ("optimal_s", 2, 6, False),
])
def test_dog_capacity(catalog, unit_id, count, weight, allowed):
    assert (unit_id in offered(catalog, [dog(weight) for index in range(count)])) is allowed


@pytest.mark.parametrize("unit_id,count,allowed", [("comfort", 4, True), ("comfort", 5, False), ("comfort_plus", 6, True), ("comfort_plus", 7, False), ("economy", 2, False)])
def test_cat_capacity(catalog, unit_id, count, allowed):
    assert (unit_id in offered(catalog, [PetProfile(kind=PetKind.CAT, name="Кошка", weight_kg=5) for index in range(count)])) is allowed


def test_heat_only_private_room_and_alone(catalog):
    pet = dog(in_heat=True, sex="женский", neutered=False)
    candidates = PlacementService(catalog).suggest([pet], limit=100).candidates
    assert candidates and all("private" in item.accommodation.features for item in candidates)
    assert not offered(catalog, [pet, dog()])


@pytest.mark.parametrize("kind", [PetKind.RABBIT, PetKind.RAT, PetKind.HAMSTER, PetKind.GUINEA_PIG])
def test_rodents_only_photo_room(catalog, kind):
    assert offered(catalog, [PetProfile(kind=kind, name="Питомец")]) == {"small_animals_balcony"}


def test_services_for_boarding_and_visits(catalog):
    pets = [dog(), PetProfile(kind=PetKind.CAT, name="Кошка")]
    excluded = {"walk", "dogsitter", "cat_nanny"}
    assert not excluded & {service.id for service in _available_services(catalog, pets)}
    assert "walk" not in {service.id for service in _available_services(catalog, pets, service_only=True)}
    assert "walk" in {service.id for service in _available_services(catalog, [dog()], service_only=True)}


@pytest.mark.parametrize("text,expected", [("01.11.2026.", date(2026, 11, 1)), ("31.11.2026", None), ("29.02.2028.", date(2028, 2, 29)), ("29.02.2026", None)])
def test_single_dates(text, expected):
    assert parse_single_date(text) == expected


class State:
    def __init__(self, **data):
        self.data = data
        self.current = None

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, value):
        self.current = value


@pytest.mark.asyncio
async def test_service_calendar_picks_one_date():
    state = State(service_only=True)
    callback = SimpleNamespace(data="cal:day:2099-11-20", answer=AsyncMock(), message=SimpleNamespace(answer=AsyncMock(), edit_reply_markup=AsyncMock()))
    await cal_day(callback, state)
    assert state.data["date_from"] == "2099-11-20"
    assert state.data["date_to"] == "2099-11-21"
    assert state.current == BookingForm.service_time


@pytest.mark.asyncio
async def test_invalid_partial_groups_do_not_advance(catalog):
    state = State(pets=[dog().model_dump(mode="json") for index in range(3)])
    message = SimpleNamespace(text="1,2;2", answer=AsyncMock())
    await set_placement_groups(message, state, catalog, None, None, ROOT / "assets")
    assert "placement_groups" not in state.data


def assignments(catalog):
    return [
        {"pet_indices": [0, 1], "unit_id": "comfort", "sheet_label": catalog.get_accommodation("comfort").calendar_labels()[0]},
        {"pet_indices": [2], "unit_id": "comfort_plus", "sheet_label": catalog.get_accommodation("comfort_plus").calendar_labels()[0]},
    ]


def test_partial_prices_discounts_and_summary(catalog):
    pets = [dog() for index in range(3)]
    rooms = assignments(catalog)
    quote = PricingService(catalog).quote(pets=pets, unit=catalog.get_accommodation("comfort"), date_from=date(2026, 11, 1), date_to=date(2026, 12, 1), room_assignments=rooms)
    subtotal = (1900 + 950 + 1365) * 30
    assert quote.total_rub == subtotal - round(2850 * 30 * 0.15) - round(1365 * 30 * 0.15)
    text = format_draft_summary(data={"date_from": "2026-11-01", "date_to": "2026-12-01", "unit_id": "comfort", "room_assignments": rooms}, pets=pets, catalog=catalog, quote=quote)
    assert "Комфорт+" in text
    assert "От 30 суток" in text
    assert "50%" in text and "30%" in text


@pytest.mark.asyncio
async def test_multiple_room_lifecycle(tmp_path, catalog):
    repo = SqliteRepository(tmp_path / "booking.db")
    await repo.open()
    try:
        service = BookingService(repo=repo, catalog=catalog, sheets=InMemorySheetsGateway())
        booking, quote = await service.submit_booking(telegram_user_id=123, customer_name="Тест", username=None, consent_at=None, date_from=date(2026, 11, 1), date_to=date(2026, 12, 1), pets=[dog() for index in range(3)], unit_id="comfort", feeding=None, service_ids=[], placement_flags=[], manual_matching=False, room_assignments=assignments(catalog), placement_together=False)
        assert quote.total_rub > 0
        await service.approve(booking.id)
        assert len(service.sheets.list_bookings()) == 2
        await service.confirm_payment(booking.id)
        assert all(row.status == "CONFIRMED" for row in service.sheets.list_bookings())
        await service.cancel(booking.id)
        assert not service.sheets.list_bookings()
    finally:
        await repo.close()
