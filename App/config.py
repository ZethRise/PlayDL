from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(alias="BOT_TOKEN")
    telegram_api_base_url: str = Field(default="https://api.telegram.org", alias="TELEGRAM_API_BASE_URL")
    telegram_api_is_local: bool = Field(default=False, alias="TELEGRAM_API_IS_LOCAL")

    mongodb_uri: str = Field(default="mongodb://localhost:27017", alias="MONGODB_URI")
    mongodb_db_name: str = Field(default="playdl", alias="MONGODB_DB_NAME")
    tools_dir: Path = Field(default=Path("tools"), alias="TOOLS_DIR")
    download_dir: Path = Field(default=Path("storage/downloads"), alias="DOWNLOAD_DIR")
    max_parallel_jobs: int = Field(default=2, ge=1, le=10, alias="MAX_PARALLEL_JOBS")

    auto_install_tools: bool = Field(default=True, alias="AUTO_INSTALL_TOOLS")
    play_downloader_backend: str = Field(default="auto", alias="PLAY_DOWNLOADER_BACKEND")
    play_downloader_cmd: str | None = Field(default=None, alias="PLAY_DOWNLOADER_CMD")
    alltech_gplay_path: Path = Field(
        default=Path("tools/gplay-apk-downloader/gplay"),
        alias="ALLTECH_GPLAY_PATH",
    )
    play_arch: str = Field(default="arm64", alias="PLAY_ARCH")
    merge_splits: bool = Field(default=True, alias="MERGE_SPLITS")
    apkeep_source: str | None = Field(default=None, alias="APKEEP_SOURCE")
    apkeep_email: str | None = Field(default=None, alias="APKEEP_EMAIL")
    apkeep_token: str | None = Field(default=None, alias="APKEEP_TOKEN")

    apkeditor_jar: Path = Field(default=Path("tools/APKEditor.jar"), alias="APKEDITOR_JAR")
    apks_to_apk_cmd: str | None = Field(default=None, alias="APKS_TO_APK_CMD")
    sign_apk_cmd: str | None = Field(default=None, alias="SIGN_APK_CMD")


def load_settings() -> Settings:
    settings = Settings()
    settings.tools_dir.mkdir(parents=True, exist_ok=True)
    settings.download_dir.mkdir(parents=True, exist_ok=True)
    return settings
