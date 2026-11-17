import hashlib

ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
CODE_LENGTH = 7  # 62**7 = ~3.5 trillion codes (the old scheme had 65,536)


def make_code(url, attempt=0):
    """Derive a short code from the URL. `attempt` salts the hash so a collision can be retried."""
    digest = hashlib.sha256(f"{attempt}:{url}".encode("utf-8")).digest()
    n = int.from_bytes(digest[:8], "big")
    chars = []
    for _ in range(CODE_LENGTH):
        n, rem = divmod(n, 62)
        chars.append(ALPHABET[rem])
    return "".join(chars)
