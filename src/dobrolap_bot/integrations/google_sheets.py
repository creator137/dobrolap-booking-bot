"""Google Sheets calendar gateway + stubs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class SheetBooking:
    external_id: str
    unit_id: str
    date_from: date
    date_to: date
    status: str


def dates_overlap(a_from: date, a_to: date, b_from: date, b_to: date) -> bool:
    """Half-open interval [from, to): same-day checkout/checkin does not overlap."""
    return a_from < b_to and b_from < a_to


class SheetsGateway(Protocol):
    def list_bookings(self) -> list[SheetBooking]: ...

    def occupied_unit_ids(
        self,
        date_from: date,
        date_to: date,
        *,
        exclude_booking_id: str | None = None,
    ) -> set[str]: ...

    def upsert_booking(
        self,
        *,
        booking_id: str,
        unit_id: str,
        date_from: date,
        date_to: date,
        status: str,
    ) -> SheetBooking: ...


class InMemorySheetsGateway:
    def __init__(self, rows: list[SheetBooking] | None = None) -> None:
        self._rows: dict[str, SheetBooking] = {r.external_id: r for r in (rows or [])}

    def list_bookings(self) -> list[SheetBooking]:
        return list(self._rows.values())

    def occupied_unit_ids(
        self,
        date_from: date,
        date_to: date,
        *,
        exclude_booking_id: str | None = None,
    ) -> set[str]:
        occupied: set[str] = set()
        for row in self._rows.values():
            if exclude_booking_id and row.external_id == exclude_booking_id:
                continue
            if row.status.upper() in {"CANCELLED", "REJECTED", "EXPIRED", "OWNER_REJECTED"}:
                continue
            if dates_overlap(date_from, date_to, row.date_from, row.date_to):
                occupied.add(row.unit_id)
        return occupied

    def upsert_booking(
        self,
        *,
        booking_id: str,
        unit_id: str,
        date_from: date,
        date_to: date,
        status: str,
    ) -> SheetBooking:
        row = SheetBooking(
            external_id=booking_id,
            unit_id=unit_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )
        self._rows[booking_id] = row
        return row


class DisabledSheetsGateway:
    def list_bookings(self) -> list[SheetBooking]:
        return []

    def occupied_unit_ids(
        self,
        date_from: date,
        date_to: date,
        *,
        exclude_booking_id: str | None = None,
    ) -> set[str]:
        return set()

    def upsert_booking(
        self,
        *,
        booking_id: str,
        unit_id: str,
        date_from: date,
        date_to: date,
        status: str,
    ) -> SheetBooking:
        return SheetBooking(
            external_id=booking_id,
            unit_id=unit_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )
