from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dobrolap_bot.bot.handlers import (
    HOTEL_ADDRESS,
    _ask_services,
    _ask_tariff_choice,
    _send_price_photos,
    set_pet_kind,
    set_service_address,
    set_service_location,
    set_service_time,
)
from dobrolap_bot.bot.keyboards import arrival_time_kb
from dobrolap_bot.bot.states import BookingForm
from dobrolap_bot.config.loader import load_catalog
from dobrolap_bot.domain.enums import PetKind
from dobrolap_bot.domain.models import PetProfile

ROOT = Path(__file__).resolve().parents[1]


class State:
    def __init__(self, **data):
        self.data = data
        self.current = None

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, state):
        self.current = state


def message(text):
    return SimpleNamespace(text=text, answer=AsyncMock(), answer_photo=AsyncMock())


@pytest.mark.asyncio
@pytest.mark.parametrize("at_home", [True, False])
async def test_service_location_routes_to_address_only_for_home(at_home):
    state = State(service_only=True)
    msg = message("18 00")
    await set_service_time(msg, state)
    assert state.data["arrival_time"] == "18:00"
    assert state.current == BookingForm.service_location
    keyboard = msg.answer.call_args.kwargs["reply_markup"]
    labels = [button.text for row in keyboard.keyboard for button in row]
    assert labels == ["Выезд на дом (зооняня)", "В зоогостиницу на груминг"]

    msg.text = labels[0 if at_home else 1]
    await set_service_location(msg, state, ROOT / "assets")
    assert msg.answer_photo.await_count == 1
    if at_home:
        assert state.current == BookingForm.service_address
        msg.text = "Адрес клиента, дом 12"
        await set_service_address(msg, state)
        assert state.data["service_address"] == msg.text
    else:
        assert state.data["service_address"] == HOTEL_ADDRESS
    assert state.current == BookingForm.pet_kind
    msg.text = "Кошка"
    await set_pet_kind(msg, state)
    assert msg.answer.call_args.args[0] == "Кличка питомца?"
    assert state.current == BookingForm.pet_name


@pytest.mark.asyncio
async def test_invalid_location_does_not_advance():
    state = State(service_only=True)
    await set_service_location(message("случайный адрес"), state, ROOT / "assets")
    assert "service_location" not in state.data
    assert state.current is None


@pytest.mark.asyncio
async def test_boarding_keeps_what_to_bring():
    msg, state = message("Кошка"), State(service_only=False)
    await set_pet_kind(msg, state)
    assert "с собой" in msg.answer.call_args.args[0]


def test_arrival_buttons_offer_only_regular_windows_and_exception():
    buttons = [button for row in arrival_time_kb().inline_keyboard for button in row]
    times = [b.callback_data[4:] for b in buttons if b.callback_data not in {"arr:noop", "arr:text"}]
    assert all("08:00" <= value <= "11:00" or "19:00" <= value <= "21:00" for value in times)
    assert any(b.callback_data == "arr:text" and "согласованию" in b.text for b in buttons)


@pytest.mark.asyncio
async def test_discount_prices_and_photos_precede_tariff_question():
    catalog = load_catalog(ROOT / "config")
    pet = PetProfile(kind=PetKind.CAT, name="Кот")
    state = State(
        pets=[pet.model_dump(mode="json"), pet.model_dump(mode="json")],
        date_from="2026-11-10", date_to="2026-11-12",
    )
    events = []
    msg = message("")
    msg.answer.side_effect = lambda text, **kwargs: events.append(("text", text))
    msg.answer_photo.side_effect = lambda photo, **kwargs: events.append(("photo", kwargs["caption"]))
    await _ask_tariff_choice(msg, state, catalog, ROOT / "assets")
    assert "50%" in events[0][1]
    assert any(kind == "photo" and "Прайс" in text for kind, text in events[:-1])
    assert any(kind == "photo" and "пример:" in text for kind, text in events[:-1])
    assert any(kind == "photo" and "По текущему тарифу:" in text and "₽" in text for kind, text in events[:-1])
    assert "Какой тариф" in events[-1][1]
    assert state.current == BookingForm.tariff_choice


@pytest.mark.asyncio
async def test_service_buttons_have_prices_and_respect_species():
    pet = PetProfile(kind=PetKind.CAT, name="Кот")
    state = State(service_only=True, pets=[pet.model_dump(mode="json")])
    msg = message("")
    await _ask_services(msg, state, load_catalog(ROOT / "config"))
    keyboard = msg.answer.call_args.kwargs["reply_markup"]
    service_buttons = [b for row in keyboard.inline_keyboard for b in row if b.callback_data not in {"svc:done", "svc:none"}]
    assert all("₽" in b.text for b in service_buttons)
    assert not any("собаки" in b.text for b in service_buttons)


@pytest.mark.asyncio
async def test_missing_or_failed_price_photo_does_not_block_questionnaire(tmp_path):
    msg = message("")
    await _send_price_photos(msg, tmp_path, ["absent.jpg"])
    msg.answer_photo.assert_not_awaited()
    msg.answer_photo.side_effect = RuntimeError("Telegram unavailable")
    await _send_price_photos(msg, ROOT / "assets", ["04-price-list-services.jpg"])
    msg.answer_photo.assert_awaited_once()
