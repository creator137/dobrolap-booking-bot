from __future__ import annotations

from datetime import time


ARRIVAL_RULES_TEXT = (
    "Будем рады принять вас:\n"
    "Вечерний заезд (19:00–21:00) — без дополнительной оплаты.\n"
    "Утренний заезд (08:00–11:00) — оплачивается как полный день проживания.\n"
    "В остальное время — технический перерыв. Для особого случая выберите «Другое время»: "
    "возможность заезда и доплату руководитель согласует отдельно."
)


def arrival_requires_price_review(value: time) -> bool:
    """True when the arrival charge is not a confirmed fixed rule."""
    return not (
        time(8, 0) <= value <= time(11, 0)
        or time(19, 0) <= value <= time(21, 0)
    )


def arrival_price_notice(value: time) -> str:
    if time(19, 0) <= value <= time(21, 0):
        return "Заезд попадает в окно 19:00–21:00 без доплаты."
    if time(8, 0) <= value <= time(11, 0):
        return "Ранний заезд: оплачивается стоимость полного дня."
    return (
        "В это время технический перерыв. Вы запросили исключение: "
        "возможность заезда и доплату должен подтвердить руководитель зоогостиницы."
    )
