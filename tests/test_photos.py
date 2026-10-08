from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from dobrolap_bot.bot.handlers import _run_placement
from dobrolap_bot.config.loader import Catalog, load_catalog
from dobrolap_bot.domain.enums import PetKind
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.integrations.google_sheets import InMemorySheetsGateway, SheetBooking
from dobrolap_bot.services.booking import BookingService

ROOT = Path(__file__).resolve().parents[1]


class FakeState:
    def __init__(self, pet):
        self.data = {
            "pets": [pet.model_dump(mode="json")],
            "date_from": "2026-11-10", "date_to": "2026-11-12",
        }
        self.current = None

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, state):
        self.current = state


class FakeMessage:
    def __init__(self):
        self.media = []
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)

    async def answer_media_group(self, media):
        self.media.append(media)


def one_unit_catalog(unit_id):
    original = load_catalog(ROOT / "config")
    return Catalog(
        accommodations=[original.get_accommodation(unit_id)],
        daily_rates=original.daily_rates,
        services=original.services,
        price_rules=original.price_rules,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "weight", "expected", "excluded"),
    [
        (PetKind.CAT, None, "24-standard-m-cat.png", "25-standard-m-dog.png"),
        (PetKind.DOG, 12, "25-standard-m-dog.png", "24-standard-m-cat.png"),
    ],
)
async def test_client_gets_species_photo_for_suitable_standard_m(kind, weight, expected, excluded):
    catalog = one_unit_catalog("standard_m")
    sheets = InMemorySheetsGateway()
    service = BookingService(repo=None, catalog=catalog, sheets=sheets)
    message, state = FakeMessage(), FakeState(
        PetProfile(kind=kind, name="Питомец", weight_kg=weight, vaccinated=True, parasite_treated=True)
    )
    await _run_placement(message, state, catalog, sheets, service, ROOT / "assets")
    paths = [str(item.media.path) for group in message.media for item in group]
    assert any(expected in path for path in paths)
    assert not any(excluded in path for path in paths)


@pytest.mark.asyncio
async def test_outdoor_photo_only_when_exact_enclosure_two_is_free():
    catalog = one_unit_catalog("outdoor_comfort")
    pet = PetProfile(kind=PetKind.DOG, name="Пёс", weight_kg=15, vaccinated=True, parasite_treated=True)
    label_two = "Уличный Вольер Комфорт для собак 2"
    for occupied_two in (False, True):
        rows = [SheetBooking("other", label_two, date(2026, 11, 10), date(2026, 11, 12), "CONFIRMED")] if occupied_two else []
        sheets = InMemorySheetsGateway(rows)
        service = BookingService(repo=None, catalog=catalog, sheets=sheets)
        message, state = FakeMessage(), FakeState(pet)
        await _run_placement(message, state, catalog, sheets, service, ROOT / "assets")
        paths = [str(item.media.path) for group in message.media for item in group]
        assert any("23-outdoor-enclosure-2.png" in path for path in paths) is not occupied_two
        if not occupied_two:
            assert state.data["offered_sheet_labels"]["outdoor_comfort"] == label_two


@pytest.mark.asyncio
async def test_house_photo_only_for_prebathroom_not_other_house_room():
    catalog = one_unit_catalog("vip_plus_house_reserve")
    pet = PetProfile(kind=PetKind.CAT, name="Кот", vaccinated=True, parasite_treated=True)
    for occupied_prebathroom in (False, True):
        rows = [SheetBooking("other", "Домик педбанник", date(2026, 11, 10), date(2026, 11, 12), "CONFIRMED")] if occupied_prebathroom else []
        sheets = InMemorySheetsGateway(rows)
        service = BookingService(repo=None, catalog=catalog, sheets=sheets)
        message, state = FakeMessage(), FakeState(pet)
        await _run_placement(message, state, catalog, sheets, service, ROOT / "assets")
        paths = [str(item.media.path) for group in message.media for item in group]
        assert any("20-house-prebathroom.png" in path for path in paths) is not occupied_prebathroom


@pytest.mark.asyncio
async def test_economy_cat_receives_both_provided_views():
    catalog = one_unit_catalog("economy")
    sheets = InMemorySheetsGateway()
    service = BookingService(repo=None, catalog=catalog, sheets=sheets)
    message, state = FakeMessage(), FakeState(PetProfile(kind=PetKind.CAT, name="Кот"))
    await _run_placement(message, state, catalog, sheets, service, ROOT / "assets")
    paths = [str(item.media.path) for group in message.media for item in group]
    assert any("21-economy-cat-furnished.png" in path for path in paths)
    assert any("22-economy-cat-empty.png" in path for path in paths)


def test_all_catalog_photos_exist_and_uncertain_images_are_not_shown():
    catalog = load_catalog(ROOT / "config")
    all_paths = []
    for unit in catalog.accommodations:
        all_paths.extend(unit.photo_paths)
        all_paths.extend(path for group in unit.photo_paths_by_species.values() for path in group)
        all_paths.extend(path for group in unit.photo_paths_by_sheet_label.values() for path in group)
    assert all((ROOT / path).is_file() for path in all_paths)
    assert not any("04-unknown" in path or "18-unknown" in path for path in all_paths)
