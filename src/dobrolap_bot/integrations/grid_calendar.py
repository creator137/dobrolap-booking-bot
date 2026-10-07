"""Pure helpers for the owner's grid calendar (Лист1).

Layout observed in prod «Размещение добролап»:
  A = category (Название), carried forward when blank
  B = subcategory / unit number (Подкатегория)
  C.. = date columns (Google serial or «21.авг.» text)
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

# Google Sheets serial date epoch (accounts for Lotus 1900 bug → 1899-12-30).
_SHEETS_EPOCH = date(1899, 12, 30)

_RU_MONTHS = {
    "янв": 1,
    "фев": 2,
    "мар": 3,
    "апр": 4,
    "май": 5,
    "мая": 5,
    "июн": 6,
    "июл": 7,
    "авг": 8,
    "сен": 9,
    "окт": 10,
    "ноя": 11,
    "дек": 12,
}


def cell_text(row: list[Any], idx: int) -> str:
    if idx >= len(row) or row[idx] is None:
        return ""
    return str(row[idx]).strip()


def parse_header_date(value: Any, *, fallback_year: int | None = None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            return _SHEETS_EPOCH + timedelta(days=int(value))
        except (OverflowError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == "-":
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    # «21.авг.» / «1.сент.» / «10.сент»
    m = re.match(
        r"^(\d{1,2})\s*[.\-/]?\s*([A-Za-zА-Яа-яё]{3,})",
        text,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    day = int(m.group(1))
    mon_key = m.group(2).lower().replace("ё", "е")[:3]
    month = _RU_MONTHS.get(mon_key)
    if not month or day < 1 or day > 31:
        return None
    year = fallback_year or date.today().year
    try:
        return date(year, month, day)
    except ValueError:
        return None


def build_room_label(*, category: str, subcategory: str, carried_category: str) -> str | None:
    """Compose stable room label from A/B cells."""
    cat = (category or "").strip()
    sub = (subcategory or "").strip()
    carried = (carried_category or "").strip()
    active_cat = cat or carried
    if sub.isdigit():
        return f"{active_cat} {sub}" if active_cat else None
    if sub:
        return sub
    if cat:
        return cat
    return None


def iter_room_rows(
    values: list[list[Any]],
    *,
    first_data_row: int = 2,
    category_col: int = 1,
    room_col: int = 2,
) -> list[tuple[int, str]]:
    """Return (0-based row index, room label) for data rows."""
    out: list[tuple[int, str]] = []
    carried = ""
    cat_i = category_col - 1
    room_i = room_col - 1
    for r in range(first_data_row - 1, len(values)):
        row = values[r]
        a = cell_text(row, cat_i)
        b = cell_text(row, room_i)
        if a:
            carried = a
        label = build_room_label(category=a, subcategory=b, carried_category=carried)
        if label:
            out.append((r, label))
    return out


def date_columns(
    header: list[Any],
    *,
    first_date_col: int = 3,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[tuple[int, date]]:
    cols: list[tuple[int, date]] = []
    for c in range(first_date_col - 1, len(header)):
        d = parse_header_date(header[c])
        if d is None:
            continue
        if date_from is not None and date_to is not None:
            if not (date_from <= d < date_to):
                continue
        cols.append((c, d))
    return cols


def require_complete_date_range(
    columns: list[tuple[int, date]], date_from: date, date_to: date
) -> None:
    """Reject calendars without exactly one column for every booked night."""
    expected_days = (date_to - date_from).days
    actual = {day for _, day in columns}
    if expected_days < 1 or len(columns) != expected_days or len(actual) != expected_days:
        raise ValueError("calendar_date_range_incomplete")
    if any(date_from + timedelta(days=offset) not in actual for offset in range(expected_days)):
        raise ValueError("calendar_date_range_incomplete")


def is_occupied_cell(cell: str, exclude_booking_id: str | None = None) -> bool:
    text = (cell or "").strip()
    if not text:
        return False
    if exclude_booking_id and exclude_booking_id in text:
        return False
    return True
