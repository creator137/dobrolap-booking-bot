"""Constrained pet-text extraction. Business decisions stay deterministic."""

from __future__ import annotations

import logging
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)
PetField = Literal["age", "behavior", "health"]
BEHAVIOR_FIELDS = frozenset({
    "aggression", "zoo_aggression", "high_stress", "distrust_humans",
    "marks_territory", "chews_furniture", "loud_barking", "elderly",
    "mobility_limited", "incontinence", "needs_treatment", "disability",
})
HEALTH_FIELDS = frozenset({
    "elderly", "mobility_limited", "incontinence", "needs_treatment", "disability",
})


class PetSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age_months: int | None = None
    behavior_flags: list[str] = Field(default_factory=list)
    health_flags: list[str] = Field(default_factory=list)
    needs_clarification: bool = False

    def for_field(self, field: PetField) -> "PetSignals":
        """Discard anything outside the requested step and allowed domain fields."""
        if field == "age":
            age = self.age_months
            return PetSignals(
                age_months=age if age is not None and 0 <= age <= 400 else None,
                needs_clarification=self.needs_clarification,
            )
        if field == "behavior":
            return PetSignals(
                behavior_flags=sorted(set(self.behavior_flags) & BEHAVIOR_FIELDS),
                needs_clarification=self.needs_clarification,
            )
        return PetSignals(
            health_flags=sorted(set(self.health_flags) & HEALTH_FIELDS),
            needs_clarification=self.needs_clarification,
        )


class LlmUnavailableError(RuntimeError):
    pass


class LlmAdapter(Protocol):
    async def extract_pet_signals(self, text: str, *, field: PetField) -> PetSignals: ...


class DisabledLlmAdapter:
    async def extract_pet_signals(self, text: str, *, field: PetField) -> PetSignals:
        raise LlmUnavailableError("llm_disabled")


class OpenAiLlmAdapter:
    """OpenAI Structured Outputs, with no access to catalogue or calendar."""

    def __init__(self, *, api_key: str, model: str, client: object | None = None) -> None:
        if not api_key or not model:
            raise ValueError("LLM_API_KEY and LLM_MODEL are required")
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, timeout=8.0, max_retries=0)
        self.client = client
        self.model = model

    async def extract_pet_signals(self, text: str, *, field: PetField) -> PetSignals:
        if not text.strip():
            return PetSignals()
        instructions = (
            "Extract only explicitly stated facts about this pet from the Russian text. "
            "Do not infer a diagnosis or turn negated traits into positive flags. "
            "Age must be integer months; return null if ambiguous. "
            "Behavior flags: aggression (aggression to humans), zoo_aggression (to animals), "
            "high_stress, distrust_humans, marks_territory, chews_furniture, loud_barking, "
            "elderly, mobility_limited, incontinence, needs_treatment, disability. "
            "Health flags: elderly, mobility_limited, incontinence, needs_treatment, disability. "
            "Use only these exact flag names. Return empty lists if unsupported or negated. "
            "Never choose accommodation, price, availability, vaccination or payment status. "
            f"The requested field is {field}; leave other fields empty. "
            "Set needs_clarification when the requested fact is unclear."
        )
        try:
            response = await self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": text[:2000]},
                ],
                text_format=PetSignals,
                store=False,
            )
            if response.output_parsed is None:
                raise LlmUnavailableError("llm_empty_or_refused")
            return PetSignals.model_validate(response.output_parsed).for_field(field)
        except Exception as exc:
            logger.warning("Pet text extraction unavailable: %s", type(exc).__name__)
            raise LlmUnavailableError("llm_unavailable") from exc


def build_llm_adapter(*, enabled: bool, api_key: str, model: str) -> LlmAdapter:
    if not enabled:
        return DisabledLlmAdapter()
    if not api_key or not model:
        logger.warning("LLM_ENABLED=true but LLM_API_KEY or LLM_MODEL is missing")
        return DisabledLlmAdapter()
    return OpenAiLlmAdapter(api_key=api_key, model=model)
