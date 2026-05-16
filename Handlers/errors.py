import logging
from typing import Any

from aiogram import Router
from aiogram.handlers import ErrorHandler
from aiogram.types import CallbackQuery, Message

from Utils.texts import UNEXPECTED_ERROR_TEXT

logger = logging.getLogger(__name__)
router = Router(name="errors")


@router.errors()
class BotErrorHandler(ErrorHandler):
    async def handle(self) -> Any:
        exception = self.event.exception
        logger.exception("Unhandled handler error", exc_info=exception)

        update = self.event.update
        if update is None:
            return True

        target = (
            update.message
            or update.callback_query
            or update.edited_message
            or update.channel_post
            or update.edited_channel_post
        )
        if target is None:
            return True

        try:
            if isinstance(target, CallbackQuery):
                if target.message is not None:
                    await target.message.answer(UNEXPECTED_ERROR_TEXT)
                else:
                    await target.answer(UNEXPECTED_ERROR_TEXT, show_alert=True)
            elif isinstance(target, Message):
                await target.answer(UNEXPECTED_ERROR_TEXT)
        except Exception:
            logger.exception("Failed to send error notice to user")
        return True
