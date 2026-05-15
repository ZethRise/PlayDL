import shutil
import sys
from pathlib import Path
from string import Formatter

from App.config import Settings
from Services.commands import CommandError, run_command, run_process


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
            await run_process(self._alltech_args(package_name, output_dir))
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
