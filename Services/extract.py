from urllib.parse import parse_qs, urlparse


def is_google_play_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and parsed.netloc in {
        "play.google.com",
        "www.play.google.com",
    }


def extract_package_name(value: str) -> str | None:
    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    package = query.get("id", [None])[0]
    if not package:
        return None
    return package.strip()
