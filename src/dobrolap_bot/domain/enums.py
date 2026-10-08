from enum import StrEnum


class BookingStatus(StrEnum):
    DRAFT = "DRAFT"
    WAITING_OWNER = "WAITING_OWNER"
    OWNER_APPROVED = "OWNER_APPROVED"
    WAITING_PAYMENT = "WAITING_PAYMENT"
    CONFIRMED = "CONFIRMED"
    OWNER_REJECTED = "OWNER_REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PetKind(StrEnum):
    DOG = "dog"
    CAT = "cat"
    RABBIT = "rabbit"
    RAT = "rat"
    HAMSTER = "hamster"
    BIRD = "bird"
    GUINEA_PIG = "guinea_pig"
    OTHER = "other"


class DogSizeClass(StrEnum):
    """Weight baskets from the current PDF price list.

    Boundary ownership (exactly 10 / 20 kg) still needs owner confirmation.
    Until then we use half-open intervals: [0, 10), [10, 20), [20, ∞).
    XLSX says large dogs start at 25 kg — that conflict is unresolved.
    """

    MINIATURE = "miniature"  # <= 10 kg
    MEDIUM = "medium"  # 10–20 kg
    LARGE = "large"  # >= 20 kg


class FeedingOption(StrEnum):
    OWNER_FOOD = "owner_food"
    HOTEL_RATION = "hotel_ration"
    NATURAL_COOKED = "natural_cooked"


class PriceScope(StrEnum):
    ACCOMMODATION = "accommodation"
    SERVICE = "service"
    FEEDING = "feeding"
    DEPOSIT = "deposit"
    DISCOUNT = "discount"
    SURCHARGE = "surcharge"
