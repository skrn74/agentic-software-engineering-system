"""Tiny in-process WSGI client so integration tests need no server and no dependencies."""
import io
import json


def call(app, method, path, body=None, headers=None):
    data = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    environ = {
        "REQUEST_METHOD": method, "PATH_INFO": path, "SERVER_NAME": "test", "SERVER_PORT": "80",
        "wsgi.url_scheme": "http", "wsgi.input": io.BytesIO(data), "CONTENT_LENGTH": str(len(data)),
    }
    for key, value in (headers or {}).items():
        environ["HTTP_" + key.upper().replace("-", "_")] = value
    captured = {}

    def start_response(status, response_headers, exc_info=None):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(response_headers)

    raw = b"".join(app(environ, start_response))
    parsed = json.loads(raw) if raw and captured["headers"].get("Content-Type") == "application/json" else raw
    return captured["status"], captured["headers"], parsed
