import shutil
from pathlib import Path
from string import Formatter

from App.config import Settings
from Services.commands import CommandError, run_command
from Services.downloader import DownloadError


class ApksConverter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def to_apk(self, source_path: Path) -> Path:
        if source_path.is_dir():
            return await self._merge_directory(source_path)

        suffix = source_path.suffix.lower()
        if suffix == ".apk":
            return source_path
        if suffix != ".apks":
            raise DownloadError("فرمت خروجی دانلودر پشتیبانی نمی‌شود.")

        return await self._merge_input(source_path, source_path.with_suffix(".apk"))

    async def _merge_directory(self, source_dir: Path) -> Path:
        apk_files = sorted(source_dir.rglob("*.apk"))
        if len(apk_files) == 1:
            return apk_files[0]
        if not apk_files:
            raise DownloadError("فایل APK داخل پوشه دانلود پیدا نشد.")

        merged = [path for path in apk_files if "merged" in path.stem.lower()]
        if merged:
            return max(merged, key=lambda item: item.stat().st_mtime)

        return await self._merge_input(source_dir, source_dir / "merged.apk")

    async def _merge_input(self, input_path: Path, output_path: Path) -> Path:
        command_template = self._settings.apks_to_apk_cmd
        if command_template:
            command = self._render(command_template, input=str(input_path), output=str(output_path))
        else:
            apkeditor = self._settings.apkeditor_jar
            if not apkeditor.exists():
                raise DownloadError(
                    "APKEditor.jar پیدا نشد. APKEDITOR_JAR یا APKS_TO_APK_CMD را تنظیم کن."
                )
            java = shutil.which("java")
            if not java:
                raise DownloadError("Java پیدا نشد. برای APKEditor به Java 17+ نیاز است.")
            command = f'"{java}" -jar "{apkeditor}" m -i "{input_path}" -o "{output_path}"'

        try:
            await run_command(command)
        except CommandError as exc:
            raise DownloadError(f"تبدیل APKS به APK ناموفق بود: {exc}") from exc

        if not output_path.exists():
            raise DownloadError("فایل APK بعد از تبدیل پیدا نشد.")

        return await self._sign_if_configured(output_path)

    async def _sign_if_configured(self, apk_path: Path) -> Path:
        command_template = self._settings.sign_apk_cmd
        if not command_template:
            return apk_path

        signed_path = apk_path.with_name(f"{apk_path.stem}-signed.apk")
        command = self._render(command_template, input=str(apk_path), output=str(signed_path))
        try:
            await run_command(command)
        except CommandError as exc:
            raise DownloadError(f"امضای APK ناموفق بود: {exc}") from exc

        if not signed_path.exists():
            raise DownloadError("فایل APK امضا شده پیدا نشد.")
        return signed_path

    @staticmethod
    def _render(template: str, **values: str) -> str:
        allowed = set(values)
        fields = {name for _, name, _, _ in Formatter().parse(template) if name}
        unknown = fields - allowed
        if unknown:
            raise DownloadError(f"متغیر ناشناخته در دستور تبدیل: {', '.join(sorted(unknown))}")
        return template.format(**values)
