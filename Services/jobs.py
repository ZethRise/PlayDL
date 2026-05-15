import asyncio
from collections.abc import Awaitable
from typing import TypeVar

T = TypeVar("T")


class JobRunner:
    def __init__(self, max_parallel: int) -> None:
        self._semaphore = asyncio.Semaphore(max_parallel)

    @property
    def available(self) -> bool:
        return self._semaphore.locked() is False

    async def run(self, task: Awaitable[T]) -> T:
        async with self._semaphore:
            return await task
