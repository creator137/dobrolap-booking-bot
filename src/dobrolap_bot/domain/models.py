from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from dobrolap_bot.domain.enums import (
    BookingStatus,
    DogSizeClass,
    FeedingOption,
    PetKind,
    PriceScope,
)


class BehaviorFlags(BaseModel):
    aggression: bool = False
    zoo_aggression: bool = False
    high_stress: bool = False
    distrust_humans: bool = False
    marks_territory: bool = False
    chews_furniture: bool = False
    loud_barking: bool = False
    elderly: bool = False
    mobility_limited: bool = False
    incontinence: bool = False
    needs_treatment: bool = False
    disability: bool = False


class PetProfile(BaseModel):
    """In-memory / domain view of a pet during booking."""

    id: str | None = None
    kind: PetKind
    name: str
    age_months: int | None = None
    breed: str | None = None
    weight_kg: float | None = None
    is_puppy_or_kitten: bool = False
    vaccinated: bool | None = None
    vaccinated_until: date | None = None
    parasite_treated: bool | None = None
    behavior: BehaviorFlags = Field(default_factory=BehaviorFlags)
    health_notes: str | None = None
    passport_file_ids: list[str] = Field(default_factory=list)

    @property
    def dog_size(self) -> DogSizeClass | None:
        if self.kind != PetKind.DOG or self.weight_kg is None:
            return None
        if self.weight_kg < 10:
            return DogSizeClass.MINIATURE
        if self.weight_kg < 20:
            return DogSizeClass.MEDIUM
        return DogSizeClass.LARGE


class Accommodation(BaseModel):
    id: str
    name: str
    tariff_kind: str
    allowed_species: list[PetKind]
    weight_min_kg: float | None = None
    weight_max_kg: float | None = None
    features: list[str] = Field(default_factory=list)
    priority_tags: list[str] = Field(default_factory=list)
    photo_paths: list[str] = Field(default_factory=list)
    sheet_unit_id: str | None = None
    active: bool = True
    seasonal: bool = False
    notes: str | None = None


class DailyRate(BaseModel):
    """One cell of the accommodation price matrix."""

    accommodation_tariff: str
    pet_kind: PetKind
    size_class: DogSizeClass | None = None
    is_young: bool = False  # puppy / kitten
    price_rub: int | None = None
    price_from_rub: int | None = None
    price_to_rub: int | None = None
    unavailable: bool = False


class ServiceOffering(BaseModel):
    id: str
    name: str
    price_from_rub: int | None = None
    price_to_rub: int | None = None
    unit: str = "once"
    applies_to: list[PetKind] | None = None
    active: bool = True
    notes: str | None = None


class PriceRule(BaseModel):
    id: str
    scope: PriceScope
    date_from: date | None = None
    date_to: date | None = None
    condition: dict[str, Any] = Field(default_factory=dict)
    amount_rub: int | None = None
    percent: float | None = None
    priority: int = 100
    stackable: bool = False
    active: bool = True
    description: str = ""


class QuoteLine(BaseModel):
    scope: PriceScope
    label: str
    amount_rub: int
    detail: str | None = None
    provisional: bool = False


class PriceQuote(BaseModel):
    lines: list[QuoteLine]
    total_rub: int
    deposit_rub: int
    explanation: str
    provisional: bool = False


class PlacementCandidate(BaseModel):
    accommodation: Accommodation
    score: int = 0
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requires_owner_review: bool = False


class PlacementResult(BaseModel):
    candidates: list[PlacementCandidate]
    requires_manual_matching: bool = False
    owner_flags: list[str] = Field(default_factory=list)


class BookingDraft(BaseModel):
    customer_telegram_id: int
    customer_name: str | None = None
    customer_contact: str | None = None
    consent_at: datetime | None = None
    date_from: date
    date_to: date
    pets: list[PetProfile]
    unit_id: str | None = None
    feeding: FeedingOption | None = None
    selected_service_ids: list[str] = Field(default_factory=list)
    promo_code: str | None = None
    status: BookingStatus = BookingStatus.DRAFT
    owner_note: str | None = None
