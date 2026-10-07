from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.bot.handlers import _accept_receipt
from dobrolap_bot.domain.enums import BookingStatus, FeedingOption, PetKind
from dobrolap_bot.domain.models import PetProfile
from dobrolap_bot.integrations.google_sheets import InMemorySheetsGateway, SheetBooking
from dobrolap_bot.repositories.sqlite import SqliteRepository
from dobrolap_bot.services.booking import BookingService, InvalidTransitionError
from dobrolap_bot.services.summary import format_client_status, format_owner_summary


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
        customer_contact="+79001234567",
    )
    assert booking.status == BookingStatus.WAITING_OWNER
    assert quote is not None
    assert quote.total_rub > 0
    owner_card = format_owner_summary(booking, catalog)
    assert "+79001234567" in owner_card
    assert "WAITING_OWNER" not in owner_card
    stored = await booking_service.get(booking.id)
    assert stored is not None
    assert stored.customer_contact == "+79001234567"

    booking = await booking_service.approve(booking.id)
    assert booking.status == BookingStatus.WAITING_PAYMENT
    assert booking.id in {r.external_id for r in booking_service.sheets.list_bookings()}

    booking = await booking_service.attach_receipt(booking.id, "file_receipt_1")
    assert "file_receipt_1" in booking.payload["receipt_file_ids"]

    booking = await booking_service.confirm_payment(booking.id)
    assert booking.status == BookingStatus.CONFIRMED
    client_card = format_client_status(booking, catalog)
    assert "Бронь подтверждена" in client_card
    assert "CONFIRMED" not in client_card


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
    # Fill the whole comfort pool (Комфорт 1/2/3) — one slot busy is not enough.
    for i, label in enumerate(booking_service.sheet_labels("comfort")):
        booking_service.sheets.upsert_booking(
            booking_id=f"other{i}",
            unit_id=label,
            date_from=date(2026, 12, 2),
            date_to=date(2026, 12, 6),
            status="CONFIRMED",
        )
    with pytest.raises(ValueError, match="unit_occupied"):
        await booking_service.approve(booking.id)


@pytest.mark.asyncio
async def test_confirm_requires_receipt(booking_service):
    booking, _ = await booking_service.submit_booking(
        telegram_user_id=555,
        customer_name="D",
        username=None,
        consent_at=None,
        date_from=date(2027, 1, 1),
        date_to=date(2027, 1, 3),
        pets=[_pet()],
        unit_id="comfort",
        feeding=FeedingOption.OWNER_FOOD,
        service_ids=[],
        placement_flags=[],
        manual_matching=False,
    )
    booking = await booking_service.approve(booking.id)
    with pytest.raises(ValueError, match="receipt_required"):
        await booking_service.confirm_payment(booking.id)


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
    with pytest.raises(ValueError, match="unit_required"):
        await booking_service.approve(booking.id)
    booking, _ = await booking_service.suggest_unit(booking.id, "comfort")
    booking = await booking_service.approve(booking.id)
    assert booking.status == BookingStatus.WAITING_PAYMENT


@pytest.mark.asyncio
async def test_legacy_payment_cannot_confirm_without_calendar_slot(booking_service):
    booking, _ = await booking_service.submit_booking(
        telegram_user_id=776, customer_name="A", username=None, consent_at=None,
        date_from=date(2027, 1, 1), date_to=date(2027, 1, 3), pets=[_pet()],
        unit_id=None, feeding=None, service_ids=[], placement_flags=[],
        manual_matching=True,
    )
    booking.status = BookingStatus.WAITING_PAYMENT
    booking.payload["receipt_file_ids"] = ["receipt"]
    await booking_service.repo.save_booking(booking)
    with pytest.raises(ValueError, match="unit_required"):
        await booking_service.confirm_payment(booking.id)
    assert (await booking_service.get(booking.id)).status == BookingStatus.WAITING_PAYMENT


@pytest.mark.asyncio
async def test_stale_approve_does_not_reserve(booking_service):
    booking, _ = await booking_service.submit_booking(
        telegram_user_id=777, customer_name="A", username=None, consent_at=None,
        date_from=date(2027, 2, 1), date_to=date(2027, 2, 3), pets=[_pet()],
        unit_id="comfort", feeding=None, service_ids=[], placement_flags=[],
        manual_matching=False,
    )
    await booking_service.cancel(booking.id)
    with pytest.raises(InvalidTransitionError):
        await booking_service.approve(booking.id)
    assert booking_service.sheets.list_bookings() == []


@pytest.mark.asyncio
async def test_change_after_hold_releases_old_room_and_receipt(booking_service):
    booking, _ = await booking_service.submit_booking(
        telegram_user_id=778, customer_name="A", username=None, consent_at=None,
        date_from=date(2027, 3, 1), date_to=date(2027, 3, 3), pets=[_pet()],
        unit_id="comfort", feeding=None, service_ids=[], placement_flags=[],
        manual_matching=False,
    )
    booking = await booking_service.approve(booking.id)
    old_label = booking.payload["sheet_label"]
    await booking_service.attach_receipt(booking.id, "old-receipt")
    booking, _ = await booking_service.suggest_unit(booking.id, "comfort_plus")
    assert booking.payload["sheet_label"] is None
    assert booking.payload["receipt_file_ids"] == []
    assert old_label not in booking_service.sheets.occupied_unit_ids(booking.date_from, booking.date_to)
    booking = await booking_service.approve(booking.id)
    with pytest.raises(ValueError, match="receipt_required"):
        await booking_service.confirm_payment(booking.id)


@pytest.mark.asyncio
async def test_failed_release_keeps_booking_active(booking_service, monkeypatch):
    booking, _ = await booking_service.submit_booking(
        telegram_user_id=779, customer_name="A", username=None, consent_at=None,
        date_from=date(2027, 4, 1), date_to=date(2027, 4, 3), pets=[_pet()],
        unit_id="comfort", feeding=None, service_ids=[], placement_flags=[],
        manual_matching=False,
    )
    booking = await booking_service.approve(booking.id)

    def fail_release(**kwargs):
        raise RuntimeError("calendar unavailable")

    monkeypatch.setattr(booking_service.sheets, "release_booking", fail_release)
    with pytest.raises(RuntimeError, match="calendar unavailable"):
        await booking_service.cancel(booking.id)
    assert (await booking_service.get(booking.id)).status == BookingStatus.WAITING_PAYMENT


@pytest.mark.asyncio
async def test_failed_cancel_save_restores_calendar_hold(booking_service, monkeypatch):
    booking, _ = await booking_service.submit_booking(
        telegram_user_id=781, customer_name="A", username=None, consent_at=None,
        date_from=date(2027, 6, 1), date_to=date(2027, 6, 3), pets=[_pet()],
        unit_id="comfort", feeding=None, service_ids=[], placement_flags=[],
        manual_matching=False,
    )
    booking = await booking_service.approve(booking.id)
    label = booking.payload["sheet_label"]

    async def fail_save(record, *, expected_status=None):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(booking_service.repo, "save_booking_if_status", fail_save)
    with pytest.raises(RuntimeError, match="database unavailable"):
        await booking_service.cancel(booking.id)
    assert (await booking_service.get(booking.id)).status == BookingStatus.WAITING_PAYMENT
    assert label in booking_service.sheets.occupied_unit_ids(booking.date_from, booking.date_to)


@pytest.mark.asyncio
async def test_receipt_requires_selection_when_multiple_bookings_wait(booking_service):
    bookings = []
    for unit_id in ("comfort", "comfort_plus"):
        booking, _ = await booking_service.submit_booking(
            telegram_user_id=780, customer_name="A", username=None, consent_at=None,
            date_from=date(2027, 5, 1), date_to=date(2027, 5, 3), pets=[_pet()],
            unit_id=unit_id, feeding=None, service_ids=[], placement_flags=[],
            manual_matching=False,
        )
        bookings.append(await booking_service.approve(booking.id))

    answers = []

    async def answer(text):
        answers.append(text)

    message = SimpleNamespace(from_user=SimpleNamespace(id=780), answer=answer, bot=None)
    assert await _accept_receipt(message, booking_service, None, "receipt")
    assert "несколько заявок" in answers[-1]
    assert not (await booking_service.get(bookings[0].id)).payload["receipt_file_ids"]
    assert not (await booking_service.get(bookings[1].id)).payload["receipt_file_ids"]

    assert await _accept_receipt(
        message, booking_service, None, "receipt", booking_id=bookings[0].id
    )
    assert (await booking_service.get(bookings[0].id)).payload["receipt_file_ids"] == ["receipt"]
    assert not (await booking_service.get(bookings[1].id)).payload["receipt_file_ids"]


@pytest.mark.asyncio
async def test_approve_sets_hold_expiry(booking_service):
    booking, _ = await booking_service.submit_booking(
        telegram_user_id=800, customer_name="H", username=None, consent_at=None,
        date_from=date(2027, 7, 1), date_to=date(2027, 7, 3), pets=[_pet()],
        unit_id="comfort", feeding=None, service_ids=[], placement_flags=[],
        manual_matching=False,
    )
    booking = await booking_service.approve(booking.id)
    assert booking.hold_expires_at is not None
    assert booking.hold_expires_at > datetime.now(timezone.utc)
    assert any(e.get("action") == "approve_hold" for e in booking.payload.get("audit") or [])


@pytest.mark.asyncio
async def test_cancel_after_confirm_sets_refund_pending(booking_service):
    booking, _ = await booking_service.submit_booking(
        telegram_user_id=801, customer_name="H", username=None, consent_at=None,
        date_from=date(2027, 8, 1), date_to=date(2027, 8, 3), pets=[_pet()],
        unit_id="comfort", feeding=None, service_ids=[], placement_flags=[],
        manual_matching=False,
    )
    booking = await booking_service.approve(booking.id)
    label = booking.payload["sheet_label"]
    await booking_service.attach_receipt(booking.id, "r1")
    booking = await booking_service.confirm_payment(booking.id)
    booking = await booking_service.cancel(booking.id, "client", actor="owner", refund_pending=True)
    assert booking.status == BookingStatus.CANCELLED
    assert booking.payload["refund"]["status"] == "pending"
    assert label not in booking_service.sheets.occupied_unit_ids(booking.date_from, booking.date_to)
    booking = await booking_service.mark_refund(booking.id, "2000 returned")
    assert booking.payload["refund"]["status"] == "done"
    # idempotent cancel
    again = await booking_service.cancel(booking.id, "again")
    assert again.status == BookingStatus.CANCELLED


@pytest.mark.asyncio
async def test_expire_hold(booking_service):
    booking, _ = await booking_service.submit_booking(
        telegram_user_id=802, customer_name="H", username=None, consent_at=None,
        date_from=date(2027, 9, 1), date_to=date(2027, 9, 3), pets=[_pet()],
        unit_id="comfort", feeding=None, service_ids=[], placement_flags=[],
        manual_matching=False,
    )
    booking = await booking_service.approve(booking.id)
    booking.hold_expires_at = datetime.now(timezone.utc).replace(year=2020)
    await booking_service.repo.save_booking(booking)
    expired = await booking_service.expire_hold(booking.id)
    assert expired is not None
    assert expired.status == BookingStatus.EXPIRED
    assert booking_service.sheets.list_bookings() == []
    # second expire is no-op
    assert await booking_service.expire_hold(booking.id) is None


@pytest.mark.asyncio
async def test_reject_only_waiting_owner(booking_service):
    booking, _ = await booking_service.submit_booking(
        telegram_user_id=803, customer_name="H", username=None, consent_at=None,
        date_from=date(2027, 10, 1), date_to=date(2027, 10, 3), pets=[_pet()],
        unit_id="comfort", feeding=None, service_ids=[], placement_flags=[],
        manual_matching=False,
    )
    booking = await booking_service.approve(booking.id)
    with pytest.raises(InvalidTransitionError):
        await booking_service.reject(booking.id, "too late")


@pytest.mark.asyncio
async def test_fsm_sqlite_roundtrip(tmp_path):
    from aiogram.fsm.storage.base import StorageKey
    from dobrolap_bot.repositories.fsm_sqlite import SqliteFsmStorage

    storage = SqliteFsmStorage(tmp_path / "fsm.db")
    await storage.open()
    key = StorageKey(bot_id=1, chat_id=2, user_id=2)
    await storage.set_state(key, "BookingForm:waiting_receipt")
    await storage.set_data(key, {"booking_id": "abc"})
    assert await storage.get_state(key) == "BookingForm:waiting_receipt"
    assert (await storage.get_data(key))["booking_id"] == "abc"
    await storage.close()
    # reopen
    storage2 = SqliteFsmStorage(tmp_path / "fsm.db")
    await storage2.open()
    assert await storage2.get_state(key) == "BookingForm:waiting_receipt"
    await storage2.close()
