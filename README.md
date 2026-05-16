# PlayDL

PlayDL is a Telegram bot that takes a Google Play link, downloads the app, merges split APKs when needed, and sends a regular installable APK back to the user.

The bot is built with Python 3.13 and aiogram 3.28.x

Persian guide: [README-Fa.md](README-Fa.md)

## What It Does

- Extracts the package name from the link.
- Downloads the app with one of the supported downloader backends.
- Converts `.apks` or split APK folders into one installable `.apk`.
- Uploads the final APK to the user through Telegram.
- Saves user/job status in MongoDB.

## Requirements

- Python 3.13
- MongoDB
- Java 17+
- Telegram Bot API local server
- One Google Play downloader backend:
  - Recommended: [`alltechdev/gplay-apk-downloader`](https://github.com/alltechdev/gplay-apk-downloader)
  - Alternative: [`gplaydl`](https://pypi.org/project/gplaydl/)
  - Alternative: [`apkeep`](https://github.com/EFForg/apkeep)
- [`APKEditor.jar`](https://github.com/REAndroid/APKEditor/releases) for merging split APKs

PlayDL can install missing helper tools on startup when `AUTO_INSTALL_TOOLS=true`. It can clone `alltechdev/gplay-apk-downloader`, install `gplaydl` with pip, install `apkeep` with Cargo if Rust is present, and download the latest APKEditor jar. It does not install OS services/packages such as Java, MongoDB, Telegram Bot API server, git, or Rust.

## Install

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env
python Main.py
```

On Windows PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

## Install Java

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y openjdk-17-jre-headless
java -version
```

Full JDK, if you need it:

```bash
sudo apt install -y openjdk-17-jdk
```

CentOS/RHEL/Rocky:

```bash
sudo dnf install -y java-17-openjdk
java -version
```

## APKEditor

Download the latest `APKEditor-*.jar` from:

https://github.com/REAndroid/APKEditor/releases

Place it here:

```text
tools/APKEditor.jar
```

Or point to it in `.env`:

```env
APKEDITOR_JAR=/opt/apkeditor/APKEditor.jar
```

## Configuration

Edit `.env`:

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

## Downloader Setup

### Recommended: alltech gplay

This backend is closest to what the bot needs. It downloads Google Play files and can merge/sign split APKs.

```env
PLAY_DOWNLOADER_BACKEND=alltech-gplay
ALLTECH_GPLAY_PATH=tools/gplay-apk-downloader/gplay
ALLTECH_AUTO_AUTH=true
ALLTECH_AUTH_FILE=~/.gplay-auth.json
PLAY_ARCH=arm64
MERGE_SPLITS=true
```

With `AUTO_INSTALL_TOOLS=true`, the bot clones this repo into `tools/gplay-apk-downloader` if it is missing. With `ALLTECH_AUTO_AUTH=true`, it also runs `gplay auth` once if `~/.gplay-auth.json` is missing.

### gplaydl

`gplaydl` is installed by `requirements.txt`. It can download base and split APK files. PlayDL then merges them with APKEditor.

```env
PLAY_DOWNLOADER_BACKEND=gplaydl
PLAY_ARCH=arm64
APKEDITOR_JAR=tools/APKEditor.jar
```

With auto-install enabled, the bot runs `python -m pip install gplaydl>=2.1,<3` if the `gplaydl` command is missing.

### apkeep

Good if you already use apkeep and have Google Play credentials or an AAS token.

```env
PLAY_DOWNLOADER_BACKEND=apkeep
APKEEP_SOURCE=google-play
APKEEP_EMAIL=you@example.com
APKEEP_TOKEN=your_aas_token
```

With auto-install enabled, the bot runs `cargo install apkeep` if `apkeep` is missing and Cargo is available.

### Custom command

Use this when you have your own downloader script.

```env
PLAY_DOWNLOADER_BACKEND=custom
PLAY_DOWNLOADER_CMD=apkeep -a "{package}" "{output_dir}"
APKS_TO_APK_CMD=java -jar tools/APKEditor.jar m -i "{input}" -o "{output}"
```

Available template variables:

- `{url}`: full Google Play URL
- `{package}`: package name, for example `org.telegram.messenger`
- `{output_dir}`: job download folder
- `{arch}`: configured architecture, for example `arm64`

## Uploader Setup
go to nixfile.com, create an account and put the username & password in your **.env** file in `NIXFILE_USERNAME` and `NIXFILE_PASS` fields. the bot login in the first run and after that uses the saved session

## Run

```bash
python Main.py
```

## How Split APK Merging Works

If the downloader returns:

- one `.apk`: the bot sends it as-is
- one `.apks`: APKEditor merges it into `.apk`
- multiple split `.apk` files in a folder: APKEditor merges the folder into `merged.apk`

If `alltech-gplay` is used with `MERGE_SPLITS=true`, it gets the first chance to merge. If split files still come out, PlayDL runs its own APKEditor merge step.

## Project Layout

```text
App/        bot startup and configuration
Handlers/   aiogram class-based handlers
DataBase/   MongoDB access layer
Services/   download, conversion, job helpers
Utils/      Persian texts and inline keyboards
tools/      optional local jars/scripts
storage/    downloads and runtime files
```
# Important!
## this project uses Telegram-bot-api and you should set it up on your server to run this bot
