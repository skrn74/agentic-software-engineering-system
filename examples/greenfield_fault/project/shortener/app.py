"""HTTP layer: a plain WSGI application (runs under wsgiref, gunicorn or uwsgi)."""
import http
import json
import os
import sys
from urllib.parse import urlsplit

from .domain import ShortenerError
from .repository import SqliteRepository
from .service import ShortenerService

MAX_BODY_BYTES = 64 * 1024

# Route table: also the single source of truth checked against openapi.json by the contract test.
ROUTES = [
    ("POST", "/api/v1/links", "create_link"),
    ("GET", "/api/v1/links/{code}/stats", "get_stats"),
    ("GET", "/healthz", "healthz"),
    ("GET", "/{code}", "redirect"),
]


def _match(template: str, path: str):
    t_parts, p_parts = template.strip("/").split("/"), path.strip("/").split("/")
    if len(t_parts) != len(p_parts):
        return None
    params = {}
    for t, p in zip(t_parts, p_parts):
        if t.startswith("{") and t.endswith("}"):
            if not p:
                return None
            params[t[1:-1]] = p
        elif t != p:
            return None
    return params


class App:
    def __init__(self, service: ShortenerService):
        self.service = service

    def __call__(self, environ, start_response):
        try:
            status, headers, body = self._dispatch(environ)
        except ShortenerError as exc:
            status, headers, body = exc.status, {}, {"error": {"code": exc.code, "message": str(exc)}}
        except Exception as exc:  # noqa: BLE001
            print(f"unhandled error: {exc!r}", file=sys.stderr)
            status, headers, body = 500, {}, {"error": {"code": "internal_error", "message": "internal error"}}
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        out_headers = {"Content-Length": str(len(payload)), **headers}
        if payload:
            out_headers["Content-Type"] = "application/json"
        start_response(f"{status} {http.HTTPStatus(status).phrase}", list(out_headers.items()))
        return [payload]

    def _dispatch(self, environ):
        method, path = environ["REQUEST_METHOD"], environ.get("PATH_INFO", "/")
        path_matched = False
        for r_method, template, handler in ROUTES:
            params = _match(template, path)
            if params is None:
                continue
            path_matched = True
            if r_method == method:
                return getattr(self, "_" + handler)(environ, **params)
        if path_matched:
            return 405, {}, {"error": {"code": "method_not_allowed", "message": f"{method} not allowed"}}
        return 404, {}, {"error": {"code": "not_found", "message": "no such route"}}

    # handlers ---------------------------------------------------------
    def _read_json(self, environ) -> dict:
        from .domain import ValidationError
        try:
            size = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            raise ValidationError("invalid Content-Length")
        if size > MAX_BODY_BYTES:
            raise ValidationError("request body too large")
        raw = environ["wsgi.input"].read(size) if size else b""
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            raise ValidationError("body must be valid JSON")
        if not isinstance(data, dict):
            raise ValidationError("body must be a JSON object")
        return data

    def _create_link(self, environ):
        body = self._read_json(environ)
        return 201, {}, self.service.shorten(body.get("url"), body.get("alias"))

    def _get_stats(self, environ, code):
        return 200, {}, self.service.stats(code)

    def _healthz(self, environ):
        return 200, {}, {"status": "ok"}

    def _redirect(self, environ, code):
        ref = environ.get("HTTP_REFERER")
        host = (urlsplit(ref).hostname or None) if ref else None   # store the host only: no paths, no PII
        url = self.service.resolve(code, host[:200] if host else None)
        return 302, {"Location": url}, None


def create_app(service: ShortenerService = None) -> App:
    if service is None:
        repo = SqliteRepository(os.environ.get("DB_PATH", "shortener.db"))
        service = ShortenerService(repo, base_url=os.environ.get("BASE_URL", "http://localhost:8080"))
    return App(service)


def main() -> None:
    from wsgiref.simple_server import make_server
    port = int(os.environ.get("PORT", "8080"))
    print(f"serving on http://0.0.0.0:{port}")
    make_server("0.0.0.0", port, create_app()).serve_forever()


if __name__ == "__main__":
    main()
