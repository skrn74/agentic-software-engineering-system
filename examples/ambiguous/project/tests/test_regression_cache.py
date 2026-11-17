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



class TestLookupCache(unittest.TestCase):
    def test_repeat_lookup_is_served_from_cache(self):
        store = Store()
        store.save("abc", "https://a.example")
        for _ in range(3):
            self.assertEqual(store.get("abc"), "https://a.example")
        self.assertEqual(store.db_reads, 1)

    def test_cache_invalidated_on_overwrite(self):
        store = Store()
        store.save("abc", "https://a.example")
        store.get("abc")
        store.save("abc", "https://b.example")
        self.assertEqual(store.get("abc"), "https://b.example")

    def test_cache_is_bounded(self):
        store = Store(cache_size=2)
        for i in range(5):
            store.save(f"c{i}", f"https://e{i}.example")
            store.get(f"c{i}")
        self.assertLessEqual(len(store._cache), 2)

    def test_unknown_codes_are_not_cached(self):
        store = Store()
        self.assertIsNone(store.get("zzz"))
        self.assertIsNone(store.get("zzz"))
        self.assertEqual(store.db_reads, 2)

    def test_http_redirect_still_works(self):
        app = make_app(Store())
        _, _, created = call(app, "POST", "/shorten", {"url": "https://example.com/p"})
        status, headers, _ = call(app, "GET", "/" + created["code"])
        self.assertEqual((status, headers["Location"]), (302, "https://example.com/p"))
