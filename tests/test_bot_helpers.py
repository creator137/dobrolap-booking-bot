from datetime import date

from dobrolap_bot.bot.helpers import is_young, normalize_phone, parse_age_months, parse_dates, parse_yes
from dobrolap_bot.domain.enums import PetKind


def test_parse_dates():
    assert parse_dates("10.10.2026 - 15.10.2026") == (date(2026, 10, 10), date(2026, 10, 15))
    assert parse_dates("10.10.2026-15.10.2026") == (date(2026, 10, 10), date(2026, 10, 15))
    assert parse_dates("bad") is None
    assert parse_dates("15.10.2026 - 10.10.2026") is None


def test_yes_helper():
    assert parse_yes("Да") is True
    assert parse_yes("нет") is False
    assert parse_yes("maybe") is None


def test_normalize_phone():
    assert normalize_phone("8 (900) 123-45-67") == "+79001234567"
    assert normalize_phone("+7 900 123 45 67") == "+79001234567"
    assert normalize_phone("123") is None


def test_parse_age_for_humans():
    assert parse_age_months("18") == 18
    assert parse_age_months("8 месяцев") == 8
    assert parse_age_months("2 года 3 месяца") == 27
    assert parse_age_months("3 недели") == 0
    assert parse_age_months("1 неделя") == 0
    assert parse_age_months("меньше месяца") == 0
    assert is_young(PetKind.DOG, 12)
    assert not is_young(PetKind.CAT, 7)
    assert parse_age_months("не знаю") is None
