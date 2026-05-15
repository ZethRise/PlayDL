from html import escape


def bold(value: str) -> str:
    return f"<b>{escape(value)}</b>"


def safe(value: object) -> str:
    return escape(str(value))
