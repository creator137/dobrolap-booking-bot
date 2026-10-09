"""Sheets calendar gateway protocol + safe stubs.

Production calendar is a grid: rows = rooms, columns = dates (Лист1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol


class SheetsUnavailableError(RuntimeError):
    """Calendar backend missing or failing — fail closed."""


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

    def reserve_booking(
        self,
        *,
        booking_id: str,
        unit_id: str,
        date_from: date,
        date_to: date,
        status: str,
        note: str | None = None,
    ) -> SheetBooking:
        """Atomically re-check availability and write the hold. Raises ValueError if busy."""
        ...

    def release_booking(self, *, booking_id: str, unit_id: str | None = None) -> None:
        """Clear calendar cells for a cancelled booking."""
        ...

    def upsert_booking(
        self,
        *,
        booking_id: str,
        unit_id: str,
        date_from: date,
        date_to: date,
        status: str,
        note: str | None = None,
    ) -> SheetBooking:
        """Update mark/status; for cancel use release_booking when status is cancelled."""
        ...


class InMemorySheetsGateway:
    """Test double only — never used when GOOGLE_SHEETS_ENABLED=true in production factory."""

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

    def reserve_booking(
        self,
        *,
        booking_id: str,
        unit_id: str,
        date_from: date,
        date_to: date,
        status: str,
        note: str | None = None,
    ) -> SheetBooking:
        occupied = self.occupied_unit_ids(
            date_from, date_to, exclude_booking_id=booking_id
        )
        if unit_id in occupied:
            raise ValueError("unit_occupied")
        return self.upsert_booking(
            booking_id=booking_id,
            unit_id=unit_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
            note=note,
        )

    def release_booking(self, *, booking_id: str, unit_id: str | None = None) -> None:
        row = self._rows.pop(booking_id, None)
        if row is None and unit_id:
            return

    def upsert_booking(
        self,
        *,
        booking_id: str,
        unit_id: str,
        date_from: date,
        date_to: date,
        status: str,
        note: str | None = None,
    ) -> SheetBooking:
        _ = note
        if status.upper() in {"CANCELLED", "REJECTED", "EXPIRED", "OWNER_REJECTED"}:
            self.release_booking(booking_id=booking_id, unit_id=unit_id)
            row = SheetBooking(booking_id, unit_id, date_from, date_to, status)
            return row
        row = SheetBooking(booking_id, unit_id, date_from, date_to, status)
        self._rows[booking_id] = row
        return row


class DisabledSheetsGateway:
    """Explicitly disabled calendar (local smoke without Sheets)."""

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

    def reserve_booking(
        self,
        *,
        booking_id: str,
        unit_id: str,
        date_from: date,
        date_to: date,
        status: str,
        note: str | None = None,
    ) -> SheetBooking:
        _ = note
        return SheetBooking(booking_id, unit_id, date_from, date_to, status)

    def release_booking(self, *, booking_id: str, unit_id: str | None = None) -> None:
        return None

    def upsert_booking(
        self,
        *,
        booking_id: str,
        unit_id: str,
        date_from: date,
        date_to: date,
        status: str,
        note: str | None = None,
    ) -> SheetBooking:
        _ = note
        return SheetBooking(booking_id, unit_id, date_from, date_to, status)


class UnavailableSheetsGateway:
    """Fail-closed stand-in when Sheets was requested but not configured/reachable."""

    def __init__(self, reason: str = "sheets_unavailable") -> None:
        self.reason = reason

    def _boom(self) -> None:
        raise SheetsUnavailableError(self.reason)

    def list_bookings(self) -> list[SheetBooking]:
        self._boom()
        return []

    def occupied_unit_ids(
        self,
        date_from: date,
        date_to: date,
        *,
        exclude_booking_id: str | None = None,
    ) -> set[str]:
        self._boom()
        return set()

    def reserve_booking(
        self,
        *,
        booking_id: str,
        unit_id: str,
        date_from: date,
        date_to: date,
        status: str,
        note: str | None = None,
    ) -> SheetBooking:
        _ = note
        self._boom()
        raise SheetsUnavailableError(self.reason)

    def release_booking(self, *, booking_id: str, unit_id: str | None = None) -> None:
        self._boom()

    def upsert_booking(
        self,
        *,
        booking_id: str,
        unit_id: str,
        date_from: date,
        date_to: date,
        status: str,
        note: str | None = None,
    ) -> SheetBooking:
        _ = note
        self._boom()
        raise SheetsUnavailableError(self.reason)
