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
    """Owner-confirmed dog weight bands: up to 10 kg, over 10 to under 20 kg, 20+ kg."""

    MINIATURE = "miniature"  # <= 10 kg
    MEDIUM = "medium"  # 10–20 kg
    LARGE = "large"  # >= 20 kg


class FeedingOption(StrEnum):
    OWNER_FOOD = "owner_food"
    HOTEL_RATION = "hotel_ration"
    NATURAL_COOKED = "natural_cooked"
    NATURAL_READY = "natural_ready"
    NATURAL_PORRIDGE = "natural_porridge"


class PriceScope(StrEnum):
    ACCOMMODATION = "accommodation"
    SERVICE = "service"
    FEEDING = "feeding"
    DEPOSIT = "deposit"
    DISCOUNT = "discount"
    SURCHARGE = "surcharge"
