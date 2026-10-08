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
    assert pricing.find_active_promo("DOBROLAP5", date_from=date(2026, 10, 10)) is None


def test_promo_discount_when_rule_active(pricing, catalog):
    unit = catalog.get_accommodation("comfort")
    pet = PetProfile(kind=PetKind.DOG, name="Биби", weight_kg=6)
    # Temporarily activate first discount rule for the assertion
    rule = next(r for r in catalog.price_rules if r.id == "promo_5pct_2026")
    rule.active = True
    try:
        assert pricing.find_active_promo(
            "dobrolap5", date_from=date(2026, 10, 10)
        ) is rule
        q = pricing.quote(
            pets=[pet],
            unit=unit,
            date_from=date(2026, 10, 10),
            date_to=date(2026, 10, 12),
            promo_code="DOBROLAP5",
            promo_eligible=True,
        )
        base = 1900 * 2
        discount = -int(round(base * 0.05))
        assert q.total_rub == base + discount
        assert any(ln.scope == PriceScope.DISCOUNT for ln in q.lines)
    finally:
        rule.active = False


def test_extra_service_price_is_set_by_operator(pricing, catalog):
    unit = catalog.get_accommodation("comfort")
    pet = PetProfile(kind=PetKind.DOG, name="Биби", weight_kg=6)
    q = pricing.quote(
        pets=[pet],
        unit=unit,
        date_from=date(2026, 10, 10),
        date_to=date(2026, 10, 13),
        service_ids=["med_care"],
    )
    assert q.total_rub == 1900 * 3
    assert q.provisional
    service_line = next(line for line in q.lines if line.scope == PriceScope.SERVICE)
    assert service_line.amount_rub == 0 and service_line.provisional


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


def test_confirmed_pdf_prices_and_missing_puppy_tariff(pricing, catalog):
    start, end = date(2026, 10, 10), date(2026, 10, 11)
    kitten = PetProfile(kind=PetKind.CAT, name="Котёнок", age_months=3, is_puppy_or_kitten=True)
    assert pricing.quote(pets=[kitten], unit=catalog.get_accommodation("economy"),
                         date_from=start, date_to=end).total_rub == 750
    medium_puppy = PetProfile(kind=PetKind.DOG, name="Щенок", weight_kg=15,
                              age_months=4, is_puppy_or_kitten=True)
    assert pricing.quote(pets=[medium_puppy], unit=catalog.get_accommodation("standard_m"),
                         date_from=start, date_to=end).total_rub == 1750
    assert pricing.quote(pets=[medium_puppy], unit=catalog.get_accommodation("vip_plus_house_reserve"),
                         date_from=start, date_to=end).total_rub == 2400
    mini_puppy = medium_puppy.model_copy(update={"weight_kg": 5})
    quote = pricing.quote(pets=[mini_puppy], unit=catalog.get_accommodation("standard_l"),
                          date_from=start, date_to=end)
    assert quote.provisional and quote.total_rub == 0


def test_spreadsheet_under_one_month_vip_only(pricing, catalog):
    start, end = date(2026, 10, 10), date(2026, 10, 11)
    puppy = PetProfile(kind=PetKind.DOG, name="Щенок", age_months=0,
                       weight_kg=6, is_puppy_or_kitten=True)
    kitten = PetProfile(kind=PetKind.CAT, name="Котёнок", age_months=0,
                        is_puppy_or_kitten=True)
    vip = catalog.get_accommodation("vip_plus_house_reserve")
    assert pricing.quote(pets=[puppy], unit=vip, date_from=start, date_to=end).total_rub == 2600
    assert pricing.quote(pets=[kitten], unit=vip, date_from=start, date_to=end).total_rub == 1500
    assert pricing.quote(pets=[kitten], unit=catalog.get_accommodation("economy"),
                         date_from=start, date_to=end).provisional


def test_owner_confirmed_weight_boundaries(pricing, catalog):
    assert PetProfile(kind=PetKind.DOG, name="A", weight_kg=9.9).dog_size.value == "miniature"
    assert PetProfile(kind=PetKind.DOG, name="A", weight_kg=10).dog_size.value == "miniature"
    assert PetProfile(kind=PetKind.DOG, name="A", weight_kg=10.1).dog_size.value == "medium"
    assert PetProfile(kind=PetKind.DOG, name="A", weight_kg=19.9).dog_size.value == "medium"
    assert PetProfile(kind=PetKind.DOG, name="A", weight_kg=20).dog_size.value == "large"
    pet = PetProfile(kind=PetKind.DOG, name="Пёс", weight_kg=22)
    quote = pricing.quote(pets=[pet], unit=catalog.get_accommodation("comfort"),
                          date_from=date(2026, 10, 10), date_to=date(2026, 10, 11))
    assert quote.total_rub == 2100


def test_group_price_applies_confirmed_fifty_percent_discount(pricing, catalog):
    pets = [
        PetProfile(kind=PetKind.DOG, name="A", weight_kg=6),
        PetProfile(kind=PetKind.DOG, name="B", weight_kg=6),
        PetProfile(kind=PetKind.DOG, name="C", weight_kg=6),
    ]
    quote = pricing.quote(
        pets=pets, unit=catalog.get_accommodation("comfort"),
        date_from=date(2026, 10, 10), date_to=date(2026, 10, 12),
    )
    assert quote.total_rub == 7600 and not quote.provisional
    discounts = [line for line in quote.lines if line.scope == PriceScope.DISCOUNT]
    assert [line.amount_rub for line in discounts] == [-1900, -1900]
    assert "50%" in quote.explanation


def test_separate_kitchen_room_has_no_unconfirmed_home_rate(pricing, catalog):
    pet = PetProfile(kind=PetKind.DOG, name="Пёс", weight_kg=6)
    quote = pricing.quote(
        pets=[pet], unit=catalog.get_accommodation("house_kitchen"),
        date_from=date(2026, 10, 10), date_to=date(2026, 10, 11),
    )
    assert quote.total_rub == 0 and quote.provisional
    assert not quote.has_accommodation_amount
