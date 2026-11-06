from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dobrolap_bot.bot.handlers import set_pet_neutered, set_promo, PROMO_ASK
from dobrolap_bot.bot.keyboards import pet_kind_kb, promo_choice_kb
from dobrolap_bot.bot.presentation import format_draft_summary
from dobrolap_bot.bot.states import BookingForm
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.enums import PetKind
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.services.pricing import PricingService

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
    return SimpleNamespace(
        text=text,
        photo=None,
        document=None,
        answer=AsyncMock(),
        from_user=SimpleNamespace(id=1),
    )


@pytest.mark.asyncio
async def test_neutered_female_skips_heat_question():
    state = State(draft_sex="женский")
    msg = message("Да")
    await set_pet_neutered(msg, state)
    assert state.data["draft_neutered"] is True
    assert state.data["draft_heat"] is False
    assert state.current == BookingForm.pet_age


@pytest.mark.asyncio
async def test_intact_female_asks_heat():
    state = State(draft_sex="женский")
    msg = message("Нет")
    await set_pet_neutered(msg, state)
    assert state.data["draft_neutered"] is False
    assert state.current == BookingForm.pet_heat


def test_grooming_pet_kind_kb_only_dog_and_cat():
    labels = [btn.text for row in pet_kind_kb(dogs_and_cats_only=True).keyboard for btn in row]
    assert labels == ["Собака", "Кошка"]


def test_promo_choice_kb_has_review_option():
    labels = [btn.text for row in promo_choice_kb().keyboard for btn in row]
    assert "Нет промокода / акций" in labels
    assert "Есть промокод" in labels
    assert "Скидка за отзыв (после проверки)" in labels
    assert "после проверки" in PROMO_ASK.lower() or "скидк" in PROMO_ASK.lower()


@pytest.mark.asyncio
async def test_promo_review_button_requests_screenshot(catalog=None):
    catalog = load_catalog(ROOT / "config")
    state = State()
    msg = message("Скидка за отзыв (после проверки)")
    await set_promo(msg, state, catalog, booking_service=SimpleNamespace())
    assert state.current == BookingForm.review_proof
    assert "скриншот" in msg.answer.call_args.args[0].lower()


def test_draft_summary_shows_price_with_and_without_discount():
    from datetime import date

    catalog = load_catalog(ROOT / "config")
    pets = [
        PetProfile(kind=PetKind.DOG, name="Ох", weight_kg=6),
        PetProfile(kind=PetKind.DOG, name="Щен", weight_kg=6),
    ]
    quote = PricingService(catalog).quote(
        pets=pets,
        unit=catalog.get_accommodation("comfort"),
        date_from=date(2026, 10, 10),
        date_to=date(2026, 10, 18),
    )
    text = format_draft_summary(
        data={
            "date_from": "2026-10-10",
            "date_to": "2026-10-18",
            "unit_id": "comfort",
            "customer_contact": "+7000",
            "feeding": "owner_food",
            "placement_together": True,
            "review_discount_claim": True,
        },
        pets=pets,
        catalog=catalog,
        quote=quote,
    )
    assert "без скидки" in text.lower()
    assert "со скидкой" in text.lower()
    assert "₽/сут" in text
    assert "после проверки" in text.lower()
