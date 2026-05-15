import json
import os
import shutil
import stat
import sys
import urllib.request
from pathlib import Path

from App.config import Settings
from Services.commands import CommandError, run_process
from Services.downloader import DownloadError

ALLTECH_REPO_URL = "https://github.com/alltechdev/gplay-apk-downloader.git"
APKEDITOR_RELEASE_API = "https://api.github.com/repos/REAndroid/APKEditor/releases/latest"


async def ensure_tools(settings: Settings) -> None:
    if not settings.auto_install_tools:
        return

    backend = settings.play_downloader_backend.strip().lower()
    if backend in {"auto", "alltech-gplay"}:
        await _ensure_alltech(settings)
    elif backend == "gplaydl":
        await _ensure_gplaydl()
    elif backend == "apkeep":
        await _ensure_apkeep()

    if _needs_apkeditor(settings):
        await _ensure_apkeditor(settings.apkeditor_jar)


async def _ensure_alltech(settings: Settings) -> None:
    gplay_path = settings.alltech_gplay_path
    if gplay_path.exists():
        return

    repo_dir = gplay_path.parent
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    if repo_dir.exists() and any(repo_dir.iterdir()):
        raise DownloadError(f"ALLTECH_GPLAY_PATH parent exists but gplay missing: {repo_dir}")

    if not shutil.which("git"):
        raise DownloadError("git پیدا نشد. برای نصب خودکار alltech-gplay باید git نصب باشد.")

    await run_process(["git", "clone", "--depth", "1", ALLTECH_REPO_URL, str(repo_dir)])

    requirements = repo_dir / "requirements.txt"
    if requirements.exists():
        await run_process([sys.executable, "-m", "pip", "install", "-r", str(requirements)])

    if not gplay_path.exists():
        raise DownloadError(f"بعد از clone، فایل gplay پیدا نشد: {gplay_path}")

    if os.name != "nt":
        mode = gplay_path.stat().st_mode
        gplay_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


async def _ensure_gplaydl() -> None:
    if shutil.which("gplaydl"):
        return
    await run_process([sys.executable, "-m", "pip", "install", "gplaydl>=2.1,<3"])


async def _ensure_apkeep() -> None:
    if shutil.which("apkeep"):
        return
    if not shutil.which("cargo"):
        raise DownloadError("apkeep پیدا نشد. برای نصب خودکار آن Rust/Cargo لازم است.")
    await run_process(["cargo", "install", "apkeep"])


async def _ensure_apkeditor(jar_path: Path) -> None:
    if jar_path.exists():
        return
    jar_path.parent.mkdir(parents=True, exist_ok=True)

    asset_url = await _latest_apkeditor_asset_url()
    await _download_file(asset_url, jar_path)

    if not jar_path.exists():
        raise DownloadError(f"APKEditor دانلود شد اما فایل پیدا نشد: {jar_path}")


async def _latest_apkeditor_asset_url() -> str:
    def fetch() -> str:
        request = urllib.request.Request(
            APKEDITOR_RELEASE_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "PlayDL"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))

        for asset in payload.get("assets", []):
            name = asset.get("name", "")
            url = asset.get("browser_download_url")
            if name.endswith(".jar") and url:
                return url
        raise DownloadError("APKEditor jar در latest release پیدا نشد.")

    import asyncio

    return await asyncio.to_thread(fetch)


async def _download_file(url: str, destination: Path) -> None:
    def download() -> None:
        with urllib.request.urlopen(url, timeout=180) as response:
            destination.write_bytes(response.read())

    import asyncio

    try:
        await asyncio.to_thread(download)
    except OSError as exc:
        raise CommandError(str(exc)) from exc


def _needs_apkeditor(settings: Settings) -> bool:
    if settings.apks_to_apk_cmd:
        return False
    return settings.play_downloader_backend.strip().lower() in {
        "auto",
        "alltech-gplay",
        "gplaydl",
        "apkeep",
        "custom",
    }
