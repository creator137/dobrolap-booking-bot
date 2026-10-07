from __future__ import annotations

from pathlib import Path

import yaml

from dobrolap_bot.domain.models import Accommodation, DailyRate, PriceRule, ServiceOffering


class Catalog:
    def __init__(
        self,
        accommodations: list[Accommodation],
        daily_rates: list[DailyRate],
        services: list[ServiceOffering],
        price_rules: list[PriceRule],
        deposit_base_rub: int = 2000,
        deposit_extra_pet_rub: int = 500,
    ) -> None:
        self.accommodations = accommodations
        self.daily_rates = daily_rates
        self.services = services
        self.price_rules = price_rules
        self.deposit_base_rub = deposit_base_rub
        self.deposit_extra_pet_rub = deposit_extra_pet_rub
        self._acc_by_id = {a.id: a for a in accommodations}
        self._svc_by_id = {s.id: s for s in services}

    def get_accommodation(self, unit_id: str) -> Accommodation | None:
        return self._acc_by_id.get(unit_id)

    def get_service(self, service_id: str) -> ServiceOffering | None:
        return self._svc_by_id.get(service_id)

    def active_accommodations(self) -> list[Accommodation]:
        return [a for a in self.accommodations if a.active]


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def load_catalog(config_dir: Path) -> Catalog:
    acc_raw = _load_yaml(config_dir / "accommodations.yaml")
    svc_raw = _load_yaml(config_dir / "services.yaml")
    rules_raw = _load_yaml(config_dir / "price_rules.yaml")

    accommodations = [Accommodation.model_validate(x) for x in acc_raw.get("accommodations", [])]
    daily_rates = [DailyRate.model_validate(x) for x in acc_raw.get("daily_rates", [])]
    services = [ServiceOffering.model_validate(x) for x in svc_raw.get("services", [])]
    price_rules = [PriceRule.model_validate(x) for x in rules_raw.get("price_rules", [])]
    deposit = rules_raw.get("deposit", {})

    return Catalog(
        accommodations=accommodations,
        daily_rates=daily_rates,
        services=services,
        price_rules=price_rules,
        deposit_base_rub=int(deposit.get("base_rub", 2000)),
        deposit_extra_pet_rub=int(deposit.get("extra_pet_rub", 500)),
    )
