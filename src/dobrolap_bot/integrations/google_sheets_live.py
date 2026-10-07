"""Service-account reader/writer for the grid occupancy calendar (Лист1).

READ uses the real prod layout (A category / B room / C+ dates).
WRITE is gated by Settings / readonly flag — do not enable against prod
until the owner confirms.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from dobrolap_bot.integrations.google_sheets import SheetBooking, SheetsUnavailableError
from dobrolap_bot.integrations.grid_calendar import (
    cell_text,
    date_columns,
    is_occupied_cell,
    iter_room_rows,
)

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class GoogleSheetsGateway:
    def __init__(
        self,
        *,
        spreadsheet_id: str,
        credentials_file: Path,
        mapping_path: Path,
        readonly: bool = True,
    ) -> None:
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Install extras: pip install -e '.[sheets]'"
            ) from exc

        if not spreadsheet_id:
            raise ValueError("spreadsheet_id is empty")
        if not credentials_file.exists():
            raise FileNotFoundError(credentials_file)

        mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = (
            mapping.get("calendar_sheet_name") or mapping.get("sheet_name") or "Лист1"
        )
        self.header_row = int(mapping.get("header_row", 1))
        self.first_data_row = int(mapping.get("first_data_row", 2))
        self.category_col = int(mapping.get("category_col", 1))
        self.room_col = int(mapping.get("room_col", 2))
        self.first_date_col = int(mapping.get("first_date_col", 3))
        self.readonly = readonly

        creds = service_account.Credentials.from_service_account_file(
            str(credentials_file),
            scopes=SCOPES,
        )
        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    def _values(self) -> list[list[Any]]:
        range_name = f"'{self.sheet_name}'!A:ZZ"
        try:
            result = (
                self._service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=self.spreadsheet_id,
                    range=range_name,
                    valueRenderOption="UNFORMATTED_VALUE",
                )
                .execute()
            )
        except Exception as exc:
            raise SheetsUnavailableError(f"sheets_read_failed: {exc}") from exc
        return result.get("values", [])

    def _rooms(self, values: list[list[Any]]) -> list[tuple[int, str]]:
        return iter_room_rows(
            values,
            first_data_row=self.first_data_row,
            category_col=self.category_col,
            room_col=self.room_col,
        )

    def list_bookings(self) -> list[SheetBooking]:
        values = self._values()
        if len(values) < self.first_data_row:
            return []
        header = values[self.header_row - 1]
        dates = date_columns(header, first_date_col=self.first_date_col)
        out: list[SheetBooking] = []
        for row_idx, room in self._rooms(values):
            row = values[row_idx]
            for col_idx, d in dates:
                cell = cell_text(row, col_idx)
                if not cell:
                    continue
                bid = _extract_booking_id(cell) or f"manual:{room}:{d.isoformat()}"
                out.append(
                    SheetBooking(
                        external_id=bid,
                        unit_id=room,
                        date_from=d,
                        date_to=d + timedelta(days=1),
                        status="CONFIRMED",
                    )
                )
        return out

    def occupied_unit_ids(
        self,
        date_from: date,
        date_to: date,
        *,
        exclude_booking_id: str | None = None,
    ) -> set[str]:
        values = self._values()
        if len(values) < self.first_data_row:
            return set()
        header = values[self.header_row - 1]
        cols = date_columns(
            header,
            first_date_col=self.first_date_col,
            date_from=date_from,
            date_to=date_to,
        )
        occupied: set[str] = set()
        for row_idx, room in self._rooms(values):
            row = values[row_idx]
            for col_idx, _d in cols:
                if is_occupied_cell(cell_text(row, col_idx), exclude_booking_id):
                    occupied.add(room)
                    break
        return occupied

    def _ensure_writable(self) -> None:
        if self.readonly:
            raise SheetsUnavailableError(
                "sheets_readonly: write disabled (prod calendar). "
                "Set GOOGLE_SHEETS_READONLY=false only when ready."
            )

    def reserve_booking(
        self,
        *,
        booking_id: str,
        unit_id: str,
        date_from: date,
        date_to: date,
        status: str,
    ) -> SheetBooking:
        self._ensure_writable()
        values = self._values()
        header = values[self.header_row - 1] if values else []
        rooms = self._rooms(values)
        row_idx = next(
            (r for r, label in rooms if label.lower() == unit_id.strip().lower()),
            None,
        )
        if row_idx is None:
            raise ValueError(f"unknown_room:{unit_id}")

        cols = date_columns(
            header,
            first_date_col=self.first_date_col,
            date_from=date_from,
            date_to=date_to,
        )
        if not cols:
            raise SheetsUnavailableError("no_date_columns_for_range")

        for col_idx, _d in cols:
            if is_occupied_cell(cell_text(values[row_idx], col_idx), booking_id):
                raise ValueError("unit_occupied")

        mark = f"{status}:{booking_id}"
        data = [
            {
                "range": f"'{self.sheet_name}'!{_a1(row_idx + 1, col_idx + 1)}",
                "values": [[mark]],
            }
            for col_idx, _d in cols
        ]
        try:
            self._service.spreadsheets().values().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": data},
            ).execute()
        except Exception as exc:
            raise SheetsUnavailableError(f"sheets_write_failed: {exc}") from exc

        return SheetBooking(booking_id, unit_id, date_from, date_to, status)

    def release_booking(self, *, booking_id: str, unit_id: str | None = None) -> None:
        self._ensure_writable()
        values = self._values()
        if len(values) < self.first_data_row:
            return
        rooms = {r: label for r, label in self._rooms(values)}
        clears = []
        for row_idx, label in rooms.items():
            if unit_id and label.lower() != unit_id.strip().lower():
                continue
            row = values[row_idx]
            for c in range(self.first_date_col - 1, len(row)):
                cell = cell_text(row, c)
                if booking_id in cell:
                    clears.append(
                        {
                            "range": f"'{self.sheet_name}'!{_a1(row_idx + 1, c + 1)}",
                            "values": [[""]],
                        }
                    )
        if not clears:
            return
        try:
            self._service.spreadsheets().values().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": clears},
            ).execute()
        except Exception as exc:
            raise SheetsUnavailableError(f"sheets_release_failed: {exc}") from exc

    def upsert_booking(
        self,
        *,
        booking_id: str,
        unit_id: str,
        date_from: date,
        date_to: date,
        status: str,
    ) -> SheetBooking:
        if status.upper() in {"CANCELLED", "REJECTED", "EXPIRED", "OWNER_REJECTED"}:
            self.release_booking(booking_id=booking_id, unit_id=unit_id)
            return SheetBooking(booking_id, unit_id, date_from, date_to, status)
        return self.reserve_booking(
            booking_id=booking_id,
            unit_id=unit_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )


def _extract_booking_id(cell: str) -> str | None:
    import re

    m = re.search(
        r"(?:HOLD|WAITING_PAYMENT|CONFIRMED|OWNER_APPROVED):([A-Za-z0-9_-]+)",
        cell,
    )
    return m.group(1) if m else None


def _a1(row_1based: int, col_1based: int) -> str:
    n = col_1based
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row_1based}"


# Re-export for tests
__all__ = ["GoogleSheetsGateway", "parse_header_date"]
