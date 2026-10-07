from __future__ import annotations

import json
from datetime import date

import pytest

from dobrolap_bot.integrations.apps_script_sheets import AppsScriptSheetsGateway, _parse_date
from dobrolap_bot.integrations.factory import build_sheets_gateway
from dobrolap_bot.integrations.google_sheets import UnavailableSheetsGateway
from dobrolap_bot.config.settings import Settings
from pathlib import Path


def test_parse_date_formats():
    assert _parse_date("2026-10-10") == date(2026, 10, 10)
    assert _parse_date("10.10.2026") == date(2026, 10, 10)


def test_apps_script_occupied_and_reserve(monkeypatch):
    calls: list[dict] = []

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            payload = calls[-1]
            if payload["action"] == "occupied":
                return json.dumps(
                    {"ok": True, "occupied_unit_ids": ["Комфорт"]}
                ).encode()
            if payload["action"] == "reserve":
                return json.dumps({"ok": True, "booking": payload["booking"]}).encode()
            if payload["action"] == "list":
                return json.dumps({"ok": True, "bookings": []}).encode()
            return json.dumps({"ok": True}).encode()

    def fake_urlopen(req, timeout=30):
        body = json.loads(req.data.decode())
        calls.append(body)
        assert body["token"] == "secret-token"
        return FakeResp()

    monkeypatch.setattr(
        "dobrolap_bot.integrations.apps_script_sheets.urllib.request.urlopen",
        fake_urlopen,
    )

    gw = AppsScriptSheetsGateway(
        webapp_url="https://script.google.com/macros/s/xxx/exec",
        token="secret-token",
    )
    assert "Комфорт" in gw.occupied_unit_ids(date(2026, 10, 2), date(2026, 10, 4))
    assert calls[-1]["action"] == "occupied"

    gw.reserve_booking(
        booking_id="b2",
        unit_id="Комфорт",
        date_from=date(2026, 11, 1),
        date_to=date(2026, 11, 3),
        status="WAITING_PAYMENT",
    )
    assert calls[-1]["action"] == "reserve"
    assert calls[-1]["booking"]["unit_id"] == "Комфорт"


def test_apps_script_rejects_placeholder_token():
    with pytest.raises(ValueError):
        AppsScriptSheetsGateway(
            webapp_url="https://script.google.com/macros/s/xxx/exec",
            token="CHANGE_ME_TO_LONG_RANDOM_SECRET",
        )


def test_factory_fail_closed_when_enabled_without_creds(tmp_path):
    settings = Settings.model_construct(
        google_sheets_enabled=True,
        gas_webapp_url="",
        gas_webapp_token="",
        google_sheets_spreadsheet_id="",
        google_service_account_file=None,
    )
    gw = build_sheets_gateway(settings, tmp_path)
    assert isinstance(gw, UnavailableSheetsGateway)
