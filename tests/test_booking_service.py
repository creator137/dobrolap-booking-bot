from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.enums import BookingStatus, FeedingOption, PetKind
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.integrations.google_sheets import InMemorySheetsGateway, SheetBooking
from dobrolap_bot.repositories.sqlite import SqliteRepository
from dobrolap_bot.services.booking import BookingService, InvalidTransitionError
from dobrolap_bot.services.summary import format_owner_summary


@pytest.fixture
def catalog():
    root = Path(__file__).resolve().parents[1]
    return load_catalog(root / "config")


@pytest.fixture
async def booking_service(tmp_path, catalog):
    repo = SqliteRepository(tmp_path / "test.db")
    await repo.open()
    sheets = InMemorySheetsGateway()
    svc = BookingService(repo=repo, catalog=catalog, sheets=sheets)
    yield svc
    await repo.close()


def _pet() -> PetProfile:
    return PetProfile(
        kind=PetKind.DOG,
        name="Биби",
        weight_kg=6,
        vaccinated=True,
        parasite_treated=True,
    )


@pytest.mark.asyncio
async def test_full_happy_path(booking_service, catalog):
    booking, quote = await booking_service.submit_booking(
        telegram_user_id=111,
        customer_name="Тест",
        username="tester",
        consent_at=datetime.now(timezone.utc),
        date_from=date(2026, 11, 1),
        date_to=date(2026, 11, 4),
        pets=[_pet()],
        unit_id="comfort",
        feeding=FeedingOption.OWNER_FOOD,
        service_ids=["nail_trim"],
        placement_flags=[],
        manual_matching=False,
    )
    assert booking.status == BookingStatus.WAITING_OWNER
    assert quote is not None
    assert quote.total_rub > 0
    assert "Биби" in format_owner_summary(booking, catalog)

    booking = await booking_service.approve(booking.id)
    assert booking.status == BookingStatus.WAITING_PAYMENT
    assert booking.id in {r.external_id for r in booking_service.sheets.list_bookings()}

    booking = await booking_service.attach_receipt(booking.id, "file_receipt_1")
    assert "file_receipt_1" in booking.payload["receipt_file_ids"]

    booking = await booking_service.confirm_payment(booking.id)
    assert booking.status == BookingStatus.CONFIRMED


@pytest.mark.asyncio
async def test_approve_blocked_if_occupied(booking_service):
    booking, _ = await booking_service.submit_booking(
        telegram_user_id=222,
        customer_name="A",
        username=None,
        consent_at=None,
        date_from=date(2026, 12, 1),
        date_to=date(2026, 12, 5),
        pets=[_pet()],
        unit_id="comfort",
        feeding=FeedingOption.OWNER_FOOD,
        service_ids=[],
        placement_flags=[],
        manual_matching=False,
    )
    booking_service.sheets.upsert_booking(
        booking_id="other",
        unit_id="comfort",
        date_from=date(2026, 12, 2),
        date_to=date(2026, 12, 6),
        status="CONFIRMED",
    )
    with pytest.raises(ValueError, match="unit_occupied"):
        await booking_service.approve(booking.id)


@pytest.mark.asyncio
async def test_reject_and_suggest(booking_service, catalog):
    booking, _ = await booking_service.submit_booking(
        telegram_user_id=333,
        customer_name="B",
        username="b",
        consent_at=None,
        date_from=date(2026, 12, 10),
        date_to=date(2026, 12, 12),
        pets=[_pet()],
        unit_id="comfort",
        feeding=None,
        service_ids=[],
        placement_flags=["multi_pet_group"],
        manual_matching=False,
    )
    booking, quote = await booking_service.suggest_unit(booking.id, "comfort_plus")
    assert booking.unit_id == "comfort_plus"
    assert quote.total_rub > 0
    assert booking.status == BookingStatus.WAITING_OWNER

    booking = await booking_service.reject(booking.id, "нет мест")
    assert booking.status == BookingStatus.OWNER_REJECTED
    with pytest.raises(InvalidTransitionError):
        await booking_service.approve(booking.id)


@pytest.mark.asyncio
async def test_manual_booking_without_unit(booking_service):
    booking, quote = await booking_service.submit_booking(
        telegram_user_id=444,
        customer_name="C",
        username=None,
        consent_at=None,
        date_from=date(2026, 12, 20),
        date_to=date(2026, 12, 22),
        pets=[_pet()],
        unit_id=None,
        feeding=FeedingOption.OWNER_FOOD,
        service_ids=[],
        placement_flags=["no_matching_units"],
        manual_matching=True,
    )
    assert quote is None
    assert booking.deposit_amount == 2000
    booking = await booking_service.approve(booking.id)
    assert booking.status == BookingStatus.WAITING_PAYMENT
