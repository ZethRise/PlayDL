from typing import Any

from aiogram import F, Router
from aiogram.handlers import CallbackQueryHandler, MessageHandler
from aiogram.types import FSInputFile

from Services.downloader import DownloadError
from Services.extract import extract_package_name, is_google_play_url
from Utils.keyboards import cancel_keyboard, main_keyboard
from Utils.texts import (
    BAD_LINK_TEXT,
    BUSY_TEXT,
    CANCELLED_TEXT,
    CONVERTING_TEXT,
    DONE_TEXT,
    DOWNLOADING_TEXT,
    FAILED_TEXT,
    SEND_LINK_TEXT,
    UPLOADING_TEXT,
)

router = Router(name="links")


@router.callback_query(F.data == "send_link")
class SendLinkCallback(CallbackQueryHandler):
    async def handle(self) -> Any:
        await self.event.answer()
        if self.message:
            await self.message.answer(SEND_LINK_TEXT, reply_markup=cancel_keyboard())


@router.callback_query(F.data == "cancel")
class CancelCallback(CallbackQueryHandler):
    async def handle(self) -> Any:
        await self.event.answer("لغو شد")
        if self.message:
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

        job_id = await db.create_job(self.from_user.id, package_name, url)
        status_message = await self.event.answer(DOWNLOADING_TEXT.format(package=package_name))

        try:
            source_path = await downloader.download(url=url, package_name=package_name, job_id=job_id)
            await db.update_job(job_id, "downloaded", source_path=str(source_path))

            await status_message.edit_text(CONVERTING_TEXT)
            apk_path = await converter.to_apk(source_path)
            await db.update_job(job_id, "converted", apk_path=str(apk_path))

            await status_message.edit_text(UPLOADING_TEXT)
            await self.event.answer_document(
                document=FSInputFile(apk_path, filename=apk_path.name),
                caption=DONE_TEXT.format(package=package_name),
                reply_markup=main_keyboard(),
            )
            await status_message.delete()
            await db.update_job(job_id, "done")
        except DownloadError as exc:
            await db.update_job(job_id, "failed", error=str(exc))
            await status_message.edit_text(FAILED_TEXT.format(error=str(exc)), reply_markup=main_keyboard())
        except Exception as exc:
            await db.update_job(job_id, "failed", error=str(exc))
            await status_message.edit_text(FAILED_TEXT.format(error=str(exc)), reply_markup=main_keyboard())
