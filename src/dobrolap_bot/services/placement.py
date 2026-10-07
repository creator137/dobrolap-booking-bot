from __future__ import annotations

from dobrolap_bot.config.loader import Catalog
from dobrolap_bot.domain.enums import PetKind
from dobrolap_bot.domain.models import (
    Accommodation,
    PetProfile,
    PlacementCandidate,
    PlacementResult,
)

# Features that satisfy "no furniture / moisture-resistant" for marking/chewing cats.
FURNITURE_SAFE_FEATURES = frozenset({"no_furniture", "moisture_resistant", "cage", "enclosure"})
VIP_TARIFFS = frozenset({"vip", "vip_plus"})


class PlacementService:
    """Deterministic placement filter. Never invents availability or medical clearance."""

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog

    def suggest(
        self,
        pets: list[PetProfile],
        *,
        occupied_unit_ids: set[str] | None = None,
        limit: int = 5,
    ) -> PlacementResult:
        occupied_unit_ids = occupied_unit_ids or set()
        owner_flags: list[str] = []
        requires_manual = False

        if not pets:
            return PlacementResult(
                candidates=[],
                requires_manual_matching=True,
                owner_flags=["empty_pet_list"],
            )

        if len(pets) > 1:
            owner_flags.append("multi_pet_group")
            # Do not assume co-housing is allowed.
            requires_manual = True

        # Small animals: simplified flow → always manual.
        if any(p.kind not in (PetKind.DOG, PetKind.CAT) for p in pets):
            owner_flags.append("non_dog_cat_species")
            requires_manual = True

        for pet in pets:
            owner_flags.extend(self._pet_owner_flags(pet))

        if any(f.startswith("needs_review:") for f in owner_flags):
            requires_manual = True

        # Intersection of per-pet candidate sets (for multi-pet we still list
        # units allowed for *every* pet, but flag manual confirmation).
        per_pet: list[list[PlacementCandidate]] = []
        for pet in pets:
            per_pet.append(self._candidates_for_pet(pet, occupied_unit_ids))

        if not per_pet or any(not c for c in per_pet):
            return PlacementResult(
                candidates=[],
                requires_manual_matching=True,
                owner_flags=owner_flags + ["no_matching_units"],
            )

        common_ids = set(c.accommodation.id for c in per_pet[0])
        for group in per_pet[1:]:
            common_ids &= {c.accommodation.id for c in group}

        if not common_ids:
            return PlacementResult(
                candidates=[],
                requires_manual_matching=True,
                owner_flags=owner_flags + ["no_shared_unit_for_group"],
            )

        # Merge scores/reasons from first pet as primary ranking signal.
        by_id = {c.accommodation.id: c for c in per_pet[0]}
        merged: list[PlacementCandidate] = []
        for unit_id in common_ids:
            base = by_id[unit_id]
            if requires_manual:
                base = base.model_copy(update={"requires_owner_review": True})
            merged.append(base)

        merged.sort(key=lambda c: (-c.score, c.accommodation.name))
        top = merged[:limit]

        if not top:
            requires_manual = True

        return PlacementResult(
            candidates=top,
            requires_manual_matching=requires_manual or not top,
            owner_flags=sorted(set(owner_flags)),
        )

    def _pet_owner_flags(self, pet: PetProfile) -> list[str]:
        flags: list[str] = []
        b = pet.behavior
        if pet.parasite_treated is False:
            flags.append("needs_review:parasite_not_treated")
        if pet.kind == PetKind.DOG and (
            b.aggression or b.high_stress or b.mobility_limited or b.needs_treatment
        ):
            flags.append("needs_review:dog_special_condition")
        if pet.vaccinated is False and pet.kind == PetKind.DOG:
            flags.append("needs_review:dog_unvaccinated")
        if pet.health_notes:
            flags.append("needs_review:health_notes")
        return flags

    def _candidates_for_pet(
        self,
        pet: PetProfile,
        occupied_unit_ids: set[str],
    ) -> list[PlacementCandidate]:
        out: list[PlacementCandidate] = []
        for unit in self.catalog.active_accommodations():
            if unit.id in occupied_unit_ids:
                continue
            candidate = self._evaluate(pet, unit)
            if candidate is not None:
                out.append(candidate)
        return out

    def _evaluate(self, pet: PetProfile, unit: Accommodation) -> PlacementCandidate | None:
        if pet.kind not in unit.allowed_species:
            return None

        if unit.weight_min_kg is not None and pet.weight_kg is not None:
            if pet.weight_kg < unit.weight_min_kg:
                return None
        if unit.weight_max_kg is not None and pet.weight_kg is not None:
            if pet.weight_kg > unit.weight_max_kg:
                return None

        # Hard cat rules
        if pet.kind == PetKind.CAT:
            if not self._cat_allowed(pet, unit):
                return None

        # Tariff must exist for this pet class (when rate matrix says unavailable)
        if not self._tariff_offered(pet, unit.tariff_kind):
            return None

        # Ordinary VIP without PDF price: allow listing but force review / no auto quote later
        warnings: list[str] = []
        requires_review = False
        if unit.tariff_kind == "vip":
            warnings.append("ordinary_vip_price_unconfirmed")
            requires_review = True

        score, reasons = self._score(pet, unit)
        if pet.kind not in (PetKind.DOG, PetKind.CAT):
            requires_review = True

        return PlacementCandidate(
            accommodation=unit,
            score=score,
            reasons=reasons,
            warnings=warnings,
            requires_owner_review=requires_review,
        )

    def _cat_allowed(self, pet: PetProfile, unit: Accommodation) -> bool:
        b = pet.behavior
        needs_vip = (
            pet.vaccinated is False
            or b.zoo_aggression
            or b.high_stress
            or b.distrust_humans
        )
        if needs_vip and unit.tariff_kind not in VIP_TARIFFS:
            return False

        if b.marks_territory or b.chews_furniture:
            feature_set = set(unit.features)
            if feature_set & FURNITURE_SAFE_FEATURES:
                return True
            # private VIP rooms assumed safer / configurable surfaces
            if unit.tariff_kind in VIP_TARIFFS:
                return True
            if "furniture" in feature_set:
                return False
        return True

    def _tariff_offered(self, pet: PetProfile, tariff_kind: str) -> bool:
        size = pet.dog_size
        young = pet.is_puppy_or_kitten
        matches = [
            r
            for r in self.catalog.daily_rates
            if r.accommodation_tariff == tariff_kind
            and r.pet_kind == pet.kind
            and r.is_young == young
            and (pet.kind != PetKind.DOG or r.size_class == size)
        ]
        if not matches:
            # No explicit row — allow physical rooms mapped to comfort etc.
            # only if some rate exists for this tariff+kind (ignore young/size miss → soft allow)
            any_kind = [
                r
                for r in self.catalog.daily_rates
                if r.accommodation_tariff == tariff_kind and r.pet_kind == pet.kind
            ]
            return bool(any_kind) and not all(r.unavailable for r in any_kind)

        return not all(r.unavailable for r in matches)

    def _score(self, pet: PetProfile, unit: Accommodation) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []
        tags = set(unit.priority_tags)
        b = pet.behavior

        if b.elderly or b.incontinence:
            if "elderly" in tags or "incontinence" in tags:
                score += 30
                reasons.append("priority:elderly_or_incontinence")
        if b.needs_treatment or b.disability:
            if "treatment" in tags or "disability" in tags:
                score += 30
                reasons.append("priority:treatment_or_disability")
        if b.loud_barking and ("loud_barking" in tags or "separate_house" in tags):
            score += 25
            reasons.append("priority:loud_barking_separate_house")

        if pet.kind == PetKind.CAT and (
            pet.vaccinated is False or b.zoo_aggression or b.high_stress or b.distrust_humans
        ):
            if "vip" in tags or unit.tariff_kind in VIP_TARIFFS:
                score += 20
                reasons.append("cat_requires_vip")

        if unit.seasonal:
            score -= 5
            reasons.append("seasonal_unit")

        return score, reasons
