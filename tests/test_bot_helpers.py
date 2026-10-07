from datetime import date

from dobrolap_bot.bot.helpers import parse_dates, parse_yes


def test_parse_dates():
    assert parse_dates("10.10.2026 - 15.10.2026") == (date(2026, 10, 10), date(2026, 10, 15))
    assert parse_dates("10.10.2026-15.10.2026") == (date(2026, 10, 10), date(2026, 10, 15))
    assert parse_dates("bad") is None
    assert parse_dates("15.10.2026 - 10.10.2026") is None


def test_yes_helper():
    assert parse_yes("Да") is True
    assert parse_yes("нет") is False
    assert parse_yes("maybe") is None
