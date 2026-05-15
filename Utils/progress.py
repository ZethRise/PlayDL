import asyncio
from contextlib import suppress

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message


class AnimatedProgress:
    def __init__(
        self,
        message: Message,
        title: str,
        package_label: str,
        start_percent: int = 6,
        max_percent: int = 94,
        interval: float = 2.0,
    ) -> None:
        self._message = message
        self._title = title
        self._package_label = package_label
        self._percent = start_percent
        self._max_percent = max_percent
        self._interval = interval
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self, title: str | None = None, percent: int = 100) -> None:
        self._stopped.set()
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

        if title:
            await self._edit(self.render(title, self._package_label, percent))

    async def _run(self) -> None:
        await self._edit(self.render(self._title, self._package_label, self._percent))
        while not self._stopped.is_set():
            await asyncio.sleep(self._interval)
            self._percent = min(self._max_percent, self._percent + self._step())
            await self._edit(self.render(self._title, self._package_label, self._percent))

    async def _edit(self, text: str) -> None:
        with suppress(TelegramBadRequest):
            await self._message.edit_text(text)

    @staticmethod
    def render(title: str, package_label: str, percent: int) -> str:
        filled = max(0, min(10, round(percent / 10)))
        bar = "█" * filled + "░" * (10 - filled)
        return f"{title}\n\n{package_label}\n\n[{bar}] {percent}%"

    @staticmethod
    def _step() -> int:
        return 7
