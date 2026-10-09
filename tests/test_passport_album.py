from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from dobrolap_bot.bot import handlers


class FakeState:
    def __init__(self):
        self.data = {"draft_passport_ids": ["already"]}

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)


class FakeMessage:
    def __init__(self, *, chat_id: int, group_id: str | None, file_id: str):
        self.chat = SimpleNamespace(id=chat_id)
        self.media_group_id = group_id
        self.photo = [SimpleNamespace(file_id=file_id)]
        self.answers: list[str] = []

    async def answer(self, text, **kwargs):
        self.answers.append(text)


@pytest.mark.asyncio
async def test_passport_album_keeps_all_photos():
    handlers._passport_album_buffers.clear()
    handlers._passport_album_tasks.clear()
    state = FakeState()
    msgs = [
        FakeMessage(chat_id=1, group_id="g1", file_id="a"),
        FakeMessage(chat_id=1, group_id="g1", file_id="b"),
        FakeMessage(chat_id=1, group_id="g1", file_id="c"),
    ]
    for msg in msgs:
        await handlers.passport_photo(msg, state)
    await asyncio.sleep(1.0)
    assert state.data["draft_passport_ids"] == ["already", "a", "b", "c"]
    assert any("3" in text or "4" in text for text in msgs[-1].answers)


@pytest.mark.asyncio
async def test_single_passport_photo_appends_immediately():
    handlers._passport_album_buffers.clear()
    handlers._passport_album_tasks.clear()
    state = FakeState()
    msg = FakeMessage(chat_id=2, group_id=None, file_id="solo")
    await handlers.passport_photo(msg, state)
    assert state.data["draft_passport_ids"] == ["already", "solo"]
    assert msg.answers
