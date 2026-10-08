from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from dobrolap_bot.config.loader import Catalog
from dobrolap_bot.domain.enums import FeedingOption, PetKind, PriceScope
from dobrolap_bot.domain.models import (
    Accommodation,
    DailyRate,
    PetProfile,
    PriceQuote,
    QuoteLine,
    ServiceOffering,
    PriceRule,
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
        promo_eligible: bool = False,
        promo_at: date | None = None,
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

        # Services — lower bound of range; multiply by nights for per_day units
        for sid in service_ids or []:
            svc = self.catalog.get_service(sid)
            if svc is None or not svc.active:
                continue
            amount, svc_provisional, detail = self._service_amount(svc, nights=nights)
            provisional = provisional or svc_provisional
            note = ", ".join(x for x in [svc.notes, detail] if x)
            lines.append(
                QuoteLine(
                    scope=PriceScope.SERVICE,
                    label=svc.name,
                    amount_rub=amount,
                    detail=note or None,
                    provisional=svc_provisional,
                )
            )

        accommodation_subtotal = sum(
            ln.amount_rub for ln in lines if ln.scope == PriceScope.ACCOMMODATION
        )

        # Promo / discounts (active rules only)
        discount_lines = self._apply_discounts(
            accommodation_subtotal=accommodation_subtotal,
            on_date=promo_at or self.promo_today(),
            promo_code=promo_code,
            promo_eligible=promo_eligible,
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

    @staticmethod
    def promo_today() -> date:
        return datetime.now(ZoneInfo("Asia/Yekaterinburg")).date()

    def find_active_promo(
        self, promo_code: str, *, on_date: date | None = None, date_from: date | None = None
    ) -> PriceRule | None:
        """Return a currently applicable promo rule without changing quote semantics."""
        valid_on = on_date or date_from or self.promo_today()
        normalized = promo_code.strip().upper()
        if not normalized:
            return None
        for rule in self.catalog.price_rules:
            if not rule.active or rule.scope != PriceScope.DISCOUNT:
                continue
            configured = rule.condition.get("promo_code")
            if not configured or normalized != str(configured).strip().upper():
                continue
            if rule.date_from and valid_on < rule.date_from:
                continue
            if rule.date_to and valid_on > rule.date_to:
                continue
            if rule.percent is None and rule.amount_rub is None:
                continue
            return rule
        return None

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

    def _service_amount(
        self, svc: ServiceOffering, *, nights: int
    ) -> tuple[int, bool, str | None]:
        base: int | None = None
        provisional = False
        if svc.price_from_rub is not None and svc.price_to_rub is not None:
            base = svc.price_from_rub
            provisional = svc.price_from_rub != svc.price_to_rub
        elif svc.price_from_rub is not None:
            base = svc.price_from_rub
            provisional = True
        else:
            return 0, True, "Цена не задана"

        unit = (svc.unit or "once").lower()
        if unit in {"per_day", "day", "сутки", "сут"}:
            return base * max(nights, 1), provisional, f"{base} ₽ × {nights} сут."
        if unit in {"visit", "session", "one_way", "once", "unclear"}:
            # Quantity UI not collected yet — quote one unit; mark unclear as provisional.
            return base, provisional or unit == "unclear", f"единица: {unit}"
        return base, True, f"неизвестная единица тарификации: {unit}"

    def _apply_discounts(
        self,
        *,
        accommodation_subtotal: int,
        on_date: date,
        promo_code: str | None,
        promo_eligible: bool,
    ) -> list[QuoteLine]:
        lines: list[QuoteLine] = []
        rules = sorted(
            [r for r in self.catalog.price_rules if r.active and r.scope == PriceScope.DISCOUNT],
            key=lambda r: r.priority,
        )
        applied_non_stackable = False
        promo_rule = (
            self.find_active_promo(promo_code, on_date=on_date)
            if promo_code and promo_eligible else None
        )
        if promo_rule is not None:
            # A non-stackable promo excludes every other discount.
            rules = [promo_rule]
        for rule in rules:
            if applied_non_stackable and not rule.stackable:
                continue
            if rule.date_from and on_date < rule.date_from:
                continue
            if rule.date_to and on_date > rule.date_to:
                continue
            code = rule.condition.get("promo_code")
            if code:
                if not promo_eligible or not promo_code or promo_code.strip().upper() != str(code).upper():
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
