import io
import json
import unittest
from unittest import mock

from app import make_app
from store import Store


def call(app, method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else b""
    environ = {"REQUEST_METHOD": method, "PATH_INFO": path, "wsgi.input": io.BytesIO(data), "CONTENT_LENGTH": str(len(data))}
    for key, value in (headers or {}).items():
        environ["HTTP_" + key.upper().replace("-", "_")] = value
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(response_headers)

    raw = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], json.loads(raw) if raw else None


A = "https://example.com/page/351"
B = "https://example.com/page/442"


class TestCollisionRegression(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.app = make_app(self.store)

    def _location(self, code):
        status, headers, _ = call(self.app, "GET", "/" + code)
        self.assertEqual(status, 302)
        return headers["Location"]

    def test_urls_sharing_the_old_hash_prefix_do_not_overwrite_each_other(self):
        # A and B have the same first 4 hex chars of their MD5 digest (the old scheme gave them one code)
        _, _, first = call(self.app, "POST", "/shorten", {"url": A})
        _, _, second = call(self.app, "POST", "/shorten", {"url": B})
        self.assertNotEqual(first["code"], second["code"])
        self.assertEqual(self._location(first["code"]), A)
        self.assertEqual(self._location(second["code"]), B)

    def test_forced_collision_does_not_overwrite(self):
        with mock.patch("app.make_code", side_effect=lambda url, attempt=0: "AAAA%d" % attempt):
            _, _, first = call(self.app, "POST", "/shorten", {"url": A})
            _, _, second = call(self.app, "POST", "/shorten", {"url": B})
        self.assertNotEqual(first["code"], second["code"])
        self.assertEqual(self._location(first["code"]), A)
        self.assertEqual(self._location(second["code"]), B)

    def test_legacy_codes_still_redirect(self):
        self.store.save("ab12", "https://old.example/page")
        self.assertEqual(self._location("ab12"), "https://old.example/page")


class TestAnalytics(unittest.TestCase):
    def setUp(self):
        self.app = make_app(Store())

    def test_redirects_are_recorded_and_reported_by_stats(self):
        _, _, created = call(self.app, "POST", "/shorten", {"url": "https://example.com/x"})
        code = created["code"]
        call(self.app, "GET", "/" + code, headers={"Referer": "https://news.example/story"})
        call(self.app, "GET", "/" + code, headers={"Referer": "https://news.example/other"})
        status, _, stats = call(self.app, "GET", "/stats/" + code)
        self.assertEqual(status, 200)
        self.assertEqual(stats["total_clicks"], 2)
        self.assertEqual(stats["top_referrers"], [{"referrer": "news.example", "count": 2}])

    def test_stats_for_unknown_code_returns_404(self):
        self.assertEqual(call(self.app, "GET", "/stats/nope")[0], 404)
