from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.enums import FeedingOption, PetKind, PriceScope
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.services.pricing import PricingService


@pytest.fixture(scope="module")
def catalog():
    root = Path(__file__).resolve().parents[1]
    return load_catalog(root / "config")


@pytest.fixture
def pricing(catalog):
    return PricingService(catalog)


def test_deposit_scaling(pricing):
    assert pricing.deposit_amount(1) == 2000
    assert pricing.deposit_amount(2) == 2500
    assert pricing.deposit_amount(3) == 3000


def test_dog_stay_quote(pricing, catalog):
    unit = catalog.get_accommodation("comfort")
    assert unit is not None
    pet = PetProfile(
        kind=PetKind.DOG,
        name="Биби",
        weight_kg=6,
        vaccinated=True,
        parasite_treated=True,
    )
    q = pricing.quote(
        pets=[pet],
        unit=unit,
        date_from=date(2026, 10, 10),
        date_to=date(2026, 10, 13),  # 3 nights
        feeding=FeedingOption.OWNER_FOOD,
    )
    # miniature comfort = 1900 * 3
    assert q.total_rub == 1900 * 3
    assert q.deposit_rub == 2000
    assert not q.provisional
    assert any(ln.scope == PriceScope.ACCOMMODATION for ln in q.lines)


def test_inactive_promo_not_applied(pricing, catalog):
    unit = catalog.get_accommodation("comfort")
    pet = PetProfile(kind=PetKind.DOG, name="Биби", weight_kg=6)
    q = pricing.quote(
        pets=[pet],
        unit=unit,
        date_from=date(2026, 10, 10),
        date_to=date(2026, 10, 12),
        promo_code="DOBROLAP5",
    )
    # Placeholder promo must stay inactive in config
    assert q.total_rub == 1900 * 2
    assert not any(ln.scope == PriceScope.DISCOUNT for ln in q.lines)


def test_promo_discount_when_rule_active(pricing, catalog):
    unit = catalog.get_accommodation("comfort")
    pet = PetProfile(kind=PetKind.DOG, name="Биби", weight_kg=6)
    # Temporarily activate first discount rule for the assertion
    rule = next(r for r in catalog.price_rules if r.id == "promo_5pct_2026")
    rule.active = True
    try:
        q = pricing.quote(
            pets=[pet],
            unit=unit,
            date_from=date(2026, 10, 10),
            date_to=date(2026, 10, 12),
            promo_code="DOBROLAP5",
        )
        base = 1900 * 2
        discount = -int(round(base * 0.05))
        assert q.total_rub == base + discount
        assert any(ln.scope == PriceScope.DISCOUNT for ln in q.lines)
    finally:
        rule.active = False


def test_med_care_per_day(pricing, catalog):
    unit = catalog.get_accommodation("comfort")
    pet = PetProfile(kind=PetKind.DOG, name="Биби", weight_kg=6)
    q = pricing.quote(
        pets=[pet],
        unit=unit,
        date_from=date(2026, 10, 10),
        date_to=date(2026, 10, 13),
        service_ids=["med_care"],
    )
    # med_care from 200 × 3 nights + 1900×3
    assert q.total_rub == 1900 * 3 + 200 * 3


def test_invalid_dates(pricing, catalog):
    unit = catalog.get_accommodation("comfort")
    pet = PetProfile(kind=PetKind.DOG, name="Биби", weight_kg=6)
    with pytest.raises(ValueError):
        pricing.quote(
            pets=[pet],
            unit=unit,
            date_from=date(2026, 10, 10),
            date_to=date(2026, 10, 10),
        )
