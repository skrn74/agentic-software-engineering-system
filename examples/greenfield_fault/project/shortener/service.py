"""Business logic. Depends only on the repository interface, never on HTTP."""
from datetime import datetime, timezone

from .domain import Conflict, NotFound, generate_code, validate_alias, validate_url


class ShortenerService:
    def __init__(self, repo, base_url: str = "http://localhost:8080", clock=None,
                 code_factory=generate_code, max_attempts: int = 5):
        self._repo = repo
        self._base_url = base_url.rstrip("/")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._code_factory = code_factory
        self._max_attempts = max_attempts

    def _now(self) -> str:
        return self._clock().strftime("%Y-%m-%dT%H:%M:%SZ")

    def shorten(self, url, alias=None) -> dict:
        url = validate_url(url)
        now = self._now()
        if alias is not None:
            alias = validate_alias(alias)
            if not self._repo.create_link(alias, url, now):
                raise Conflict("alias is already in use")
            code = alias
        else:
            for _ in range(self._max_attempts):
                code = self._code_factory()
                if self._repo.create_link(code, url, now):
                    break
            else:
                raise RuntimeError("could not allocate a unique code")
        return {"code": code, "short_url": f"{self._base_url}/{code}", "url": url, "created_at": now}

    def resolve(self, code: str, referrer=None) -> str:
        url = self._repo.get_url(code)
        if url is None:
            raise NotFound("unknown short code")
        now = self._now()
        self._repo.record_click(code, now, referrer)
        return url

    def stats(self, code: str) -> dict:
        if self._repo.get_url(code) is None:
            raise NotFound("unknown short code")
        return {"code": code, **self._repo.stats(code)}
