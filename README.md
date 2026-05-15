# PlayDL

ربات تلگرام فارسی برای گرفتن لینک Google Play، دانلود برنامه، تبدیل split APK / `.apks` به APK معمولی و ارسال فایل با Telegram Local Bot API.

## اجرا

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
python -m App.main
```

## ابزارهای لازم روی VPS

- پیشنهاد اصلی: `alltechdev/gplay-apk-downloader`، چون خودش download، merge، asset-pack patch و signing را انجام می‌دهد.
- جایگزین سبک‌تر: `gplaydl` برای دانلود base/split APKها، سپس `APKEditor.jar` برای merge.
- جایگزین دیگر: `apkeep`.
- Telegram Bot API local server فعال، سپس `TELEGRAM_API_BASE_URL` را تنظیم کنید.
- MongoDB فعال، سپس `MONGODB_URI` و `MONGODB_DB_NAME` را تنظیم کنید.

## تنظیم alltech

```env
PLAY_DOWNLOADER_BACKEND=alltech-gplay
ALLTECH_GPLAY_PATH=/opt/gplay-apk-downloader/gplay
PLAY_ARCH=arm64
MERGE_SPLITS=true
```

## تنظیم gplaydl

```env
PLAY_DOWNLOADER_BACKEND=gplaydl
APKEDITOR_JAR=/opt/apkeditor/APKEditor.jar
```

## تنظیم custom

```env
PLAY_DOWNLOADER_BACKEND=custom
PLAY_DOWNLOADER_CMD=apkeep -a "{package}" "{output_dir}"
APKS_TO_APK_CMD=java -jar tools/APKEditor.jar m -i "{input}" -o "{output}"
```

## تنظیم apkeep با Google Play

```env
PLAY_DOWNLOADER_BACKEND=apkeep
APKEEP_SOURCE=google-play
APKEEP_EMAIL=you@example.com
APKEEP_TOKEN=aas_token
```
