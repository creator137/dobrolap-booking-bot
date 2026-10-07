"""Optional LLM adapter — disabled by default. Stub only in this phase."""

from __future__ import annotations

from typing import Any, Protocol


class LlmAdapter(Protocol):
    async def extract_pet_signals(self, text: str) -> dict[str, Any]: ...

    async def summarize_booking(self, payload: dict[str, Any]) -> str: ...


class DisabledLlmAdapter:
    async def extract_pet_signals(self, text: str) -> dict[str, Any]:
        return {}

    async def summarize_booking(self, payload: dict[str, Any]) -> str:
        return ""
