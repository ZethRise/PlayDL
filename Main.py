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


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    settings = load_settings()
    await ensure_tools(settings)

    db = Database(settings.mongodb_uri, settings.mongodb_db_name)
    await db.connect()
    await db.migrate()

    bot = create_bot(settings)
    dp = Dispatcher()
    dp.include_router(setup_routers())

    dp["settings"] = settings
    dp["db"] = db
    dp["downloader"] = PlayDownloader(settings)
    dp["converter"] = ApksConverter(settings)
    dp["job_runner"] = JobRunner(settings.max_parallel_jobs)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
