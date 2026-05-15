# PlayDL

PlayDL یک ربات تلگرام برای دانلود برنامه از Google Play است. کاربر لینک برنامه را می‌فرستد، ربات برنامه را دانلود می‌کند، اگر فایل‌ها split باشند آن‌ها را به یک APK قابل نصب تبدیل می‌کند و فایل نهایی را در تلگرام برای کاربر می‌فرستد.

این پروژه با Python 3.13 و aiogram 3.28.x ساخته شده

English guide: [README.md](README.md)

## امکانات

- استخراج package name از لینک
- دانلود برنامه با چند backend مختلف
- تبدیل `.apks` یا split APKها به یک `.apk` معمولی
- ارسال APK نهایی در تلگرام
- ذخیره وضعیت jobها در MongoDB

## پیش‌نیازها

- Python 3.13
- MongoDB
- Java 17+
- Telegram Bot API local server
- یکی از دانلودرهای Google Play:
  - پیشنهاد اصلی: [`alltechdev/gplay-apk-downloader`](https://github.com/alltechdev/gplay-apk-downloader)
  - جایگزین: [`gplaydl`](https://pypi.org/project/gplaydl/)
  - جایگزین: [`apkeep`](https://github.com/EFForg/apkeep)
- [`APKEditor.jar`](https://github.com/REAndroid/APKEditor/releases) برای merge کردن split APKها

اگر `AUTO_INSTALL_TOOLS=true` باشد، PlayDL ابزارهای کمکی را موقع شروع نصب می‌کند: repo مربوط به `alltechdev/gplay-apk-downloader` را clone می‌کند، `gplaydl` را با pip نصب می‌کند، اگر Rust/Cargo نصب باشد `apkeep` را نصب می‌کند و آخرین APKEditor jar را دانلود می‌کند. سرویس‌ها و پکیج‌های سیستمی مثل Java، MongoDB، Telegram Bot API server، git و Rust را خودش نصب نمی‌کند.

## نصب

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env
python App.main
```

در Windows PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

## نصب Java

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y openjdk-17-jre-headless
java -version
```

اگر JDK کامل خواستی:

```bash
sudo apt install -y openjdk-17-jdk
```

CentOS/RHEL/Rocky:

```bash
sudo dnf install -y java-17-openjdk
java -version
```

## دریافت APKEditor

آخرین فایل `APKEditor-*.jar` را از این صفحه بگیر:

https://github.com/REAndroid/APKEditor/releases

بعد داخل این مسیر بگذار:

```text
tools/APKEditor.jar
```

یا مسیرش را در `.env` تنظیم کن:

```env
APKEDITOR_JAR=/opt/apkeditor/APKEditor.jar
```

## تنظیمات اصلی

فایل `.env` را ویرایش کن:

```env
BOT_TOKEN=123456:CHANGE_ME

TELEGRAM_API_BASE_URL=http://127.0.0.1:8081
TELEGRAM_API_IS_LOCAL=true

MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=playdl

AUTO_INSTALL_TOOLS=true
TOOLS_DIR=tools
DOWNLOAD_DIR=storage/downloads
MAX_PARALLEL_JOBS=2
```

## تنظیم دانلودر

### پیشنهاد اصلی: alltech gplay

این گزینه برای کار ما مناسب‌تر است، چون دانلود Google Play، merge، patch و signing را خودش انجام می‌دهد.

```env
PLAY_DOWNLOADER_BACKEND=alltech-gplay
ALLTECH_GPLAY_PATH=tools/gplay-apk-downloader/gplay
PLAY_ARCH=arm64
MERGE_SPLITS=true
```

اگر `AUTO_INSTALL_TOOLS=true` باشد، ربات این repo را داخل `tools/gplay-apk-downloader` clone می‌کند.

### gplaydl

`gplaydl` با `requirements.txt` نصب می‌شود. فایل‌های base و split را دانلود می‌کند و PlayDL آن‌ها را با APKEditor تبدیل می‌کند.

```env
PLAY_DOWNLOADER_BACKEND=gplaydl
PLAY_ARCH=arm64
APKEDITOR_JAR=tools/APKEditor.jar
```

اگر نصب خودکار فعال باشد و دستور `gplaydl` پیدا نشود، ربات آن را با pip نصب می‌کند.

### apkeep

اگر از apkeep استفاده می‌کنی و اکانت/توکن Google Play داری:

```env
PLAY_DOWNLOADER_BACKEND=apkeep
APKEEP_SOURCE=google-play
APKEEP_EMAIL=you@example.com
APKEEP_TOKEN=your_aas_token
```

اگر نصب خودکار فعال باشد و `apkeep` پیدا نشود، ربات با `cargo install apkeep` نصبش می‌کند. برای این حالت Rust/Cargo باید از قبل نصب باشد.

### دستور دلخواه

اگر دانلودر اختصاصی خودت را داری:

```env
PLAY_DOWNLOADER_BACKEND=custom
PLAY_DOWNLOADER_CMD=apkeep -a "{package}" "{output_dir}"
APKS_TO_APK_CMD=java -jar tools/APKEditor.jar m -i "{input}" -o "{output}"
```

متغیرهای قابل استفاده:

- `{url}`: لینک کامل Google Play
- `{package}`: نام پکیج، مثل `org.telegram.messenger`
- `{output_dir}`: پوشه دانلود همان job
- `{arch}`: معماری انتخاب شده، مثل `arm64`

## اجرا

```bash
python -m App.main
```

## تبدیل Split APK چطور انجام می‌شود؟

اگر دانلودر خروجی زیر را بدهد:

- یک `.apk`: همان فایل ارسال می‌شود
- یک `.apks`: با APKEditor به `.apk` تبدیل می‌شود
- چند split APK داخل یک پوشه: پوشه با APKEditor به `merged.apk` تبدیل می‌شود

اگر `alltech-gplay` با `MERGE_SPLITS=true` فعال باشد، اول خودش merge را انجام می‌دهد. اگر باز هم خروجی split بود، PlayDL مرحله merge با APKEditor را اجرا می‌کند.

## ساختار پروژه

```text
App/        شروع bot و تنظیمات
Handlers/   هندلرهای class-based aiogram
DataBase/   لایه MongoDB
Services/   دانلود، تبدیل و مدیریت job
Utils/      متن‌های فارسی و کیبوردهای inline
tools/      jarها و اسکریپت‌های اختیاری
storage/    فایل‌های دانلود و runtime
```
# مهم!
## این ربات بر روی Telegram-bot-api کار میکنه و باید خودتون روی سرورتون ستاپش کنید قبل از ران کردن این ربات
