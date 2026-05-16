# Contributing to PlayDL

Thanks for your interest in contributing to PlayDL! This document explains how to report issues, suggest features, and submit pull requests for the project.

PlayDL is a Telegram bot written in Python 3.13 using aiogram 3.28.x. It takes a Google Play link, downloads the app via one of several backends, merges split APKs when needed, and delivers a single installable APK back to the user.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Ways to Contribute](#ways-to-contribute)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)
- [Development Setup](#development-setup)
- [Project Layout](#project-layout)
- [Pull Request Process](#pull-request-process)
- [Coding Style](#coding-style)
- [Commit Messages](#commit-messages)
- [Testing Your Changes](#testing-your-changes)
- [Documentation](#documentation)
- [Questions](#questions)

## Code of Conduct

Be respectful, constructive, and patient. Assume good faith. Harassment, personal attacks, or discriminatory language are not welcome in issues, pull requests, or any other project space. Maintainers reserve the right to remove comments or block contributors who do not follow these expectations.

## Ways to Contribute

There are several ways you can help improve PlayDL:

- Reporting bugs you encounter while running the bot.
- Suggesting new features, downloader backends, or workflow improvements.
- Submitting pull requests for bug fixes, new features, or refactors.
- Improving documentation in `README.md`, `README-Fa.md`, or inline code comments.
- Translating the bot's user-facing messages (see `Utils/`).

## Reporting Bugs

Before opening a new issue, please:

1. Search the [existing issues](https://github.com/ZethRise/PlayDL/issues) to make sure your problem has not already been reported.
2. Make sure you are running a recent version of the project (pull from `main`).
3. Confirm that your environment matches the requirements in the README (Python 3.13, MongoDB, Java 17+, Telegram Bot API local server, a working downloader backend).

When filing a bug, please include:

- A clear, descriptive title.
- Steps to reproduce the problem.
- The expected behavior and what actually happened.
- Relevant logs or stack traces (please redact tokens, emails, and other secrets).
- Your environment: OS, Python version, downloader backend (`alltech-gplay`, `gplaydl`, `apkeep`, or `custom`), and architecture (`PLAY_ARCH`).
- The Google Play package name or URL that triggered the issue, if applicable and not sensitive.

## Suggesting Features

Feature requests are welcome. Please open an issue describing:

- The problem you are trying to solve.
- The proposed solution or behavior.
- Any alternatives you considered.
- Whether you would be willing to implement it yourself.

For larger changes (new backends, breaking config changes, major refactors), please open a discussion or issue before writing code so we can agree on the approach.

## Development Setup

Follow the install steps in the README, then set up the project for development:

```bash
git clone https://github.com/ZethRise/PlayDL.git
cd PlayDL
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your local values:

- `BOT_TOKEN` for a test bot (create one with @BotFather).
- `TELEGRAM_API_BASE_URL` pointing to your local Telegram Bot API server.
- `MONGODB_URI` pointing to a local MongoDB instance.
- A `PLAY_DOWNLOADER_BACKEND` of your choice and its required variables.

Please use a dedicated test bot and a separate MongoDB database while developing. Never commit `.env`, auth files (for example `~/.gplay-auth.json`), session data, or downloaded APKs.

Run the bot with:

```bash
python Main.py
```

## Project Layout

A quick map of where things live:

- `App/` — bot startup and configuration.
- `Handlers/` — aiogram class-based handlers for Telegram updates.
- `DataBase/` — MongoDB access layer.
- `Services/` — download, conversion, and job helpers.
- `Utils/` — Persian texts and inline keyboards.
- `tools/` — optional local jars and scripts (for example `APKEditor.jar`).
- `storage/` — downloads and runtime files (should not be committed).

When adding new functionality, try to keep code in the layer where it logically belongs. Download and conversion logic goes in `Services/`, Telegram-facing logic in `Handlers/`, and persistence in `DataBase/`.

## Pull Request Process

1. Fork the repository and create a feature branch from `main`:
   ```bash
   git checkout -b feature/short-description
   ```
2. Make your changes in small, focused commits.
3. Make sure the bot still starts cleanly and your change works end-to-end with at least one downloader backend.
4. Update documentation (`README.md`, `README-Fa.md`, `.env.example`, or this file) when you change behavior, configuration, or requirements.
5. Push your branch to your fork and open a pull request against `ZethRise/PlayDL:main`.
6. In the PR description, include:
   - A summary of what changed and why.
   - Any related issue numbers (for example `Closes #42`).
   - Configuration changes or migration notes, if any.
   - Manual test steps you performed.
7. Be responsive to review feedback. Small follow-up commits are fine; we can squash on merge if needed.

Please keep PRs focused. If you find unrelated issues while working, open separate PRs or issues for them.

## Coding Style

- Target Python 3.13 and use modern syntax (type hints, `match` statements, `async`/`await`).
- Follow [PEP 8](https://peps.python.org/pep-0008/) for general style.
- Prefer descriptive names over abbreviations.
- Use `async` functions for any I/O (network, database, subprocess) that has an async-friendly API. Avoid blocking the event loop.
- Wrap long-running blocking calls (for example `subprocess` invocations of `apkeep`, `gplaydl`, or `APKEditor`) in `asyncio.to_thread` or `run_in_executor` rather than calling them directly in async handlers.
- Keep secrets, tokens, and personal paths out of source. Read them from environment variables via the existing config layer.
- Log meaningful events (job start, backend chosen, merge result, errors) but never log full tokens or user credentials.

If you introduce new dependencies, add them to `requirements.txt` with a sensible version constraint and explain why in the PR description.

## Commit Messages

Write clear, imperative commit messages, for example:

```
Add retry logic to alltech-gplay backend
Fix split APK merge when APKEditor returns multiple files
Update README install steps for Windows PowerShell
```

Keep the subject line under about 72 characters. Add a longer body if the change needs explanation (motivation, trade-offs, follow-up work).

## Testing Your Changes

PlayDL is an integration-heavy project, so manual end-to-end testing is important. Before opening a PR, please verify at least the following with a test bot:

- The bot starts without errors using your `.env`.
- A Google Play link you send produces a downloadable APK in Telegram.
- If you changed merging logic, test with an app that returns split APKs (most large apps do).
- If you changed the database layer, confirm that job and user records are written and updated as expected.
- If you changed `AUTO_INSTALL_TOOLS` behavior, test both with the tool already installed and with it missing.

Describe your test steps and results in the PR description.

## Documentation

If your change affects how users install, configure, or run PlayDL, please update:

- `README.md` (English) — required.
- `README-Fa.md` (Persian) — appreciated; if you cannot write Persian, note it in the PR so a maintainer or another contributor can update it.
- `.env.example` — if you add or rename environment variables.

## Questions

If you are unsure about anything, open a draft pull request or an issue with the `question` label. It is better to ask early than to rework a large change later.

Thanks again for helping make PlayDL better!
