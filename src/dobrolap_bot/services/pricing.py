from __future__ import annotations

from datetime import date

from dobrolap_bot.config.loader import Catalog
from dobrolap_bot.domain.enums import FeedingOption, PetKind, PriceScope
from dobrolap_bot.domain.models import (
    Accommodation,
    DailyRate,
    PetProfile,
    PriceQuote,
    QuoteLine,
    ServiceOffering,
)


class PricingService:
    """Pure pricing function: accommodation + services + feeding − discounts + deposit."""

    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog

    def quote(
        self,
        *,
        pets: list[PetProfile],
        unit: Accommodation,
        date_from: date,
        date_to: date,
        feeding: FeedingOption | None = None,
        service_ids: list[str] | None = None,
        promo_code: str | None = None,
    ) -> PriceQuote:
        if date_to <= date_from:
            raise ValueError("date_to must be after date_from")

        nights = (date_to - date_from).days
        lines: list[QuoteLine] = []
        provisional = False
        notes: list[str] = []

        # Accommodation: for multi-pet MVP we charge per pet against the same unit tariff
        # unless owner later defines co-housing pricing. Flag in explanation.
        if len(pets) > 1:
            notes.append(
                "Несколько питомцев: предварительный расчёт по каждому; "
                "совместное размещение подтверждает владелец."
            )

        for pet in pets:
            rate = self._find_rate(pet, unit.tariff_kind)
            if rate is None or rate.unavailable:
                provisional = True
                lines.append(
                    QuoteLine(
                        scope=PriceScope.ACCOMMODATION,
                        label=f"Проживание: {unit.name} / {pet.name}",
                        amount_rub=0,
                        detail="Тариф не найден или недоступен — нужно ручное подтверждение",
                        provisional=True,
                    )
                )
                continue

            day_price, day_provisional, detail = self._day_amount(rate)
            if unit.tariff_kind == "vip":
                provisional = True
                detail = (detail or "") + "; обычный VIP без цены в PDF"
            amount = day_price * nights
            provisional = provisional or day_provisional
            lines.append(
                QuoteLine(
                    scope=PriceScope.ACCOMMODATION,
                    label=f"Проживание {nights} сут.: {unit.name} / {pet.name}",
                    amount_rub=amount,
                    detail=detail,
                    provisional=day_provisional or unit.tariff_kind == "vip",
                )
            )

        # Feeding
        if feeding == FeedingOption.NATURAL_COOKED:
            # Unit of billing unknown — quote lower bound × nights as provisional
            feed_from = 150
            amount = feed_from * nights * max(len(pets), 1)
            provisional = True
            lines.append(
                QuoteLine(
                    scope=PriceScope.FEEDING,
                    label="Натуральное питание (ориентир)",
                    amount_rub=amount,
                    detail="150–250 ₽, единица тарификации не подтверждена; взята нижняя граница × сутки × питомцы",
                    provisional=True,
                )
            )
        elif feeding == FeedingOption.HOTEL_RATION:
            provisional = True
            lines.append(
                QuoteLine(
                    scope=PriceScope.FEEDING,
                    label="Готовый рацион гостиницы",
                    amount_rub=0,
                    detail="Цена рациона не задана в материалах",
                    provisional=True,
                )
            )
        elif feeding == FeedingOption.OWNER_FOOD:
            lines.append(
                QuoteLine(
                    scope=PriceScope.FEEDING,
                    label="Корм владельца",
                    amount_rub=0,
                    detail="Без доплаты за корм",
                )
            )

        # Services — use lower bound of range as provisional quote
        for sid in service_ids or []:
            svc = self.catalog.get_service(sid)
            if svc is None or not svc.active:
                continue
            amount, svc_provisional = self._service_amount(svc)
            provisional = provisional or svc_provisional
            lines.append(
                QuoteLine(
                    scope=PriceScope.SERVICE,
                    label=svc.name,
                    amount_rub=amount,
                    detail=svc.notes,
                    provisional=svc_provisional,
                )
            )

        accommodation_subtotal = sum(
            ln.amount_rub for ln in lines if ln.scope == PriceScope.ACCOMMODATION
        )

        # Promo / discounts (active rules only)
        discount_lines = self._apply_discounts(
            accommodation_subtotal=accommodation_subtotal,
            date_from=date_from,
            promo_code=promo_code,
        )
        lines.extend(discount_lines)

        total = sum(ln.amount_rub for ln in lines)
        deposit = self.deposit_amount(len(pets))

        explanation_parts = [
            f"Суток: {nights}.",
            f"Залог отдельно: {deposit} ₽ "
            f"(база {self.catalog.deposit_base_rub} + "
            f"{self.catalog.deposit_extra_pet_rub} × доп. питомцы).",
            "Полная стоимость проживания оплачивается при заезде.",
        ]
        explanation_parts.extend(notes)
        if provisional:
            explanation_parts.append(
                "Часть сумм ориентировочная и требует подтверждения владельцем."
            )

        return PriceQuote(
            lines=lines,
            total_rub=total,
            deposit_rub=deposit,
            explanation=" ".join(explanation_parts),
            provisional=provisional,
        )

    def deposit_amount(self, pet_count: int) -> int:
        if pet_count < 1:
            pet_count = 1
        extra = max(pet_count - 1, 0)
        return self.catalog.deposit_base_rub + extra * self.catalog.deposit_extra_pet_rub

    def _find_rate(self, pet: PetProfile, tariff_kind: str) -> DailyRate | None:
        size = pet.dog_size
        young = pet.is_puppy_or_kitten
        exact = [
            r
            for r in self.catalog.daily_rates
            if r.accommodation_tariff == tariff_kind
            and r.pet_kind == pet.kind
            and r.is_young == young
            and (pet.kind != PetKind.DOG or r.size_class == size)
        ]
        if exact:
            return exact[0]
        # Fallback: adult rate if young missing
        if young:
            return self._find_rate(
                pet.model_copy(update={"is_puppy_or_kitten": False}),
                tariff_kind,
            )
        return None

    def _day_amount(self, rate: DailyRate) -> tuple[int, bool, str | None]:
        if rate.price_rub is not None:
            return rate.price_rub, False, None
        if rate.price_from_rub is not None:
            upper = f"–{rate.price_to_rub}" if rate.price_to_rub else "+"
            return (
                rate.price_from_rub,
                True,
                f"Диапазон {rate.price_from_rub}{upper} ₽/сут., в расчёте нижняя граница",
            )
        return 0, True, "Цена не задана"

    def _service_amount(self, svc: ServiceOffering) -> tuple[int, bool]:
        if svc.price_from_rub is not None and svc.price_to_rub is not None:
            if svc.price_from_rub != svc.price_to_rub:
                return svc.price_from_rub, True
            return svc.price_from_rub, False
        if svc.price_from_rub is not None:
            return svc.price_from_rub, True
        return 0, True

    def _apply_discounts(
        self,
        *,
        accommodation_subtotal: int,
        date_from: date,
        promo_code: str | None,
    ) -> list[QuoteLine]:
        lines: list[QuoteLine] = []
        rules = sorted(
            [r for r in self.catalog.price_rules if r.active and r.scope == PriceScope.DISCOUNT],
            key=lambda r: r.priority,
        )
        applied_non_stackable = False
        for rule in rules:
            if applied_non_stackable and not rule.stackable:
                continue
            if rule.date_from and date_from < rule.date_from:
                continue
            if rule.date_to and date_from > rule.date_to:
                continue
            code = rule.condition.get("promo_code")
            if code:
                if not promo_code or promo_code.strip().upper() != str(code).upper():
                    continue
            amount = 0
            if rule.percent is not None:
                base = accommodation_subtotal
                if rule.condition.get("applies_to") == "accommodation":
                    base = accommodation_subtotal
                amount = -int(round(base * rule.percent / 100))
            elif rule.amount_rub is not None:
                amount = -abs(rule.amount_rub)
            else:
                continue
            if amount == 0:
                continue
            lines.append(
                QuoteLine(
                    scope=PriceScope.DISCOUNT,
                    label=rule.description or rule.id,
                    amount_rub=amount,
                    detail=f"rule:{rule.id}",
                )
            )
            if not rule.stackable:
                applied_non_stackable = True
        return lines
