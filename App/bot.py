from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode

from App.config import Settings


def create_bot(settings: Settings) -> Bot:
    session = AiohttpSession(
        api=TelegramAPIServer.from_base(
            settings.telegram_api_base_url,
            is_local=settings.telegram_api_is_local,
        )
    )
    return Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
