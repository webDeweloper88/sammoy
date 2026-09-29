from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject


class DuplicateMessageGuard:
    def __init__(self, ttl_seconds: float = 2.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._recent: dict[tuple[int, int, str], float] = {}
        self._lock = asyncio.Lock()

    async def accept(self, key: tuple[int, int, str], *, now: float | None = None) -> bool:
        timestamp = monotonic() if now is None else now
        async with self._lock:
            previous = self._recent.get(key)
            if previous is not None and timestamp - previous < self.ttl_seconds:
                return False
            self._recent[key] = timestamp
            cutoff = timestamp - self.ttl_seconds
            self._recent = {item: seen_at for item, seen_at in self._recent.items() if seen_at >= cutoff}
            return True


class DuplicateMessageMiddleware(BaseMiddleware):
    def __init__(self, ttl_seconds: float = 2.0) -> None:
        self.guard = DuplicateMessageGuard(ttl_seconds)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.text and event.from_user:
            key = (event.chat.id, event.from_user.id, event.text)
            if not await self.guard.accept(key):
                return None
        return await handler(event, data)
