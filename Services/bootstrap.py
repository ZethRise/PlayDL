import json
import logging
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
logger = logging.getLogger(__name__)


async def ensure_tools(settings: Settings) -> None:
    if not settings.auto_install_tools:
        logger.info("Auto tool install disabled")
        return

    backend = settings.play_downloader_backend.strip().lower()
    logger.info("Checking downloader tools for backend=%s", backend)
    if backend in {"auto", "alltech-gplay"}:
        await _ensure_alltech(settings)
    elif backend == "gplaydl":
        await _ensure_gplaydl()
    elif backend == "apkeep":
        await _ensure_apkeep()

    if _needs_apkeditor(settings):
        await _ensure_apkeditor(settings.apkeditor_jar)
    logger.info("Tool check finished")


async def _ensure_alltech(settings: Settings) -> None:
    gplay_path = settings.alltech_gplay_path
    if gplay_path.exists():
        await _ensure_alltech_venv(gplay_path.parent)
        logger.info("alltech-gplay found: %s", gplay_path)
        return

    repo_dir = gplay_path.parent
    repo_dir.parent.mkdir(parents=True, exist_ok=True)

    if repo_dir.exists() and any(repo_dir.iterdir()):
        raise DownloadError(f"ALLTECH_GPLAY_PATH parent exists but gplay missing: {repo_dir}")

    if not shutil.which("git"):
        raise DownloadError("git پیدا نشد. برای نصب خودکار alltech-gplay باید git نصب باشد.")

    logger.info("Cloning alltech-gplay into %s", repo_dir)
    await run_process(["git", "clone", "--depth", "1", ALLTECH_REPO_URL, str(repo_dir)])

    requirements = repo_dir / "requirements.txt"
    await _ensure_alltech_venv(repo_dir)

    if not gplay_path.exists():
        raise DownloadError(f"بعد از clone، فایل gplay پیدا نشد: {gplay_path}")

    if os.name != "nt":
        mode = gplay_path.stat().st_mode
        gplay_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    logger.info("alltech-gplay ready: %s", gplay_path)


async def _ensure_alltech_venv(repo_dir: Path) -> None:
    venv_python = repo_dir / ".venv" / "bin" / "python"
    venv_activate = repo_dir / ".venv" / "bin" / "activate"
    if os.name == "nt":
        venv_python = repo_dir / ".venv" / "Scripts" / "python.exe"
        venv_activate = repo_dir / ".venv" / "Scripts" / "activate"

    requirements = repo_dir / "requirements.txt"
    if venv_python.exists() and venv_activate.exists():
        return

    logger.info("Creating alltech-gplay venv in %s", repo_dir / ".venv")
    await run_process([sys.executable, "-m", "venv", str(repo_dir / ".venv")])

    if requirements.exists():
        logger.info("Installing alltech-gplay requirements into its venv")
        await _install_python_packages(["-r", str(requirements)], python_path=venv_python)


async def _ensure_gplaydl() -> None:
    if shutil.which("gplaydl"):
        logger.info("gplaydl found")
        return
    logger.info("Installing gplaydl")
    await _install_python_packages(["gplaydl>=2.1,<3"])


async def _ensure_apkeep() -> None:
    if shutil.which("apkeep"):
        logger.info("apkeep found")
        return
    if not shutil.which("cargo"):
        raise DownloadError("apkeep پیدا نشد. برای نصب خودکار آن Rust/Cargo لازم است.")
    logger.info("Installing apkeep with cargo")
    await run_process(["cargo", "install", "apkeep"], timeout=1800)


async def _install_python_packages(args: list[str], python_path: Path | None = None) -> None:
    python = str(python_path or sys.executable)
    pip_command = [python, "-m", "pip", "install", *args]
    try:
        await run_process(pip_command)
        return
    except CommandError as exc:
        if "No module named pip" not in str(exc):
            raise

    if not shutil.which("uv"):
        raise DownloadError("pip داخل venv وجود ندارد و uv هم پیدا نشد.")

    logger.info("pip missing; falling back to uv pip")
    uv_args = ["uv", "pip", "install", *args]
    if python_path:
        uv_args.extend(["--python", str(python_path)])
    await run_process(uv_args)


async def _ensure_apkeditor(jar_path: Path) -> None:
    if jar_path.exists():
        logger.info("APKEditor found: %s", jar_path)
        return
    jar_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Finding latest APKEditor release")
    asset_url = await _latest_apkeditor_asset_url()
    logger.info("Downloading APKEditor jar to %s", jar_path)
    await _download_file(asset_url, jar_path)

    if not jar_path.exists():
        raise DownloadError(f"APKEditor دانلود شد اما فایل پیدا نشد: {jar_path}")
    logger.info("APKEditor ready: %s", jar_path)


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
