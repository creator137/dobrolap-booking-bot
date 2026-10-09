from __future__ import annotations

from datetime import date

import pytest

from dobrolap_bot.integrations.grid_calendar import (
    build_room_label,
    calendar_cell_mark,
    date_columns,
    extract_booking_id,
    iter_room_rows,
    parse_header_date,
    require_complete_date_range,
)


def test_human_calendar_mark_keeps_booking_id():
    mark = calendar_cell_mark("WAITING_PAYMENT", "abc123", "Бобик")
    assert mark == "резерв до оплаты Бобик · бот #abc123"
    assert extract_booking_id(mark) == "abc123"
    assert extract_booking_id("CONFIRMED:abc123") == "abc123"
    assert calendar_cell_mark("CONFIRMED", "abc123") == "бронь · бот #abc123"


def test_parse_sheets_serial():
    assert parse_header_date(46255) == date(2026, 8, 21)


def test_parse_ru_month_text():
    assert parse_header_date("21.авг.", fallback_year=2026) == date(2026, 8, 21)
    assert parse_header_date("1.сент.", fallback_year=2026) == date(2026, 9, 1)
    assert parse_header_date("13.сент", fallback_year=2026) == date(2026, 9, 13)


def test_build_room_label_variants():
    assert (
        build_room_label(category="Комната Комфорт", subcategory="1", carried_category="")
        == "Комната Комфорт 1"
    )
    assert (
        build_room_label(category="", subcategory="2", carried_category="Комната Комфорт")
        == "Комната Комфорт 2"
    )
    assert (
        build_room_label(category="", subcategory="2 этаж балкон", carried_category="ВИП+")
        == "2 этаж балкон"
    )
    assert (
        build_room_label(category="Комфорт+", subcategory="", carried_category="")
        == "Комфорт+"
    )


def test_iter_room_rows_matches_prod_shape():
    values = [
        ["Название", "Подкатегория", 46255, 46256],
        ["Отдельная Комната ВИП+", "1 этаж мастерская", "Бадик", ""],
        ["", "2 этаж комната с формулами", "", ""],
        ["Комната Комфорт", "1", "", ""],
        ["", "2", "busy", ""],
        ["Комфорт+", "", "", ""],
        ["Уличный Вольер Комфорт для собак", "1", "dog", ""],
        ["", "2", "", ""],
    ]
    rooms = iter_room_rows(values)
    labels = [label for _, label in rooms]
    assert labels == [
        "1 этаж мастерская",
        "2 этаж комната с формулами",
        "Комната Комфорт 1",
        "Комната Комфорт 2",
        "Комфорт+",
        "Уличный Вольер Комфорт для собак 1",
        "Уличный Вольер Комфорт для собак 2",
    ]
    cols = date_columns(
        values[0],
        first_date_col=3,
        date_from=date(2026, 8, 21),
        date_to=date(2026, 8, 22),
    )
    assert cols == [(2, date(2026, 8, 21))]


def test_calendar_range_requires_every_night_once():
    start, end = date(2026, 8, 21), date(2026, 8, 24)
    require_complete_date_range(
        [(2, date(2026, 8, 21)), (3, date(2026, 8, 22)), (4, date(2026, 8, 23))],
        start, end,
    )
    with pytest.raises(ValueError, match="calendar_date_range_incomplete"):
        require_complete_date_range([(2, start), (3, date(2026, 8, 23))], start, end)
    with pytest.raises(ValueError, match="calendar_date_range_incomplete"):
        require_complete_date_range([(2, start), (3, start), (4, date(2026, 8, 23))], start, end)
