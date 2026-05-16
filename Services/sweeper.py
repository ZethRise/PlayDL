import asyncio
import logging
import shutil
from contextlib import suppress
from pathlib import Path

import aiohttp

from App.config import Settings
from DataBase.mongo import Database

logger = logging.getLogger(__name__)


def _dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for entry in path.rglob("*"):
        with suppress(Exception):
            if entry.is_file():
                total += entry.stat().st_size
    return total


def _clear_dir(path: Path) -> None:
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        return
    for entry in path.iterdir():
        with suppress(Exception):
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)


async def downloads_sweeper(settings: Settings) -> None:
    limit_bytes = settings.downloads_max_mb * 1024 * 1024
    interval = settings.downloads_sweep_interval_s
    logger.info(
        "downloads_sweeper started (limit=%d MB, interval=%ds)",
        settings.downloads_max_mb,
        interval,
    )
    while True:
        try:
            await asyncio.sleep(interval)
            size = await asyncio.to_thread(_dir_size_bytes, settings.download_dir)
            size_mb = size / (1024 * 1024)
            logger.info("downloads dir size=%.2f MB", size_mb)
            if size >= limit_bytes:
                logger.warning(
                    "downloads dir exceeded %d MB (%.2f MB), clearing",
                    settings.downloads_max_mb,
                    size_mb,
                )
                await asyncio.to_thread(_clear_dir, settings.download_dir)
        except asyncio.CancelledError:
            logger.info("downloads_sweeper cancelled")
            raise
        except Exception:
            logger.exception("downloads_sweeper iteration failed")


async def _check_url_alive(session: aiohttp.ClientSession, url: str) -> bool:
    try:
        async with session.head(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status < 400:
                return True
            if resp.status in (403, 405):
                pass
            else:
                return False
    except Exception:
        pass
    try:
        async with session.get(
            url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=20)
        ) as resp:
            return resp.status < 400
    except Exception:
        return False


async def nixfile_link_checker(settings: Settings, db: Database) -> None:
    interval = settings.nixfile_link_check_interval_s
    logger.info("nixfile_link_checker started (interval=%ds)", interval)
    while True:
        try:
            await asyncio.sleep(interval)
            entries = await db.list_packages_with_nixfile()
            if not entries:
                continue
            logger.info("nixfile_link_checker scanning %d entries", len(entries))
            async with aiohttp.ClientSession() as session:
                for entry in entries:
                    package = entry.get("_id")
                    url = entry.get("nixfile_url")
                    if not (package and url):
                        continue
                    alive = await _check_url_alive(session, url)
                    if alive:
                        await db.touch_package_nixfile(package)
                    else:
                        logger.warning(
                            "nixfile link dead: package=%s url=%s -> clearing",
                            package,
                            url,
                        )
                        await db.clear_package_nixfile(package)
        except asyncio.CancelledError:
            logger.info("nixfile_link_checker cancelled")
            raise
        except Exception:
            logger.exception("nixfile_link_checker iteration failed")
