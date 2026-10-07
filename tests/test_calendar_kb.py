from datetime import date

from dobrolap_bot.bot.calendar_kb import build_calendar, parse_day, parse_nav


def test_parse_nav_and_day():
    assert parse_nav("cal:nav:2026-10") == (2026, 10)
    assert parse_day("cal:day:2026-10-15") == date(2026, 10, 15)


def test_build_calendar_disables_past_and_has_nav():
    kb = build_calendar(
        year=2026,
        month=10,
        today=date(2026, 10, 7),
        min_date=date(2026, 10, 7),
    )
    flat = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert "cal:nav:2026-09" in flat
    assert "cal:nav:2026-11" in flat
    assert "cal:day:2026-10-07" in flat
    # past day disabled — no number, no callback
    assert "cal:day:2026-10-01" not in flat
    assert "1" not in texts


def test_checkout_calendar_requires_after_checkin():
    kb = build_calendar(
        year=2026,
        month=10,
        today=date(2026, 10, 7),
        pick_from=date(2026, 10, 10),
        min_date=date(2026, 10, 11),
    )
    flat = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "cal:day:2026-10-10" not in flat
    assert "cal:day:2026-10-11" in flat
    assert "cal:reset" in flat
