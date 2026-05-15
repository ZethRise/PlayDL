from typing import Any

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.handlers import MessageHandler

from Utils.keyboards import main_keyboard
from Utils.texts import START_TEXT

router = Router(name="start")


@router.message(CommandStart())
class StartHandler(MessageHandler):
    async def handle(self) -> Any:
        db = self.data["db"]
        await db.upsert_user(self.from_user.id, self.from_user.full_name)
        await self.event.answer(START_TEXT, reply_markup=main_keyboard())
