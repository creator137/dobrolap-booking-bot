"""Google Apps Script Web App gateway — preferred Sheets integration for MVP.

No service account JSON. Owner deploys Code.gs once; bot calls HTTPS endpoint.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import date
from typing import Any

from dobrolap_bot.integrations.google_sheets import SheetBooking, dates_overlap

logger = logging.getLogger(__name__)


class AppsScriptSheetsGateway:
    def __init__(self, *, webapp_url: str, token: str, timeout_sec: float = 30.0) -> None:
        if not webapp_url:
            raise ValueError("GAS_WEBAPP_URL is empty")
        if not token or token == "CHANGE_ME_TO_LONG_RANDOM_SECRET":
            raise ValueError("GAS_WEBAPP_TOKEN is empty or still the placeholder")
        self.webapp_url = webapp_url.rstrip("/")
        self.token = token
        self.timeout_sec = timeout_sec

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps({**payload, "token": self.token}).encode("utf-8")
        req = urllib.request.Request(
            self.webapp_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Apps Script HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Apps Script unreachable: {exc}") from exc

        data = json.loads(raw or "{}")
        if not data.get("ok"):
            raise RuntimeError(f"Apps Script error: {data.get('error') or data}")
        return data

    def ping(self) -> dict[str, Any]:
        return self._post({"action": "ping"})

    def list_bookings(self) -> list[SheetBooking]:
        data = self._post({"action": "list"})
        rows: list[SheetBooking] = []
        for item in data.get("bookings") or []:
            try:
                rows.append(
                    SheetBooking(
                        external_id=str(item["external_id"]),
                        unit_id=str(item["unit_id"]),
                        date_from=_parse_date(item["date_from"]),
                        date_to=_parse_date(item["date_to"]),
                        status=str(item.get("status") or "CONFIRMED"),
                    )
                )
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("Skip bad Apps Script row %s: %s", item, exc)
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
        booking = {
            "external_id": booking_id,
            "unit_id": unit_id,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "status": status,
        }
        self._post({"action": "upsert", "booking": booking})
        return SheetBooking(
            external_id=booking_id,
            unit_id=unit_id,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )


def _parse_date(value: Any) -> date:
    text = str(value).strip()
    # Apps Script may return dd.MM.yyyy depending on locale — accept both.
    for fmt_len in (10,):
        _ = fmt_len
    if len(text) >= 10 and text[4] == "-":
        return date.fromisoformat(text[:10])
    parts = text.replace("/", ".").split(".")
    if len(parts) == 3:
        d, m, y = (int(parts[0]), int(parts[1]), int(parts[2]))
        if y < 100:
            y += 2000
        return date(y, m, d)
    raise ValueError(f"bad date: {value!r}")
