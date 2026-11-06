from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from dobrolap_bot.config.loader import Catalog
from dobrolap_bot.domain.enums import FeedingOption, PriceScope
from dobrolap_bot.domain.models import (
    Accommodation,
    DailyRate,
    PetProfile,
    PriceQuote,
    QuoteLine,
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
        arrival_time: str | None = None,
        together: bool = True,
        room_assignments: list[dict] | None = None,
    ) -> PriceQuote:
        if date_to <= date_from:
            raise ValueError("date_to must be after date_from")

        nights = (date_to - date_from).days
        lines: list[QuoteLine] = []
        provisional = False
        notes: list[str] = []
        is_season = self.catalog.is_season_date(date_from)
        if is_season:
            notes.append("Период заезда входит в сезон отпусков/праздников — цены по сезонному прайсу.")

        multi_pet_discount_rate = 0.5 if together else 0.3
        multi_pet_discount_pct = int(multi_pet_discount_rate * 100)
        if len(pets) > 1:
            placement_word = "Совместное" if together else "Раздельное"
            notes.append(
                f"{placement_word} размещение: скидка {multi_pet_discount_pct}% на проживание "
                "второго и каждого следующего питомца."
            )

        shared_pet_discount = 0
        pet_units: dict[int, Accommodation | None] = {index: unit for index in range(len(pets))}
        pet_discount_rates = {index: (multi_pet_discount_rate if index else 0) for index in range(len(pets))}
        if room_assignments:
            if len(room_assignments) > 1 and any(len(item["pet_indices"]) > 1 for item in room_assignments):
                notes = [note for note in notes if "размещение: скидка" not in note]
                notes.append(
                    "Частичное размещение: 50% на дополнительных питомцев в общей комнате, "
                    "30% на первого питомца в каждой следующей отдельной комнате."
                )
            indices = [index for item in room_assignments for index in item["pet_indices"]]
            if sorted(indices) != list(range(len(pets))):
                raise ValueError("incomplete_room_assignments")
            for group_index, item in enumerate(room_assignments):
                raw_unit_id = item.get("unit_id")
                if item.get("manual") or not raw_unit_id:
                    provisional = True
                    notes.append(
                        "Часть питомцев без автоматического помещения — цену подтвердит оператор."
                    )
                    for index in item["pet_indices"]:
                        pet_units[index] = None
                        pet_discount_rates[index] = 0
                    continue
                assigned_unit = self.catalog.get_accommodation(raw_unit_id)
                if assigned_unit is None:
                    raise ValueError("unknown_unit")
                for position, index in enumerate(item["pet_indices"]):
                    pet_units[index] = assigned_unit
                    pet_discount_rates[index] = 0.5 if position else (0.3 if group_index else 0)
        tariff_subtotals: dict[str, int] = {}
        for pet_index, pet in enumerate(pets):
            unit = pet_units[pet_index]
            if unit is None:
                provisional = True
                lines.append(
                    QuoteLine(
                        scope=PriceScope.ACCOMMODATION,
                        label=f"Проживание: подбор оператора / {pet.name}",
                        amount_rub=0,
                        detail="Помещение и стоимость подтвердит руководитель зоогостиницы",
                        provisional=True,
                    )
                )
                continue
            if unit.tariff_unconfirmed:
                provisional = True
                lines.append(
                    QuoteLine(
                        scope=PriceScope.ACCOMMODATION,
                        label=f"Проживание: {unit.name} / {pet.name}",
                        amount_rub=0,
                        detail="Тариф этого помещения не подтверждён руководителем зоогостиницы",
                        provisional=True,
                    )
                )
                continue
            rate = self._find_rate(pet, unit.rate_tariff_kind or unit.tariff_kind)
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

            day_price, day_provisional, detail = self._day_amount(rate, use_season=is_season)
            if unit.rate_adjustment_rub:
                day_price = max(0, day_price + unit.rate_adjustment_rub)
                detail = (detail or "") + f"; корректировка тарифа {unit.rate_adjustment_rub:+} ₽/сутки"
            if unit.tariff_kind == "vip" and not unit.rate_tariff_kind:
                provisional = True
                detail = (detail or "") + "; обычный VIP без отдельной тарифной колонки в XLSX"
            amount = day_price * nights
            discount_rate = pet_discount_rates[pet_index]
            discount_pct = int(discount_rate * 100)
            tariff_subtotals[unit.tariff_kind] = tariff_subtotals.get(unit.tariff_kind, 0) + amount - int(amount * discount_rate)
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
            if discount_rate > 0:
                discount = int(amount * discount_rate)
                shared_pet_discount -= discount
                lines.append(
                    QuoteLine(
                        scope=PriceScope.DISCOUNT,
                        label=f"Скидка {discount_pct}% на размещение питомца: {pet.name}",
                        amount_rub=-discount,
                        detail="Скидка на второго и каждого следующего питомца; лимит акции за отзывы к ней не относится",
                    )
                )

        # Feeding
        if feeding in {FeedingOption.NATURAL_COOKED, FeedingOption.NATURAL_READY, FeedingOption.NATURAL_PORRIDGE}:
            feed_rate = 150 if feeding == FeedingOption.NATURAL_READY else 250
            amount = feed_rate * nights * max(len(pets), 1)
            lines.append(
                QuoteLine(
                    scope=PriceScope.FEEDING,
                    label="Натуральное питание",
                    amount_rub=amount,
                    detail=f"{feed_rate} ₽ за сутки. Продукты предоставляет хозяин питомца либо гостиница покупает с передачей чеков.",
                )
            )
        elif feeding == FeedingOption.HOTEL_RATION:
            provisional = True
            lines.append(
                QuoteLine(
                    scope=PriceScope.FEEDING,
                    label="Готовый рацион гостиницы",
                    amount_rub=0,
                    detail="Платный рацион; стоимость рассчитывается индивидуально и добавляется к проживанию",
                    provisional=True,
                )
            )
        elif feeding == FeedingOption.OWNER_FOOD:
            lines.append(
                QuoteLine(
                    scope=PriceScope.FEEDING,
                    label="Свой корм",
                    amount_rub=0,
                    detail="Без доплаты за корм",
                )
            )

        # Services — lower bound of range; multiply by nights for per_day units
        for sid in service_ids or []:
            svc = self.catalog.get_service(sid)
            if svc is None or not svc.active:
                continue
            svc_provisional = True
            provisional = True
            detail = "Стоимость сообщит оператор после уточнения деталей услуги"
            note = ", ".join(x for x in [svc.notes, detail] if x)
            lines.append(
                QuoteLine(
                    scope=PriceScope.SERVICE,
                    label=svc.name,
                    amount_rub=0,
                    detail=note or None,
                    provisional=svc_provisional,
                )
            )

        accommodation_subtotal = sum(
            ln.amount_rub for ln in lines if ln.scope == PriceScope.ACCOMMODATION
        ) + shared_pet_discount

        try:
            parsed_arrival = time.fromisoformat(arrival_time) if arrival_time else None
        except ValueError:
            parsed_arrival = None
        arrival_fraction = 0
        arrival_label = ""
        if parsed_arrival and time(16, 30) <= parsed_arrival < time(19, 0):
            arrival_fraction = 0.5
            arrival_label = "Заезд 16:30–19:00 (50% суточной стоимости)"
        elif parsed_arrival and time(8, 0) <= parsed_arrival <= time(11, 0):
            arrival_fraction = 1
            arrival_label = "Заезд 08:00–11:00 (полная стоимость суток)"
        if arrival_fraction:
            half_day_total = 0
            for pet_index, pet in enumerate(pets):
                unit = pet_units[pet_index]
                if unit is None:
                    provisional = True
                    continue
                arrival_rate = self._find_rate(pet, unit.rate_tariff_kind or unit.tariff_kind)
                if arrival_rate is None or arrival_rate.unavailable:
                    provisional = True
                    continue
                daily, is_provisional, _ = self._day_amount(arrival_rate, use_season=is_season)
                half_day_total += int(max(0, daily + unit.rate_adjustment_rub) * arrival_fraction)
                provisional = provisional or is_provisional
            if half_day_total:
                lines.append(QuoteLine(
                    scope=PriceScope.SURCHARGE,
                    label=arrival_label,
                    amount_rub=half_day_total,
                    detail="Индивидуальный случай, рассчитывается как перерыв",
                ))

        # Promo / discounts (active rules only)
        discount_lines = []
        for tariff, subtotal in tariff_subtotals.items():
            discount_lines.extend(self._apply_discounts(
                accommodation_subtotal=subtotal,
                on_date=promo_at or self.promo_today(),
                promo_code=promo_code,
                promo_eligible=promo_eligible,
                nights=nights,
                tariff_kind=tariff,
                max_actions=1 if len(pets) > 1 else 2,
            ))
        lines.extend(discount_lines)
        if len(pets) > 1 and promo_eligible and nights >= 30:
            provisional = True
            notes.append("При сочетании скидки на питомцев, промокода и длительного размещения окончательную сумму определит оператор: не более двух акций.")

        total = sum(ln.amount_rub for ln in lines)
        deposit = self.deposit_amount(len(pets))
        accommodation_gross = sum(
            ln.amount_rub for ln in lines if ln.scope == PriceScope.ACCOMMODATION
        )
        accommodation_net = accommodation_gross + sum(
            ln.amount_rub for ln in lines if ln.scope == PriceScope.DISCOUNT
        )
        day_net = accommodation_net // nights if nights else accommodation_net
        day_gross = accommodation_gross // nights if nights else accommodation_gross

        explanation_parts = [f"Суток: {nights}."]
        if accommodation_gross:
            if accommodation_gross != accommodation_net:
                explanation_parts.append(
                    f"≈ {day_net} ₽/сут. проживания со скидкой "
                    f"(без скидки ≈ {day_gross} ₽/сут.)."
                )
            else:
                explanation_parts.append(f"≈ {day_net} ₽/сут. проживания.")
        explanation_parts.extend(
            [
                f"Залог отдельно: {deposit} ₽ "
                f"(база {self.catalog.deposit_base_rub} + "
                f"{self.catalog.deposit_extra_pet_rub} × доп. питомцы).",
                "Полная стоимость проживания оплачивается при заезде.",
            ]
        )
        explanation_parts.extend(notes)
        if provisional:
            explanation_parts.append(
                "Часть сумм ориентировочная и требует подтверждения руководителем зоогостиницы."
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
        exact = [
            r
            for r in self.catalog.daily_rates
            if r.matches_pet(pet, tariff_kind)
        ]
        if exact:
            return exact[0]
        return None

    def _day_amount(self, rate: DailyRate, *, use_season: bool = False) -> tuple[int, bool, str | None]:
        if use_season and rate.price_rub_season is not None:
            return rate.price_rub_season, False, "Сезонная цена (отпуска/праздники)"
        if use_season and rate.price_from_rub_season is not None:
            upper = f"–{rate.price_to_rub_season}" if rate.price_to_rub_season else "+"
            return (
                rate.price_from_rub_season,
                True,
                f"Сезонный диапазон {rate.price_from_rub_season}{upper} ₽/сут., в расчёте нижняя граница",
            )
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

    def _apply_discounts(
        self,
        *,
        accommodation_subtotal: int,
        on_date: date,
        promo_code: str | None,
        promo_eligible: bool,
        nights: int,
        tariff_kind: str,
        max_actions: int,
    ) -> list[QuoteLine]:
        lines: list[QuoteLine] = []
        rules = sorted(
            [r for r in self.catalog.price_rules if r.active and r.scope == PriceScope.DISCOUNT],
            key=lambda r: (0 if max_actions == 1 and r.condition.get("min_nights") else 1, r.priority),
        )
        applied_non_stackable = False
        promo_rule = (
            self.find_active_promo(promo_code, on_date=on_date)
            if promo_code and promo_eligible else None
        )
        for rule in rules:
            if len(lines) >= max_actions or applied_non_stackable:
                continue
            if lines and not rule.stackable:
                continue
            if rule.date_from and on_date < rule.date_from:
                continue
            if rule.date_to and on_date > rule.date_to:
                continue
            min_nights = rule.condition.get("min_nights")
            if min_nights is not None and nights < int(min_nights):
                continue
            tariff_kinds = rule.condition.get("tariff_kinds")
            if tariff_kinds and tariff_kind not in tariff_kinds:
                continue
            code = rule.condition.get("promo_code")
            if code:
                if rule is not promo_rule:
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
