from __future__ import annotations

import json
from datetime import date

import pytest

from dobrolap_bot.integrations.apps_script_sheets import AppsScriptSheetsGateway, _parse_date


def test_parse_date_formats():
    assert _parse_date("2026-10-10") == date(2026, 10, 10)
    assert _parse_date("10.10.2026") == date(2026, 10, 10)


def test_apps_script_list_and_upsert(monkeypatch):
    calls: list[dict] = []

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            payload = calls[-1]
            if payload["action"] == "list":
                return json.dumps(
                    {
                        "ok": True,
                        "bookings": [
                            {
                                "external_id": "b1",
                                "unit_id": "comfort",
                                "date_from": "2026-10-01",
                                "date_to": "2026-10-05",
                                "status": "CONFIRMED",
                            }
                        ],
                    }
                ).encode()
            if payload["action"] == "upsert":
                return json.dumps({"ok": True, "booking": payload["booking"]}).encode()
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
    rows = gw.list_bookings()
    assert len(rows) == 1
    assert rows[0].unit_id == "comfort"
    assert "comfort" in gw.occupied_unit_ids(date(2026, 10, 2), date(2026, 10, 4))

    gw.upsert_booking(
        booking_id="b2",
        unit_id="vip_plus_house_reserve",
        date_from=date(2026, 11, 1),
        date_to=date(2026, 11, 3),
        status="WAITING_PAYMENT",
    )
    assert calls[-1]["action"] == "upsert"
    assert calls[-1]["booking"]["external_id"] == "b2"


def test_apps_script_rejects_placeholder_token():
    with pytest.raises(ValueError):
        AppsScriptSheetsGateway(
            webapp_url="https://script.google.com/macros/s/xxx/exec",
            token="CHANGE_ME_TO_LONG_RANDOM_SECRET",
        )
