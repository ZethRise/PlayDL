import asyncio
import threading
from pathlib import Path
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.handlers import CallbackQueryHandler, MessageHandler
from aiogram.types import FSInputFile

from Services.downloader import DownloadError
from Services.extract import extract_package_name, is_google_play_url
from Services.nixfile import NixfileError
from Utils.html import bold, safe
from Utils.keyboards import (
    cancel_keyboard,
    delivery_keyboard,
    link_keyboard,
    main_keyboard,
)
from Utils.progress import AnimatedProgress, DiskSizeProgress, SnapshotProgress
from Utils.texts import (
    BAD_LINK_TEXT,
    BUSY_TEXT,
    CANCELLED_TEXT,
    CONVERTING_TEXT,
    DELIVERY_PROMPT_TEXT,
    DONE_TEXT,
    DOWNLOAD_TITLE,
    FAILED_TEXT,
    JOB_NOT_FOUND_TEXT,
    LINK_READY_TEXT,
    NIXFILE_DISABLED_TEXT,
    NIXFILE_PREPARING_TEXT,
    NIXFILE_UPLOAD_TITLE,
    SEND_LINK_TEXT,
    UPLOAD_TITLE,
)

router = Router(name="links")


@router.callback_query(F.data == "send_link")
class SendLinkCallback(CallbackQueryHandler):
    async def handle(self) -> Any:
        await self.event.answer()
        if not self.message:
            return

        try:
            await self.message.edit_text(SEND_LINK_TEXT, reply_markup=cancel_keyboard())
        except TelegramBadRequest:
            await self.message.answer(SEND_LINK_TEXT, reply_markup=cancel_keyboard())


@router.callback_query(F.data == "cancel")
class CancelCallback(CallbackQueryHandler):
    async def handle(self) -> Any:
        await self.event.answer("لغو شد")
        if not self.message:
            return

        try:
            await self.message.edit_text(CANCELLED_TEXT, reply_markup=main_keyboard())
        except TelegramBadRequest:
            await self.message.answer(CANCELLED_TEXT, reply_markup=main_keyboard())


@router.message(F.text)
class GooglePlayLinkHandler(MessageHandler):
    async def handle(self) -> Any:
        text = (self.event.text or "").strip()
        if not is_google_play_url(text):
            await self.event.answer(BAD_LINK_TEXT, reply_markup=main_keyboard())
            return

        package_name = extract_package_name(text)
        if not package_name:
            await self.event.answer(BAD_LINK_TEXT, reply_markup=main_keyboard())
            return

        job_runner = self.data["job_runner"]
        if not job_runner.available:
            await self.event.answer(BUSY_TEXT, reply_markup=main_keyboard())
            return

        await job_runner.run(self._process(text, package_name))

    async def _process(self, url: str, package_name: str) -> None:
        db = self.data["db"]
        downloader = self.data["downloader"]
        converter = self.data["converter"]
        settings = self.data["settings"]

        job_id = await db.create_job(self.from_user.id, package_name, url)
        package_label = bold(package_name)
        status_message = await self.event.answer(
            f"{DOWNLOAD_TITLE}\n\n{package_label}\n\n📥 0 B  •  0 B/s"
        )

        download_dir = settings.download_dir / str(job_id)
        download_dir.mkdir(parents=True, exist_ok=True)
        download_progress: DiskSizeProgress | None = None

        try:
            download_progress = DiskSizeProgress(
                status_message, DOWNLOAD_TITLE, package_label, download_dir
            )
            download_progress.start()
            source_path = await downloader.download(url=url, package_name=package_name, job_id=job_id)
            await download_progress.stop()
            download_progress = None
            await db.update_job(job_id, "downloaded", source_path=str(source_path))

            await status_message.edit_text(CONVERTING_TEXT)
            apk_path = await converter.to_apk(source_path)
            await db.update_job(job_id, "ready", apk_path=str(apk_path))

            await status_message.edit_text(
                DELIVERY_PROMPT_TEXT, reply_markup=delivery_keyboard(job_id)
            )
        except DownloadError as exc:
            if download_progress:
                await download_progress.stop()
            await db.update_job(job_id, "failed", error=str(exc))
            await status_message.edit_text(
                FAILED_TEXT.format(error=safe(exc)),
                reply_markup=main_keyboard(),
            )
        except Exception as exc:
            if download_progress:
                await download_progress.stop()
            await db.update_job(job_id, "failed", error=str(exc))
            await status_message.edit_text(
                FAILED_TEXT.format(error=safe(exc)),
                reply_markup=main_keyboard(),
            )


@router.callback_query(F.data.startswith("deliver:"))
class DeliveryCallback(CallbackQueryHandler):
    async def handle(self) -> Any:
        await self.event.answer()
        if not self.message:
            return

        try:
            _, mode, job_id_str = (self.event.data or "").split(":", 2)
            job_id = int(job_id_str)
        except (ValueError, AttributeError):
            await self.message.edit_text(JOB_NOT_FOUND_TEXT, reply_markup=main_keyboard())
            return

        db = self.data["db"]
        job = await db.get_job(job_id)
        if not job or not job.get("apk_path"):
            await self.message.edit_text(JOB_NOT_FOUND_TEXT, reply_markup=main_keyboard())
            return

        apk_path = Path(job["apk_path"])
        package_name = job.get("package_name", "")
        package_label = bold(package_name)

        if not apk_path.exists():
            await db.update_job(job_id, "failed", error="apk_missing")
            await self.message.edit_text(JOB_NOT_FOUND_TEXT, reply_markup=main_keyboard())
            return

        if mode == "tg":
            await self._deliver_telegram(job_id, apk_path, package_label)
        elif mode == "nx":
            await self._deliver_nixfile(job_id, apk_path, package_label)
        else:
            await self.message.edit_text(JOB_NOT_FOUND_TEXT, reply_markup=main_keyboard())

    async def _deliver_telegram(
        self, job_id: int, apk_path: Path, package_label: str
    ) -> None:
        db = self.data["db"]
        status_message = self.message
        if status_message is None:
            return

        upload_progress = AnimatedProgress(status_message, UPLOAD_TITLE, package_label)
        try:
            await status_message.edit_text(
                AnimatedProgress.render(UPLOAD_TITLE, package_label, 6)
            )
            upload_progress.start()
            await self.event.message.answer_document(
                document=FSInputFile(apk_path, filename=apk_path.name),
                caption=DONE_TEXT.format(package=package_label),
                reply_markup=main_keyboard(),
            )
            await upload_progress.stop(percent=100)
            await status_message.delete()
            await db.update_job(job_id, "done")
        except Exception as exc:
            await upload_progress.stop()
            await db.update_job(job_id, "failed", error=str(exc))
            await status_message.edit_text(
                FAILED_TEXT.format(error=safe(exc)),
                reply_markup=main_keyboard(),
            )

    async def _deliver_nixfile(
        self, job_id: int, apk_path: Path, package_label: str
    ) -> None:
        db = self.data["db"]
        status_message = self.message
        if status_message is None:
            return

        uploader = self.data.get("nixfile_uploader")
        if uploader is None or not uploader.enabled:
            await status_message.edit_text(
                NIXFILE_DISABLED_TEXT, reply_markup=main_keyboard()
            )
            return

        upload_progress = SnapshotProgress(
            status_message, NIXFILE_UPLOAD_TITLE, package_label, uploader.progress_snapshot
        )
        upload_started = threading.Event()
        progress_started = False

        await status_message.edit_text(NIXFILE_PREPARING_TEXT)

        async def watch_start() -> None:
            while not upload_started.is_set():
                await asyncio.sleep(0.3)
            nonlocal progress_started
            upload_progress.start()
            progress_started = True

        watcher = asyncio.create_task(watch_start())

        try:
            url = await uploader.upload(apk_path, upload_started=upload_started)
            watcher.cancel()
            if progress_started:
                await upload_progress.stop(percent=100)
            await status_message.edit_text(
                LINK_READY_TEXT.format(package=package_label, url=safe(url)),
                reply_markup=link_keyboard(url),
            )
            await db.update_job(job_id, "done")
        except NixfileError as exc:
            watcher.cancel()
            if progress_started:
                await upload_progress.stop()
            await db.update_job(job_id, "failed", error=str(exc))
            await status_message.edit_text(
                FAILED_TEXT.format(error=safe(exc)),
                reply_markup=main_keyboard(),
            )
        except Exception as exc:
            watcher.cancel()
            if progress_started:
                await upload_progress.stop()
            await db.update_job(job_id, "failed", error=str(exc))
            await status_message.edit_text(
                FAILED_TEXT.format(error=safe(exc)),
                reply_markup=main_keyboard(),
            )
