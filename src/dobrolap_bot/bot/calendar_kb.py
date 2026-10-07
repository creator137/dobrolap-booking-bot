"""Inline month calendar for check-in / check-out (Telegram has no native date picker)."""

from __future__ import annotations

import calendar as pycal
from datetime import date, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

_WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
_MONTHS_RU = (
    "",
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


def month_title(year: int, month: int) -> str:
    return f"{_MONTHS_RU[month]} {year}"


def dates_prompt(*, pick_from: date | None = None) -> str:
    if pick_from is None:
        return (
            "Выберите дату <b>заезда</b> в календаре.\n"
            "Или напишите текстом: <code>ДД.ММ.ГГГГ - ДД.ММ.ГГГГ</code>"
        )
    return (
        f"Заезд: <b>{pick_from.strftime('%d.%m.%Y')}</b>\n"
        "Выберите дату <b>выезда</b> (позже заезда).\n"
        "Сброс — кнопка ниже, либо напишите обе даты текстом."
    )


def build_calendar(
    *,
    year: int,
    month: int,
    today: date | None = None,
    pick_from: date | None = None,
    min_date: date | None = None,
) -> InlineKeyboardMarkup:
    today = today or date.today()
    min_date = min_date or today
    rows: list[list[InlineKeyboardButton]] = []

    rows.append(
        [
            InlineKeyboardButton(text="‹", callback_data=f"cal:nav:{_shift(year, month, -1)}"),
            InlineKeyboardButton(text=month_title(year, month), callback_data="cal:noop"),
            InlineKeyboardButton(text="›", callback_data=f"cal:nav:{_shift(year, month, 1)}"),
        ]
    )
    rows.append(
        [InlineKeyboardButton(text=d, callback_data="cal:noop") for d in _WEEKDAYS]
    )

    cal = pycal.Calendar(firstweekday=0)
    week: list[InlineKeyboardButton] = []
    for day in cal.itermonthdates(year, month):
        if day.month != month:
            week.append(InlineKeyboardButton(text="·", callback_data="cal:noop"))
        else:
            disabled = day < min_date or (pick_from is not None and day <= pick_from)
            if pick_from and day == pick_from:
                # Keep check-in mark visible even though the day itself is not selectable.
                label = f"[{day.day}]"
            elif disabled:
                # Telegram can't grey out text — hide numbers so they don't look tappable.
                label = "·"
            elif day == today:
                label = f"·{day.day}·"
            else:
                label = str(day.day)
            if disabled:
                week.append(InlineKeyboardButton(text=label, callback_data="cal:noop"))
            else:
                week.append(
                    InlineKeyboardButton(
                        text=label,
                        callback_data=f"cal:day:{day.isoformat()}",
                    )
                )
        if len(week) == 7:
            rows.append(week)
            week = []

    footer = []
    if pick_from is not None:
        footer.append(InlineKeyboardButton(text="↺ Сбросить заезд", callback_data="cal:reset"))
    footer.append(InlineKeyboardButton(text="✏️ Ввести текстом", callback_data="cal:text"))
    rows.append(footer)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _shift(year: int, month: int, delta: int) -> str:
    d = date(year, month, 15) + timedelta(days=32 * delta)
    return f"{d.year:04d}-{d.month:02d}"


def parse_nav(payload: str) -> tuple[int, int] | None:
    # cal:nav:YYYY-MM
    try:
        _, _, ym = payload.split(":", 2)
        y, m = ym.split("-")
        return int(y), int(m)
    except ValueError:
        return None


def parse_day(payload: str) -> date | None:
    # cal:day:YYYY-MM-DD
    try:
        _, _, iso = payload.split(":", 2)
        return date.fromisoformat(iso)
    except ValueError:
        return None
