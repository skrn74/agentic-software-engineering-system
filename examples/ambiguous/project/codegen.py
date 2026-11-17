import hashlib


def make_code(url):
    """Derive a short code from the URL."""
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:4]
