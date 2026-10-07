from __future__ import annotations

from datetime import date, datetime

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


def parse_yes(text: str) -> bool | None:
    t = text.strip().lower()
    if t in {"да", "yes", "y", "+"}:
        return True
    if t in {"нет", "no", "n", "-"}:
        return False
    return None


def is_young(kind: PetKind, age_months: int | None) -> bool:
    """Puppy < 12 months; kitten < 7 months (from price sheet)."""
    if age_months is None:
        return False
    if kind == PetKind.DOG:
        return age_months < 12
    if kind == PetKind.CAT:
        return age_months < 7
    return False


# Backwards-compatible aliases for tests
_parse_dates = parse_dates
_yes = parse_yes
