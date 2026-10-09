from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from dobrolap_bot.bot.presentation import (
    admin_booking_button_title,
    format_admin_bookings_list,
    format_admin_clients,
    format_admin_overview,
    short_status_label,
)
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.enums import BookingStatus, FeedingOption, PetKind
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.integrations.google_sheets import InMemorySheetsGateway
from dobrolap_bot.repositories.sqlite import SqliteRepository
from dobrolap_bot.services.booking import BookingService


@pytest.fixture
def catalog():
    return load_catalog(Path(__file__).resolve().parents[1] / "config")


@pytest.fixture
async def booking_service(tmp_path, catalog):
    repo = SqliteRepository(tmp_path / "admin.db")
    await repo.open()
    svc = BookingService(repo=repo, catalog=catalog, sheets=InMemorySheetsGateway())
    yield svc
    await repo.close()


@pytest.mark.asyncio
async def test_admin_repo_lists_and_counts(booking_service, catalog):
    pet = PetProfile(
        kind=PetKind.DOG,
        name="Биби",
        weight_kg=6,
        vaccinated=True,
        parasite_treated=True,
    )
    booking, _ = await booking_service.submit_booking(
        telegram_user_id=42,
        customer_name="Анна",
        username="anna",
        consent_at=datetime.now(timezone.utc),
        date_from=date(2026, 11, 1),
        date_to=date(2026, 11, 3),
        pets=[pet],
        unit_id="comfort",
        feeding=FeedingOption.OWNER_FOOD,
        service_ids=[],
        placement_flags=[],
        manual_matching=False,
        customer_contact="+79001112233",
    )
    await booking_service.approve(booking.id)

    counts = await booking_service.repo.count_by_status()
    assert counts.get(BookingStatus.WAITING_PAYMENT.value) == 1

    unpaid = await booking_service.repo.list_bookings(
        statuses=[BookingStatus.WAITING_PAYMENT], limit=10
    )
    assert len(unpaid) == 1
    assert unpaid[0].customer_name == "Анна"

    clients = await booking_service.repo.list_customers()
    assert any(c["telegram_user_id"] == 42 for c in clients)

    overview = format_admin_overview(counts)
    assert "Ждут оплату залога: 1" in overview

    listing = format_admin_bookings_list(
        "💳 Неоплаченные",
        unpaid,
        catalog,
        empty_text="пусто",
    )
    assert "Биби" in listing
    assert short_status_label(BookingStatus.WAITING_PAYMENT) == "ждёт оплату"
    assert booking.id[:8] in admin_booking_button_title(unpaid[0])

    clients_text = format_admin_clients(clients)
    assert "Анна" in clients_text
    assert "+79001112233" in clients_text


def _callbacks(kb):
    return [b.callback_data for row in kb.inline_keyboard for b in row] if kb else []


def test_owner_booking_kb_matches_status():
    from dobrolap_bot.bot.keyboards import owner_booking_kb

    pending = _callbacks(owner_booking_kb("b1", BookingStatus.WAITING_OWNER))
    assert "own:approve:b1" in pending

    # Unpaid reserve: «Подтвердить» (approve) would fail with InvalidTransitionError,
    # the card must offer payment confirmation / cancel instead.
    unpaid = _callbacks(owner_booking_kb("b1", BookingStatus.WAITING_PAYMENT))
    assert "own:approve:b1" not in unpaid
    assert "own:paid:b1" in unpaid
    assert "own:cancel:b1" in unpaid

    confirmed = _callbacks(owner_booking_kb("b1", BookingStatus.CONFIRMED))
    assert confirmed == ["own:cancel:b1"]

    assert owner_booking_kb("b1", BookingStatus.CANCELLED) is None
    assert owner_booking_kb("b1", "EXPIRED") is None
