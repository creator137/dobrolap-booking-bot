from __future__ import annotations

from pathlib import Path

import pytest

from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.enums import PetKind
from dobrolap_bot.domain.models import BehaviorFlags, PetProfile
from dobrolap_bot.services.placement import PlacementService


@pytest.fixture(scope="module")
def catalog():
    root = Path(__file__).resolve().parents[1]
    return load_catalog(root / "config")


@pytest.fixture
def placement(catalog):
    return PlacementService(catalog)


def test_catalog_loads(catalog):
    assert len(catalog.accommodations) >= 10
    assert len(catalog.daily_rates) >= 20
    assert catalog.deposit_base_rub == 2000


def test_miniature_dog_gets_candidates(placement):
    pet = PetProfile(
        kind=PetKind.DOG,
        name="Биби",
        weight_kg=6,
        vaccinated=True,
        parasite_treated=True,
    )
    result = placement.suggest([pet])
    assert result.candidates
    ids = {c.accommodation.id for c in result.candidates}
    assert "premium_xxl" not in ids  # min weight 10
    assert "outdoor_comfort" not in ids


def test_unvaccinated_cat_only_vip(placement):
    pet = PetProfile(
        kind=PetKind.CAT,
        name="Мурка",
        vaccinated=False,
        parasite_treated=True,
    )
    result = placement.suggest([pet])
    assert result.candidates
    assert all(c.accommodation.tariff_kind in {"vip", "vip_plus"} for c in result.candidates)


def test_stressed_cat_only_vip(placement):
    pet = PetProfile(
        kind=PetKind.CAT,
        name="Тень",
        vaccinated=True,
        parasite_treated=True,
        behavior=BehaviorFlags(high_stress=True),
    )
    result = placement.suggest([pet])
    assert result.candidates
    assert all(c.accommodation.tariff_kind in {"vip", "vip_plus"} for c in result.candidates)


def test_elderly_dog_prioritizes_workshop(placement):
    pet = PetProfile(
        kind=PetKind.DOG,
        name="Бобик",
        weight_kg=12,
        vaccinated=True,
        parasite_treated=True,
        behavior=BehaviorFlags(elderly=True),
    )
    result = placement.suggest([pet])
    assert result.candidates
    assert result.candidates[0].accommodation.id == "first_floor_workshop"


def test_occupied_units_filtered(placement):
    pet = PetProfile(
        kind=PetKind.DOG,
        name="Рекс",
        weight_kg=8,
        vaccinated=True,
        parasite_treated=True,
    )
    free = placement.suggest([pet])
    occupied_id = free.candidates[0].accommodation.id
    filtered = placement.suggest([pet], occupied_unit_ids={occupied_id})
    assert all(c.accommodation.id != occupied_id for c in filtered.candidates)


def test_multi_pet_flags_manual(placement):
    pets = [
        PetProfile(kind=PetKind.DOG, name="А", weight_kg=5, vaccinated=True, parasite_treated=True),
        PetProfile(kind=PetKind.DOG, name="Б", weight_kg=6, vaccinated=True, parasite_treated=True),
    ]
    result = placement.suggest(pets)
    assert "multi_pet_group" in result.owner_flags
    assert result.requires_manual_matching
