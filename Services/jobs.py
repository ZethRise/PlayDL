import asyncio
from collections.abc import Awaitable
from typing import TypeVar

T = TypeVar("T")


class JobRunner:
    def __init__(self, max_parallel: int) -> None:
        self._semaphore = asyncio.Semaphore(max_parallel)
        self._user_locks: dict[int, asyncio.Lock] = {}
        self._active_users: set[int] = set()

    @property
    def available(self) -> bool:
        return self._semaphore.locked() is False

    def user_busy(self, user_id: int) -> bool:
        return user_id in self._active_users

    async def run(self, user_id: int, task: Awaitable[T]) -> T:
        lock = self._user_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            self._active_users.add(user_id)
            try:
                async with self._semaphore:
                    return await task
            finally:
                self._active_users.discard(user_id)
