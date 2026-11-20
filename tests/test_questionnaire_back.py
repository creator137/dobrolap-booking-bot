from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dobrolap_bot.bot import handlers as h
from dobrolap_bot.bot.states import BookingForm
from dobrolap_bot.domain.enums import PetKind
from test_client_ux import State


def message(text=""):
    return SimpleNamespace(text=text, answer=AsyncMock(), answer_photo=AsyncMock())


@pytest.mark.asyncio
async def test_back_from_pet_name_to_kind():
    state = State(draft_kind=PetKind.DOG.value)
    state.current = BookingForm.pet_name
    await h.set_pet_name(message("Вернуться назад"), state)
    assert state.current == BookingForm.pet_kind
    assert state.data.get("draft_name") is None


@pytest.mark.asyncio
async def test_back_from_sex_to_breed():
    state = State(draft_kind=PetKind.DOG.value, draft_name="Рекс", draft_breed="метис")
    state.current = BookingForm.pet_sex
    await h.set_pet_sex(message("Вернуться назад"), state)
    assert state.current == BookingForm.pet_breed


@pytest.mark.asyncio
async def test_back_from_weight_to_age():
    state = State(
        draft_kind=PetKind.DOG.value,
        draft_name="Рекс",
        draft_sex="женский",
        draft_neutered=True,
        draft_age_months=36,
    )
    state.current = BookingForm.pet_weight
    await h.set_pet_weight(message("Вернуться назад"), state)
    assert state.current == BookingForm.pet_age
    assert state.data.get("draft_weight") is None


@pytest.mark.asyncio
async def test_back_from_passport_to_health():
    state = State(
        draft_kind=PetKind.DOG.value,
        draft_name="Рекс",
        draft_behavior={},
        draft_passport_ids=["x"],
    )
    state.current = BookingForm.pet_passport
    await h.passport_done(message("Вернуться назад"), state)
    assert state.current == BookingForm.pet_health
    assert state.data.get("draft_passport_ids") == []


@pytest.mark.asyncio
async def test_back_from_add_another_removes_last_pet():
    pets = [
        {"kind": "dog", "name": "Один"},
        {"kind": "cat", "name": "Два"},
    ]
    state = State(pets=pets)
    state.current = BookingForm.add_another_pet
    await h.add_another(message("Вернуться назад"), state, None, None, None, None)
    assert state.current == BookingForm.add_another_pet
    assert len(state.data["pets"]) == 1
    assert state.data["pets"][0]["name"] == "Один"


@pytest.mark.asyncio
async def test_back_from_arrival_to_dates():
    state = State(date_from="2027-11-20", date_to="2027-11-25", arrival_time="19:00")
    state.current = BookingForm.arrival_time
    await h.set_arrival_time(message("Вернуться назад"), state)
    assert state.current == BookingForm.dates
    assert state.data.get("date_from") is None
    assert state.data.get("arrival_time") is None
