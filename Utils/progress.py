import asyncio
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

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


def _bar(percent: int, width: int = 10) -> str:
    percent = max(0, min(100, percent))
    filled = round(percent / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _format_size(num_bytes: float) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(num_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{value:.2f} TB"


class DiskSizeProgress:
    def __init__(
        self,
        message: Message,
        title: str,
        package_label: str,
        path: Path,
        interval: float = 1.5,
    ) -> None:
        self._message = message
        self._title = title
        self._label = package_label
        self._path = path
        self._interval = interval
        self._stopped = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self, title: str | None = None, info: str | None = None) -> None:
        self._stopped.set()
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        if title or info:
            text = self._render_final(title or self._title, info or "")
            await self._edit(text)

    async def _run(self) -> None:
        last_size = 0
        last_time = time.monotonic()
        await self._edit(self._render(0, 0.0))
        while not self._stopped.is_set():
            await asyncio.sleep(self._interval)
            size = self._dir_size()
            now = time.monotonic()
            elapsed = max(0.001, now - last_time)
            speed = max(0.0, (size - last_size) / elapsed)
            last_size, last_time = size, now
            await self._edit(self._render(size, speed))

    def _dir_size(self) -> int:
        total = 0
        with suppress(Exception):
            if self._path.is_file():
                return self._path.stat().st_size
            for entry in self._path.rglob("*"):
                with suppress(Exception):
                    if entry.is_file():
                        total += entry.stat().st_size
        return total

    def _render(self, size_bytes: int, speed_bps: float) -> str:
        size_str = _format_size(size_bytes)
        speed_str = f"{_format_size(speed_bps)}/s"
        return (
            f"{self._title}\n\n{self._label}\n\n"
            f"📥 {size_str}  •  {speed_str}"
        )

    def _render_final(self, title: str, info: str) -> str:
        return f"{title}\n\n{self._label}\n\n{info}" if info else f"{title}\n\n{self._label}"

    async def _edit(self, text: str) -> None:
        with suppress(TelegramBadRequest):
            await self._message.edit_text(text)


class SnapshotProgress:
    def __init__(
        self,
        message: Message,
        title: str,
        package_label: str,
        snapshot: Callable[[], dict | None],
        interval: float = 1.5,
    ) -> None:
        self._message = message
        self._title = title
        self._label = package_label
        self._snapshot = snapshot
        self._interval = interval
        self._stopped = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._last_text = ""

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self, percent: int | None = None, info: str | None = None) -> None:
        self._stopped.set()
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        if percent is not None:
            await self._edit(self._render(percent, info or ""))

    async def _run(self) -> None:
        await self._edit(self._render(0, ""))
        while not self._stopped.is_set():
            await asyncio.sleep(self._interval)
            snap = self._snapshot()
            if snap is None:
                continue
            percent = int(snap.get("percent", 0) or 0)
            info = str(snap.get("info", "") or "")
            await self._edit(self._render(percent, info))

    def _render(self, percent: int, info: str) -> str:
        bar = _bar(percent)
        lines = [self._title, "", self._label, "", f"[{bar}] {percent}%"]
        if info:
            lines.append(info)
        return "\n".join(lines)

    async def _edit(self, text: str) -> None:
        if text == self._last_text:
            return
        self._last_text = text
        with suppress(TelegramBadRequest):
            await self._message.edit_text(text)
