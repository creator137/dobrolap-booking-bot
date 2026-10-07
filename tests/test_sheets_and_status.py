from datetime import date

from dobrolap_bot.integrations.google_sheets import InMemorySheetsGateway, SheetBooking, dates_overlap
from dobrolap_bot.domain.enums import BookingStatus
from dobrolap_bot.services.booking import InvalidTransitionError, can_transition, transition


def test_half_open_overlap():
    # checkout Oct 10 and checkin Oct 10 → no overlap
    assert not dates_overlap(date(2026, 10, 1), date(2026, 10, 10), date(2026, 10, 10), date(2026, 10, 15))
    assert dates_overlap(date(2026, 10, 1), date(2026, 10, 11), date(2026, 10, 10), date(2026, 10, 15))


def test_inmemory_occupied():
    gw = InMemorySheetsGateway(
        [
            SheetBooking("b1", "comfort", date(2026, 10, 5), date(2026, 10, 10), "CONFIRMED"),
        ]
    )
    assert "comfort" in gw.occupied_unit_ids(date(2026, 10, 8), date(2026, 10, 12))
    assert "comfort" not in gw.occupied_unit_ids(date(2026, 10, 10), date(2026, 10, 12))


def test_upsert_idempotent():
    gw = InMemorySheetsGateway()
    gw.upsert_booking(
        booking_id="x1",
        unit_id="comfort",
        date_from=date(2026, 11, 1),
        date_to=date(2026, 11, 5),
        status="WAITING_PAYMENT",
    )
    gw.upsert_booking(
        booking_id="x1",
        unit_id="comfort_plus",
        date_from=date(2026, 11, 1),
        date_to=date(2026, 11, 5),
        status="CONFIRMED",
    )
    rows = gw.list_bookings()
    assert len(rows) == 1
    assert rows[0].unit_id == "comfort_plus"
    assert rows[0].status == "CONFIRMED"


def test_status_transitions():
    assert can_transition(BookingStatus.DRAFT, BookingStatus.WAITING_OWNER)
    assert transition(BookingStatus.WAITING_OWNER, BookingStatus.OWNER_APPROVED) == BookingStatus.OWNER_APPROVED
    try:
        transition(BookingStatus.CONFIRMED, BookingStatus.DRAFT)
        assert False, "expected InvalidTransitionError"
    except InvalidTransitionError:
        pass
