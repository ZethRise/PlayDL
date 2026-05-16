import logging
import shutil
import sys
from contextlib import suppress
from pathlib import Path
from string import Formatter

from App.config import Settings
from Services.commands import CommandError, run_command, run_process

logger = logging.getLogger(__name__)
MAX_ALLTECH_AUTH_RETRIES = 2


class DownloadError(RuntimeError):
    pass


class PlayDownloader:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def download(self, url: str, package_name: str, job_id: int) -> Path:
        output_dir = self._settings.download_dir / str(job_id)
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            await self._run_backend(url=url, package_name=package_name, output_dir=output_dir)
        except CommandError as exc:
            raise DownloadError(f"دانلود ناموفق بود: {exc}") from exc

        return self._select_download_result(output_dir)

    async def _run_backend(self, url: str, package_name: str, output_dir: Path) -> None:
        backend = self._resolve_backend()

        if backend == "custom":
            command_template = self._settings.play_downloader_cmd
            if not command_template:
                raise DownloadError("PLAY_DOWNLOADER_CMD تنظیم نشده است.")
            await run_command(
                self._render(
                    command_template,
                    url=url,
                    package=package_name,
                    output_dir=str(output_dir),
                    arch=self._settings.play_arch,
                )
            )
            return

        if backend == "alltech-gplay":
            await self._alltech_run_with_auth_retry(package_name, output_dir)
            return

        if backend == "gplaydl":
            await run_process(
                [
                    "gplaydl",
                    "download",
                    package_name,
                    "-o",
                    str(output_dir),
                    "-a",
                    self._settings.play_arch,
                ]
            )
            return

        if backend == "apkeep":
            await run_process(self._apkeep_args(package_name, output_dir))
            return

        raise DownloadError(f"دانلودر پشتیبانی نمی‌شود: {backend}")

    def _resolve_backend(self) -> str:
        backend = self._settings.play_downloader_backend.strip().lower()
        if backend != "auto":
            return backend

        if self._settings.alltech_gplay_path.exists():
            return "alltech-gplay"
        if shutil.which("gplaydl"):
            return "gplaydl"
        if shutil.which("apkeep"):
            return "apkeep"
        if self._settings.play_downloader_cmd:
            return "custom"

        raise DownloadError(
            "هیچ دانلودری پیدا نشد. ALLTECH_GPLAY_PATH یا gplaydl/apkeep یا PLAY_DOWNLOADER_CMD را تنظیم کن."
        )

    async def _alltech_run_with_auth_retry(
        self, package_name: str, output_dir: Path
    ) -> None:
        args = self._alltech_args(package_name, output_dir)
        last_error: CommandError | None = None
        for attempt in range(MAX_ALLTECH_AUTH_RETRIES + 1):
            try:
                await run_process(args)
                return
            except CommandError as exc:
                last_error = exc
                if not self._is_alltech_auth_error(str(exc)):
                    raise
                if attempt >= MAX_ALLTECH_AUTH_RETRIES:
                    break
                logger.warning(
                    "alltech-gplay 401 for %s (attempt %d); rotating auth token",
                    package_name,
                    attempt + 1,
                )
                await self._alltech_force_reauth()
        if last_error is None:
            raise CommandError("alltech-gplay failed without raising")
        raise last_error

    @staticmethod
    def _is_alltech_auth_error(text: str) -> bool:
        lowered = text.lower()
        markers = (
            "failed to get app details: 401",
            "401",
            "unauthorized",
            "authentication",
        )
        return any(m in lowered for m in markers)

    async def _alltech_force_reauth(self) -> None:
        auth_file = self._settings.alltech_auth_file.expanduser()
        with suppress(Exception):
            if auth_file.exists():
                auth_file.unlink()
                logger.info("alltech-gplay auth file removed: %s", auth_file)

        gplay_path = self._settings.alltech_gplay_path
        if not gplay_path.exists():
            raise CommandError(f"alltech-gplay binary missing: {gplay_path}")

        if gplay_path.suffix.lower() == ".py":
            auth_args = [sys.executable, str(gplay_path), "auth"]
        else:
            auth_args = [str(gplay_path), "auth"]

        logger.info("alltech-gplay re-authenticating to rotate profile")
        await run_process(auth_args)

        if not auth_file.exists():
            raise CommandError(
                f"alltech-gplay auth ناموفق بود؛ {auth_file} ساخته نشد. NIXFILE یا alltech تنظیمات را بررسی کن."
            )

    def _alltech_args(self, package_name: str, output_dir: Path) -> list[str]:
        gplay_path = self._settings.alltech_gplay_path
        if not gplay_path.exists():
            raise DownloadError(f"فایل gplay پیدا نشد: {gplay_path}")

        args = [
            str(gplay_path),
            "download",
            package_name,
            "-a",
            self._settings.play_arch,
            "-o",
            str(output_dir),
        ]
        if self._settings.merge_splits:
            args.append("-m")

        if gplay_path.suffix.lower() == ".py":
            return [sys.executable, *args]
        return args

    def _apkeep_args(self, package_name: str, output_dir: Path) -> list[str]:
        args = ["apkeep", "-a", package_name]
        if self._settings.apkeep_source:
            args.extend(["-d", self._settings.apkeep_source])
        if self._settings.apkeep_email:
            args.extend(["-e", self._settings.apkeep_email])
        if self._settings.apkeep_token:
            args.extend(["-t", self._settings.apkeep_token])
        args.append(str(output_dir))
        return args

    @staticmethod
    def _select_download_result(output_dir: Path) -> Path:
        candidates = [
            path
            for path in output_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in {".apk", ".apks"}
        ]
        if not candidates:
            raise DownloadError("فایل APK/APKS بعد از دانلود پیدا نشد.")

        merged = [
            path
            for path in candidates
            if path.suffix.lower() == ".apk" and "merged" in path.stem.lower()
        ]
        if merged:
            return max(merged, key=lambda item: item.stat().st_mtime)

        apk_files = [path for path in candidates if path.suffix.lower() == ".apk"]
        apks_files = [path for path in candidates if path.suffix.lower() == ".apks"]

        if len(apk_files) == 1:
            return apk_files[0]
        if len(apks_files) == 1 and not apk_files:
            return apks_files[0]
        if len(apk_files) > 1:
            return output_dir

        return max(candidates, key=lambda item: item.stat().st_mtime)

    @staticmethod
    def _render(template: str, **values: str) -> str:
        allowed = set(values)
        fields = {name for _, name, _, _ in Formatter().parse(template) if name}
        unknown = fields - allowed
        if unknown:
            raise DownloadError(
                f"متغیر ناشناخته در PLAY_DOWNLOADER_CMD: {', '.join(sorted(unknown))}"
            )
        return template.format(**values)
