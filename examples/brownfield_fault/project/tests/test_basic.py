import io
import json
import unittest

from app import make_app
from store import Store


def call(app, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else b""
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "wsgi.input": io.BytesIO(data), "CONTENT_LENGTH": str(len(data))}
    captured = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(headers)

    raw = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], json.loads(raw) if raw else None


class TestBasic(unittest.TestCase):
    def setUp(self):
        self.app = make_app(Store())

    def test_shorten_and_redirect(self):
        status, _, body = call(self.app, "POST", "/shorten", {"url": "https://example.com/a"})
        self.assertEqual(status, 201)
        status, headers, _ = call(self.app, "GET", "/" + body["code"])
        self.assertEqual((status, headers["Location"]), (302, "https://example.com/a"))

    def test_unknown_code_returns_404(self):
        self.assertEqual(call(self.app, "GET", "/zzzz")[0], 404)

    def test_missing_url_returns_400(self):
        self.assertEqual(call(self.app, "POST", "/shorten", {})[0], 400)


if __name__ == "__main__":
    unittest.main()
