import asyncio
import logging

from aiogram import Dispatcher

from App.bot import create_bot
from App.config import load_settings
from DataBase.mongo import Database
from Handlers import setup_routers
from Services.bootstrap import ensure_tools
from Services.converter import ApksConverter
from Services.downloader import PlayDownloader
from Services.jobs import JobRunner
from Services.nixfile import NixfileUploader

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    logger.info("PlayDL starting")
    settings = load_settings()
    logger.info("Settings loaded")
    await ensure_tools(settings)

    logger.info("Connecting to MongoDB: %s", settings.mongodb_uri)
    db = Database(settings.mongodb_uri, settings.mongodb_db_name)
    await db.connect()
    await db.migrate()
    logger.info("MongoDB ready: %s", settings.mongodb_db_name)

    bot = create_bot(settings)
    dp = Dispatcher()
    dp.include_router(setup_routers())

    nixfile_uploader = NixfileUploader(settings)

    dp["settings"] = settings
    dp["db"] = db
    dp["downloader"] = PlayDownloader(settings)
    dp["converter"] = ApksConverter(settings)
    dp["job_runner"] = JobRunner(settings.max_parallel_jobs)
    dp["nixfile_uploader"] = nixfile_uploader

    try:
        logger.info("Starting Telegram polling")
        await dp.start_polling(bot)
    finally:
        await nixfile_uploader.close()
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
