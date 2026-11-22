"""Database-backed write-through Aiogram FSM storage surviving bot restarts."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Mapping, Optional, Tuple

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StateType, StorageKey
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.models import FSMStateRecord


logger = logging.getLogger("norin_bot.fsm")


class DatabaseFSMStorage(BaseStorage):
    """Persist Aiogram FSM states & JSON data in PostgreSQL/SQLite with write-through RAM cache."""

    def __init__(self, session_maker: async_sessionmaker[AsyncSession]) -> None:
        self._session_maker = session_maker
        self._cache: Dict[str, Tuple[Optional[str], Dict[str, Any]]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    @staticmethod
    def _key_str(key: StorageKey) -> str:
        return (
            f"{key.bot_id}:{key.chat_id}:{key.user_id}:"
            f"{key.thread_id or 0}:{key.business_connection_id or ''}:{key.destiny}"
        )[:255]

    def _lock_for(self, skey: str) -> asyncio.Lock:
        lock = self._locks.get(skey)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[skey] = lock
        return lock

    async def _load(self, skey: str) -> Tuple[Optional[str], Dict[str, Any]]:
        cached = self._cache.get(skey)
        if cached is not None:
            return cached[0], dict(cached[1])
        async with self._session_maker() as db:
            rec = await db.get(FSMStateRecord, skey)
        if rec is None:
            self._cache[skey] = (None, {})
            return None, {}
        try:
            parsed = json.loads(rec.data_json or "{}")
            data = parsed if isinstance(parsed, dict) else {}
        except Exception:
            data = {}
        self._cache[skey] = (rec.state, dict(data))
        return rec.state, data

    async def _save(self, skey: str, state_val: Optional[str], data_val: Dict[str, Any]) -> None:
        clean_data = dict(data_val) if data_val else {}
        self._cache[skey] = (state_val, clean_data)
        try:
            async with self._session_maker() as db:
                if state_val is None and not clean_data:
                    await db.execute(
                        delete(FSMStateRecord).where(FSMStateRecord.storage_key == skey)
                    )
                    await db.commit()
                    return
                encoded = json.dumps(clean_data, ensure_ascii=False, default=str)
                rec = await db.get(FSMStateRecord, skey)
                if rec is None:
                    db.add(
                        FSMStateRecord(
                            storage_key=skey,
                            state=state_val,
                            data_json=encoded,
                        )
                    )
                else:
                    rec.state = state_val
                    rec.data_json = encoded
                await db.commit()
        except Exception as exc:
            logger.warning("FSM persistence write error for %s: %s", skey, exc)

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        skey = self._key_str(key)
        state_val = state.state if isinstance(state, State) else (str(state) if state else None)
        async with self._lock_for(skey):
            _, data = await self._load(skey)
            await self._save(skey, state_val, data)

    async def get_state(self, key: StorageKey) -> Optional[str]:
        skey = self._key_str(key)
        state_val, _ = await self._load(skey)
        return state_val

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        skey = self._key_str(key)
        async with self._lock_for(skey):
            state_val, _ = await self._load(skey)
            await self._save(skey, state_val, dict(data))

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        skey = self._key_str(key)
        _, data = await self._load(skey)
        return dict(data)

    async def close(self) -> None:
        self._cache.clear()
        self._locks.clear()
