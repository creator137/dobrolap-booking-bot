from datetime import date
from pathlib import Path

from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.enums import FeedingOption, PetKind
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.services.pricing import PricingService

ROOT = Path(__file__).resolve().parents[1]


def test_same_cage_rats_add_100_per_extra_day():
    catalog = load_catalog(ROOT / "config")
    unit = catalog.get_accommodation("small_animals_balcony")
    pets = [PetProfile(kind=PetKind.RAT, name="А"), PetProfile(kind=PetKind.RAT, name="Б")]
    quote = PricingService(catalog).quote(
        pets=pets,
        unit=unit,
        date_from=date(2026, 10, 10),
        date_to=date(2026, 10, 18),
        together=True,
        feeding=FeedingOption.OWNER_FOOD,
    )
    assert quote.total_rub == 650 * 8 + 100 * 8
    assert not any(line.scope.value == "discount" for line in quote.lines)
    assert "+100" in quote.explanation or "одной клетке" in quote.explanation


def test_different_cages_rats_get_fifty_percent():
    catalog = load_catalog(ROOT / "config")
    unit = catalog.get_accommodation("small_animals_balcony")
    pets = [PetProfile(kind=PetKind.RAT, name="А"), PetProfile(kind=PetKind.RAT, name="Б")]
    quote = PricingService(catalog).quote(
        pets=pets,
        unit=unit,
        date_from=date(2026, 10, 10),
        date_to=date(2026, 10, 18),
        together=False,
        feeding=FeedingOption.OWNER_FOOD,
    )
    assert quote.total_rub == 7800
    assert any(line.amount_rub == -2600 for line in quote.lines)


def test_ferret_in_catalog_and_keyboard():
    from dobrolap_bot.bot.helpers import KIND_MAP
    from dobrolap_bot.bot.keyboards import pet_kind_kb

    catalog = load_catalog(ROOT / "config")
    assert KIND_MAP["хорёк"] == PetKind.FERRET
    labels = [b.text for row in pet_kind_kb().keyboard for b in row]
    assert "Хорёк" in labels
    unit = catalog.get_accommodation("small_animals_balcony")
    assert PetKind.FERRET in unit.allowed_species
    quote = PricingService(catalog).quote(
        pets=[PetProfile(kind=PetKind.FERRET, name="Фокс")],
        unit=unit,
        date_from=date(2026, 10, 10),
        date_to=date(2026, 10, 11),
        feeding=FeedingOption.OWNER_FOOD,
    )
    assert quote.total_rub == 650
