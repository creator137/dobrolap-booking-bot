"""Live Google Sheets gateway (optional dependency).

Install: pip install google-api-python-client google-auth
Enable: GOOGLE_SHEETS_ENABLED=true + service account file + spreadsheet share.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from dobrolap_bot.integrations.google_sheets import SheetBooking, dates_overlap

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class GoogleSheetsGateway:
    def __init__(
        self,
        *,
        spreadsheet_id: str,
        credentials_file: Path,
        mapping_path: Path,
    ) -> None:
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Install google-api-python-client and google-auth for live Sheets"
            ) from exc

        if not spreadsheet_id:
            raise ValueError("spreadsheet_id is empty")
        if not credentials_file.exists():
            raise FileNotFoundError(credentials_file)

        mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8")) or {}
        self.spreadsheet_id = spreadsheet_id
        self.sheet_name = mapping.get("sheet_name", "Bookings")
        self.columns: dict[str, str] = mapping.get("columns", {})
        self.date_format = mapping.get("date_format", "%Y-%m-%d")
        self.header_row = int(mapping.get("header_row", 1))

        creds = service_account.Credentials.from_service_account_file(
            str(credentials_file),
            scopes=SCOPES,
        )
        self._service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    def _col_letter(self, key: str) -> str:
        letter = self.columns.get(key)
        if not letter:
            raise KeyError(f"sheets mapping missing column for {key}")
        return letter

    def _parse_date(self, value: str) -> date | None:
        value = (value or "").strip()
        if not value:
            return None
        for fmt in (self.date_format, "%d.%m.%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None

    def list_bookings(self) -> list[SheetBooking]:
        range_name = f"'{self.sheet_name}'!A:Z"
        result = (
            self._service.spreadsheets()
            .values()
            .get(spreadsheetId=self.spreadsheet_id, range=range_name)
            .execute()
        )
        values: list[list[Any]] = result.get("values", [])
        if len(values) <= self.header_row:
            return []

        # Build index from header if present, else use configured letters as 0-based
        header = values[self.header_row - 1] if values else []
        col_index = {name: idx for idx, name in enumerate(header)}

        def cell(row: list[Any], key: str) -> str:
            letter = self._col_letter(key)
            # Prefer header name match if headers look like keys
            if key in col_index:
                idx = col_index[key]
            else:
                idx = ord(letter.upper()) - ord("A")
            if idx >= len(row):
                return ""
            return str(row[idx]).strip()

        rows: list[SheetBooking] = []
        for raw in values[self.header_row :]:
            external_id = cell(raw, "external_id")
            unit_id = cell(raw, "unit_id")
            d_from = self._parse_date(cell(raw, "date_from"))
            d_to = self._parse_date(cell(raw, "date_to"))
            status = cell(raw, "status") or "CONFIRMED"
            if not external_id or not unit_id or not d_from or not d_to:
                continue
            rows.append(
                SheetBooking(
                    external_id=external_id,
                    unit_id=unit_id,
                    date_from=d_from,
                    date_to=d_to,
                    status=status,
                )
            )
        return rows

    def occupied_unit_ids(
        self,
        date_from: date,
        date_to: date,
        *,
        exclude_booking_id: str | None = None,
    ) -> set[str]:
        occupied: set[str] = set()
        for row in self.list_bookings():
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
        existing = self.list_bookings()
        row_number = None
        for idx, row in enumerate(existing, start=self.header_row + 1):
            if row.external_id == booking_id:
                row_number = idx
                break

        values = [[
            booking_id,
            unit_id,
            date_from.strftime(self.date_format),
            date_to.strftime(self.date_format),
            status,
        ]]
        if row_number is None:
            self._service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{self.sheet_name}'!A:E",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": values},
            ).execute()
            logger.info("Appended booking %s to Sheets", booking_id)
        else:
            self._service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{self.sheet_name}'!A{row_number}:E{row_number}",
                valueInputOption="USER_ENTERED",
                body={"values": values},
            ).execute()
            logger.info("Updated booking %s row %s in Sheets", booking_id, row_number)

        return SheetBooking(
            external_id=booking_id,
            unit_id=unit_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )
