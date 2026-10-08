from __future__ import annotations

from datetime import time


ARRIVAL_RULES_TEXT = (
    "Заезд с 19:00 до 21:00 — без доплаты.\n"
    "С 08:00 до 11:00 — оплачивается стоимость полного дня.\n"
    "До 08:00 и после 21:00 — доплата 15% за каждый час.\n"
    "Заезд с 16:30 до 19:00 — 50% стоимости полного дня (индивидуальный случай, как перерыв).\n"
    "Для других случаев до 19:00 может применяться доплата 15% за каждый час."
)


def arrival_requires_price_review(value: time) -> bool:
    """True when the arrival charge is not a confirmed fixed rule."""
    return not (
        time(8, 0) <= value <= time(11, 0)
        or time(16, 30) <= value <= time(21, 0)
    )


def arrival_price_notice(value: time) -> str:
    if time(19, 0) <= value <= time(21, 0):
        return "Заезд попадает в окно 19:00–21:00 без доплаты."
    if time(8, 0) <= value <= time(11, 0):
        return "Ранний заезд: оплачивается стоимость полного дня."
    if time(16, 30) <= value < time(19, 0):
        return "Заезд с 16:30 до 19:00: 50% стоимости полного дня (индивидуальный случай, как перерыв)."
    if value < time(8, 0):
        return "Заезд до 08:00: доплата 15% за каждый час; итог подтвердит администратор."
    if value > time(21, 0):
        return "Заезд после 21:00: доплата 15% за каждый час; итог подтвердит администратор."
    return "Заезд до 16:30: доплата 15% за каждый час; итог подтвердит администратор."
