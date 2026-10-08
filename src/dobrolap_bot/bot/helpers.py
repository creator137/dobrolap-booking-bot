from __future__ import annotations

from datetime import date, datetime, time
import re

from dobrolap_bot.domain.enums import FeedingOption, PetKind


KIND_MAP = {
    "собака": PetKind.DOG,
    "кошка": PetKind.CAT,
    "кролик": PetKind.RABBIT,
    "крыса": PetKind.RAT,
    "хомяк": PetKind.HAMSTER,
    "птица": PetKind.BIRD,
    "морская свинка": PetKind.GUINEA_PIG,
    "свинка": PetKind.GUINEA_PIG,
    "другое": PetKind.OTHER,
}

FEED_MAP = {
    "корм владельца": FeedingOption.OWNER_FOOD,
    "рацион гостиницы": FeedingOption.HOTEL_RATION,
    "натуральное с приготовлением": FeedingOption.NATURAL_COOKED,
}


def parse_dates(text: str) -> tuple[date, date] | None:
    text = text.strip().replace("—", "-").replace("–", "-")
    parts = [p.strip() for p in text.split("-")]
    if len(parts) != 2:
        return None
    try:
        d1 = datetime.strptime(parts[0], "%d.%m.%Y").date()
        d2 = datetime.strptime(parts[1], "%d.%m.%Y").date()
    except ValueError:
        return None
    if d2 <= d1:
        return None
    return d1, d2


def parse_time(text: str) -> time | None:
    value = text.strip().replace(".", ":")
    if re.fullmatch(r"\d{1,2}", value):
        value += ":00"
    if not re.fullmatch(r"\d{1,2}:\d{2}", value):
        return None
    hours, minutes = (int(part) for part in value.split(":"))
    if hours > 23 or minutes > 59:
        return None
    return time(hours, minutes)


def parse_yes(text: str) -> bool | None:
    t = text.strip().lower()
    if t in {"да", "yes", "y", "+"}:
        return True
    if t in {"нет", "no", "n", "-"}:
        return False
    return None


def is_young(kind: PetKind, age_months: int | None) -> bool:
    """Puppy through 12 months; kitten under 7 months (2026 price sheet)."""
    if age_months is None:
        return False
    if kind == PetKind.DOG:
        return age_months <= 12
    if kind == PetKind.CAT:
        return age_months < 7
    return False


def normalize_phone(text: str) -> str | None:
    raw = text.strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) < 10 or len(digits) > 15:
        return None
    return "+" + digits


def parse_age_months(text: str) -> int | None:
    value = text.strip().lower().replace("ё", "е")
    weeks_match = re.fullmatch(r"(\d+)\s*нед(?:ел(?:я|и|ь)?)?", value)
    if weeks_match:
        weeks = int(weeks_match.group(1))
        return 0 if 0 < weeks < 4 else None
    if value in {"меньше месяца", "до месяца", "менее месяца"}:
        return 0
    if value.isdigit():
        months = int(value)
        return months if 0 <= months <= 400 else None
    years_match = re.search(r"(\d+)\s*(?:г(?:од(?:а|ов)?)?|лет)", value)
    months_match = re.search(r"(\d+)\s*мес", value)
    if not years_match and not months_match:
        return None
    years = int(years_match.group(1)) if years_match else 0
    months = int(months_match.group(1)) if months_match else 0
    total = years * 12 + months
    return total if 0 <= total <= 400 and months < 12 else None


# Backwards-compatible aliases for tests
_parse_dates = parse_dates
_yes = parse_yes
