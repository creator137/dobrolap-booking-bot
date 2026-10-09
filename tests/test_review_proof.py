from types import SimpleNamespace

import pytest

from dobrolap_bot.bot.handlers import _save_review_proof
from dobrolap_bot.bot.states import BookingForm
from dobrolap_bot.config.loader import load_catalog
from pathlib import Path


class State:
    def __init__(self):
        self.data = {"date_from": "2026-10-10", "date_to": "2026-10-11", "pets": []}
        self.current = None

    async def update_data(self, **values):
        self.data.update(values)

    async def get_data(self):
        return self.data.copy()

    async def set_state(self, state):
        self.current = state


class Message:
    def __init__(self, *, document=False):
        self.photo = [] if document else [SimpleNamespace(file_id="review-photo")]
        self.document = SimpleNamespace(file_id="review-document") if document else None
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)


@pytest.mark.asyncio
@pytest.mark.parametrize("document,expected", [(False, "review-photo"), (True, "review-document")])
async def test_review_screenshot_is_kept_for_operator(document, expected):
    catalog = load_catalog(Path(__file__).resolve().parents[1] / "config")
    state, message = State(), Message(document=document)
    await _save_review_proof(message, state, catalog)
    assert state.data["review_discount_claim"] is True
    assert state.data["review_proof_file_id"] == expected
    assert state.data["review_proof_is_document"] is document
    assert state.current == BookingForm.confirm_submit
