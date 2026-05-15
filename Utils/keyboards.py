from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📥 ارسال لینک گوگل پلی", callback_data="send_link")],
        ]
    )


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="لغو", callback_data="cancel")],
        ]
    )


def delivery_keyboard(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="تلگرام", callback_data=f"deliver:tg:{job_id}"),
                InlineKeyboardButton(text="لینک داخلی", callback_data=f"deliver:nx:{job_id}"),
            ],
        ]
    )


def link_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="دانلود فایل", url=url)],
        ]
    )
