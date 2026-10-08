from __future__ import annotations

from types import SimpleNamespace

import pytest

from dobrolap_bot.bot.handlers import set_pet_age, set_behavior_text, set_health
from dobrolap_bot.bot.states import BookingForm
from dobrolap_bot.integrations.llm import (
    DisabledLlmAdapter, LlmUnavailableError, OpenAiLlmAdapter, PetSignals,
)


class FakeState:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.current = None

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, value):
        self.current = value


class FakeMessage:
    def __init__(self, text):
        self.text = text
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


@pytest.mark.asyncio
async def test_openai_adapter_accepts_only_requested_allowed_signals():
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_parsed=PetSignals(
            age_months=15,
            behavior_flags=["high_stress", "invented_room", "high_stress"],
            health_flags=["needs_treatment"],
        ))

    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    adapter = OpenAiLlmAdapter(api_key="test", model="test-model", client=client)
    result = await adapter.extract_pet_signals("Сильно стрессует", field="behavior")
    assert result.age_months is None
    assert result.health_flags == []
    assert result.behavior_flags == ["high_stress"]
    assert calls[0]["store"] is False
    assert calls[0]["text_format"] is PetSignals


@pytest.mark.asyncio
async def test_age_uses_safe_local_fallback_and_asks_confirmation():
    state = FakeState({"draft_kind": "dog"})
    message = FakeMessage("2 года 3 месяца")
    await set_pet_age(message, state, DisabledLlmAdapter())
    assert state.data["draft_age_candidate"] == 27
    assert state.current == BookingForm.pet_age_review
    assert "Верно" in message.answers[0][0]


@pytest.mark.asyncio
async def test_behavior_fallback_preserves_raw_text_without_guessing_flags():
    state = FakeState({"draft_kind": "dog", "draft_behavior_selected": []})
    message = FakeMessage("Не агрессивен, но боится транспорта")
    await set_behavior_text(message, state, DisabledLlmAdapter())
    assert state.data["draft_behavior_raw"] == message.text
    assert state.data["draft_behavior_selected"] == []
    assert state.current is None
    assert "кнопками" in message.answers[-1][0]


@pytest.mark.asyncio
async def test_health_text_is_preserved_and_only_allowed_flags_are_offered():
    class FakeLlm:
        async def extract_pet_signals(self, text, *, field):
            assert field == "health"
            return PetSignals(health_flags=["needs_treatment", "made_up"] ).for_field(field)

    state = FakeState({"draft_kind": "cat", "draft_behavior": {}})
    message = FakeMessage("Даю таблетки два раза в день")
    await set_health(message, state, FakeLlm())
    assert state.data["draft_health_candidate"] == message.text
    assert state.data["draft_health_flags_candidate"] == ["needs_treatment"]
    assert state.current == BookingForm.pet_health_review


@pytest.mark.asyncio
async def test_api_failure_falls_back():
    async def parse(**kwargs):
        raise TimeoutError()

    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    adapter = OpenAiLlmAdapter(api_key="test", model="test-model", client=client)
    with pytest.raises(LlmUnavailableError):
        await adapter.extract_pet_signals("1 год", field="age")
