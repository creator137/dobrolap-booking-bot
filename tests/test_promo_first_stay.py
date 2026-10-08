from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.enums import BookingStatus, PetKind, PriceScope
from dobrolap_bot.domain.models import PetProfile, PriceRule
from dobrolap_bot.integrations.google_sheets import InMemorySheetsGateway
from dobrolap_bot.repositories.sqlite import SqliteRepository
from dobrolap_bot.services.booking import BookingService
from dobrolap_bot.services.pricing import PricingService

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
async def service(tmp_path):
    repo = SqliteRepository(tmp_path / "promo.db")
    await repo.open()
    catalog = load_catalog(ROOT / "config")
    service = BookingService(repo=repo, catalog=catalog, sheets=InMemorySheetsGateway())
    yield service
    await repo.close()


async def submit(service, user_id, *, promo="ДОБРОЛАПКИ", contact=None):
    return await service.submit_booking(
        telegram_user_id=user_id, customer_name="Тест", username=None, consent_at=None,
        date_from=date(2026, 11, 10), date_to=date(2026, 11, 12),
        pets=[PetProfile(kind=PetKind.DOG, name="Биби", weight_kg=6)],
        unit_id="comfort", feeding=None, service_ids=[], placement_flags=[],
        manual_matching=False, promo_code=promo, customer_contact=contact,
    )


@pytest.mark.asyncio
async def test_promo_first_stay_and_history_after_cancel(service, monkeypatch):
    monkeypatch.setattr(PricingService, "promo_today", staticmethod(lambda: date(2026, 11, 1)))
    booking, quote = await submit(service, 901)
    assert quote.total_rub == 3610  # 2 × 1900 less 5%.
    assert booking.payload["promo_rule_id"] == "dobrolapki_first_stay_2026"
    with pytest.raises(ValueError, match="promo_not_first_placement"):
        await submit(service, 901)
    await service.approve(booking.id)
    await service.attach_receipt(booking.id, "receipt")
    await service.confirm_payment(booking.id)
    await service.cancel(booking.id)
    assert (await service.get(booking.id)).payload["ever_confirmed"] is True
    with pytest.raises(ValueError, match="promo_not_first_placement"):
        await submit(service, 901)


@pytest.mark.asyncio
async def test_rejected_unpaid_application_does_not_consume_promo(service, monkeypatch):
    monkeypatch.setattr(PricingService, "promo_today", staticmethod(lambda: date(2026, 10, 31)))
    booking, _ = await submit(service, 902)
    await service.reject(booking.id)
    next_booking, quote = await submit(service, 902)
    assert next_booking.status == BookingStatus.WAITING_OWNER
    assert quote.total_rub == 3610


@pytest.mark.asyncio
async def test_promo_expiry_is_redemption_date_inclusive(service, monkeypatch):
    monkeypatch.setattr(PricingService, "promo_today", staticmethod(lambda: date(2026, 11, 1)))
    assert (await submit(service, 903))[1].total_rub == 3610
    monkeypatch.setattr(PricingService, "promo_today", staticmethod(lambda: date(2026, 11, 2)))
    with pytest.raises(ValueError, match="promo_invalid_or_expired"):
        await submit(service, 904)


@pytest.mark.asyncio
async def test_same_phone_on_new_telegram_account_does_not_get_second_promo(service, monkeypatch):
    monkeypatch.setattr(PricingService, "promo_today", staticmethod(lambda: date(2026, 11, 1)))
    await submit(service, 905, contact="+79001234567")
    assert await service.repo.has_prior_placement_by_telegram(906, "+79001234567")
    with pytest.raises(ValueError, match="promo_not_first_placement"):
        await submit(service, 906, contact="+79001234567")


def test_promo_excludes_other_discount_rules():
    catalog = load_catalog(ROOT / "config")
    catalog.price_rules.append(PriceRule(
        id="other", scope=PriceScope.DISCOUNT, percent=10, priority=2, active=True,
    ))
    pricing = PricingService(catalog)
    quote = pricing.quote(
        pets=[PetProfile(kind=PetKind.DOG, name="Биби", weight_kg=6)],
        unit=catalog.get_accommodation("comfort"),
        date_from=date(2026, 11, 10), date_to=date(2026, 11, 12),
        promo_code="добролапки", promo_eligible=True, promo_at=date(2026, 11, 1),
    )
    discounts = [line for line in quote.lines if line.scope == PriceScope.DISCOUNT]
    assert len(discounts) == 1
    assert discounts[0].amount_rub == -190
