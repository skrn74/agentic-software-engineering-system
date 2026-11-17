"""Domain rules: pure functions with no I/O, so they are cheap to test."""
import re
import secrets
from urllib.parse import urlsplit

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
CODE_LENGTH = 7  # 62**7 = ~3.5 trillion codes
MAX_URL_LENGTH = 2048
ALIAS_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
RESERVED_ALIASES = {"api", "healthz", "static", "admin"}


class ShortenerError(Exception):
    status = 400
    code = "bad_request"


class ValidationError(ShortenerError):
    status = 400
    code = "invalid_request"


class NotFound(ShortenerError):
    status = 404
    code = "not_found"


class Conflict(ShortenerError):
    status = 409
    code = "conflict"


def generate_code(length: int = CODE_LENGTH) -> str:
    """Random base62 code from a cryptographically secure source (not guessable or enumerable)."""
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def validate_url(url) -> str:
    """Accept only absolute http(s) URLs. Rejects javascript:, data:, ftp: and malformed input."""
    if not isinstance(url, str):
        raise ValidationError("url must be a string")
    url = url.strip()
    if not url:
        raise ValidationError("url is required")
    if len(url) > MAX_URL_LENGTH:
        raise ValidationError(f"url is longer than {MAX_URL_LENGTH} characters")
    if any(ch.isspace() or ord(ch) < 32 for ch in url):
        raise ValidationError("url must not contain whitespace or control characters")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValidationError("url scheme must be http or https")
    if not parts.hostname:
        raise ValidationError("url must include a host")
    return url


def validate_alias(alias) -> str:
    if not isinstance(alias, str) or not ALIAS_RE.match(alias):
        raise ValidationError("alias must be 3-32 characters: letters, digits, '-' or '_'")
    if alias.lower() in RESERVED_ALIASES:
        raise ValidationError("alias is reserved")
    return alias
