"""SQLite-backed aiogram FSM storage (survives bot restarts)."""

from __future__ import annotations

import json
from copy import copy
from pathlib import Path
from typing import Any, Mapping

import aiosqlite
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey

SCHEMA = """
CREATE TABLE IF NOT EXISTS fsm_states (
    bot_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    destiny TEXT NOT NULL DEFAULT 'default',
    state TEXT,
    data_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (bot_id, chat_id, user_id, destiny)
);
"""


class SqliteFsmStorage(BaseStorage):
    def __init__(self, path: Path) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SqliteFsmStorage is not open")
        return self._db

    def _key(self, key: StorageKey) -> tuple[int, int, int, str]:
        return key.bot_id, key.chat_id, key.user_id, key.destiny

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        state_str = state.state if isinstance(state, State) else state
        bot_id, chat_id, user_id, destiny = self._key(key)
        await self.db.execute(
            """
            INSERT INTO fsm_states (bot_id, chat_id, user_id, destiny, state, data_json)
            VALUES (?, ?, ?, ?, ?, '{}')
            ON CONFLICT(bot_id, chat_id, user_id, destiny) DO UPDATE SET state=excluded.state
            """,
            (bot_id, chat_id, user_id, destiny, state_str),
        )
        await self.db.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        bot_id, chat_id, user_id, destiny = self._key(key)
        cur = await self.db.execute(
            """
            SELECT state FROM fsm_states
            WHERE bot_id=? AND chat_id=? AND user_id=? AND destiny=?
            """,
            (bot_id, chat_id, user_id, destiny),
        )
        row = await cur.fetchone()
        return row[0] if row else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        if not isinstance(data, dict):
            raise TypeError(f"Data must be a dict, got {type(data).__name__}")
        bot_id, chat_id, user_id, destiny = self._key(key)
        payload = json.dumps(dict(data), ensure_ascii=False)
        await self.db.execute(
            """
            INSERT INTO fsm_states (bot_id, chat_id, user_id, destiny, state, data_json)
            VALUES (?, ?, ?, ?, NULL, ?)
            ON CONFLICT(bot_id, chat_id, user_id, destiny) DO UPDATE SET data_json=excluded.data_json
            """,
            (bot_id, chat_id, user_id, destiny, payload),
        )
        await self.db.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        bot_id, chat_id, user_id, destiny = self._key(key)
        cur = await self.db.execute(
            """
            SELECT data_json FROM fsm_states
            WHERE bot_id=? AND chat_id=? AND user_id=? AND destiny=?
            """,
            (bot_id, chat_id, user_id, destiny),
        )
        row = await cur.fetchone()
        if not row:
            return {}
        return json.loads(row[0] or "{}")

    async def get_value(
        self,
        storage_key: StorageKey,
        dict_key: str,
        default: Any | None = None,
    ) -> Any | None:
        data = await self.get_data(storage_key)
        return copy(data.get(dict_key, default))
