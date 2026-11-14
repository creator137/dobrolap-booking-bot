from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dobrolap_bot.bot import handlers as h
from dobrolap_bot.bot.calendar_kb import build_calendar
from dobrolap_bot.bot.handlers import _ask_tariff_choice
from dobrolap_bot.bot.presentation import MARKING_RELOCATION_NOTE
from dobrolap_bot.bot.states import BookingForm
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.enums import PetKind
from dobrolap_bot.domain.models import BehaviorFlags, PetProfile
from dobrolap_bot.services.placement import PlacementService
from test_client_ux import State

ROOT = Path(__file__).resolve().parents[1]


def message(text=""):
    return SimpleNamespace(
        text=text,
        answer=AsyncMock(),
        answer_photo=AsyncMock(),
        answer_media_group=AsyncMock(),
    )


def test_service_end_calendar_allows_same_day():
    start = date(2027, 11, 21)
    kb = build_calendar(
        year=2027,
        month=11,
        today=date(2027, 11, 14),
        pick_from=start,
        min_date=start,
        allow_same_day=True,
    )
    flat = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "cal:day:2027-11-21" in flat
    assert "cal:day:2027-11-22" in flat


@pytest.mark.asyncio
async def test_nanny_calendar_same_day_end_then_time_prompt_separate():
    state = State(service_only=True, service_category="home")
    cb = SimpleNamespace(
        data="cal:day:2027-11-21",
        message=SimpleNamespace(
            edit_text=AsyncMock(),
            edit_reply_markup=AsyncMock(),
            answer=AsyncMock(),
        ),
        answer=AsyncMock(),
    )
    await h.cal_day(cb, state)
    markup = cb.message.edit_text.call_args.kwargs["reply_markup"]
    flat = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "cal:day:2027-11-21" in flat
    cb.data = "cal:day:2027-11-21"
    await h.cal_day(cb, state)
    assert state.data["date_from"] == "2027-11-21"
    assert state.data["date_to"] == "2027-11-22"
    assert state.current == BookingForm.service_time
    answers = [call.args[0] for call in cb.message.answer.call_args_list if call.args]
    assert any("один день" in text.casefold() for text in answers)
    assert any("время" in text.casefold() for text in answers)


@pytest.mark.asyncio
async def test_nanny_end_date_later_day_works():
    state = State(service_only=True, service_category="home")
    cb = SimpleNamespace(
        data="cal:day:2027-11-21",
        message=SimpleNamespace(edit_text=AsyncMock(), edit_reply_markup=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
    )
    await h.cal_day(cb, state)
    cb.data = "cal:day:2027-11-25"
    await h.cal_day(cb, state)
    assert state.data["date_from"] == "2027-11-21"
    assert state.data["date_to"] == "2027-11-25"
    assert state.current == BookingForm.service_time


@pytest.mark.asyncio
async def test_service_back_from_time_keeps_address():
    state = State(
        service_only=True,
        service_category="home",
        service_address="СНТ заор",
        date_from="2027-11-21",
        date_to="2027-11-22",
    )
    state.current = BookingForm.service_time
    msg = message("Вернуться назад")
    await h.set_service_time(msg, state)
    assert state.current == BookingForm.service_date
    assert state.data["service_address"] == "СНТ заор"
    assert state.data.get("date_from") is None


def test_marking_barking_dog_gets_balcony_not_formulas():
    catalog = load_catalog(ROOT / "config")
    pet = PetProfile(
        kind=PetKind.DOG,
        name="Рекс",
        weight_kg=12,
        vaccinated=True,
        parasite_treated=True,
        behavior=BehaviorFlags(marks_territory=True, loud_barking=True),
    )
    ids = {c.accommodation.id for c in PlacementService(catalog).suggest([pet], limit=100).candidates}
    assert "balcony" in ids
    assert "second_floor_formulas" not in ids


@pytest.mark.asyncio
async def test_tariff_preview_day_price_and_marking_copy():
    catalog = load_catalog(ROOT / "config")
    pet = PetProfile(
        kind=PetKind.DOG,
        name="Рекс",
        weight_kg=12,
        vaccinated=True,
        parasite_treated=True,
        behavior=BehaviorFlags(marks_territory=True, loud_barking=True),
    )
    state = State(
        pets=[pet.model_dump(mode="json")],
        date_from="2027-11-20",
        date_to="2027-11-28",
    )
    msg = message()
    await _ask_tariff_choice(msg, state, catalog, ROOT / "assets")
    vip = [call for call in msg.answer_photo.call_args_list if "VIP+" in call.kwargs.get("caption", "")]
    assert vip
    caption = vip[0].kwargs["caption"]
    assert "₽/сут" in caption
    assert "балкон" in caption.casefold()
    assert MARKING_RELOCATION_NOTE in caption
    assert "формулами" not in caption.casefold()
