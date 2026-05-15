from typing import Any

from aiogram import Router
from aiogram.handlers import ErrorHandler

from Utils.texts import UNEXPECTED_ERROR_TEXT

router = Router(name="errors")


@router.errors()
class BotErrorHandler(ErrorHandler):
    async def handle(self) -> Any:
        event = self.update.event
        if hasattr(event, "answer"):
            await event.answer(UNEXPECTED_ERROR_TEXT)
        return True
