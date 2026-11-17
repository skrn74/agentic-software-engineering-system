import os
import tempfile
import unittest

from shortener.app import create_app
from shortener.repository import SqliteRepository
from shortener.service import ShortenerService
from tests.helpers import call


def build_app(db_path):
    return create_app(ShortenerService(SqliteRepository(db_path), base_url="http://sho.rt"))


class TestHttpApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "test.db")
        self.app = build_app(self.db)

    def tearDown(self):
        self.app.service._repo.close()
        self.tmp.cleanup()

    def test_create_redirect_and_stats_flow(self):
        status, _, body = call(self.app, "POST", "/api/v1/links", {"url": "https://example.com/landing"})
        self.assertEqual(status, 201)
        code = body["code"]
        status, headers, _ = call(self.app, "GET", f"/{code}", headers={"Referer": "https://news.example/story"})
        self.assertEqual(status, 302)
        self.assertEqual(headers["Location"], "https://example.com/landing")
        status, _, stats = call(self.app, "GET", f"/api/v1/links/{code}/stats")
        self.assertEqual(status, 200)
        self.assertEqual(stats["total_clicks"], 1)
        self.assertEqual(stats["top_referrers"], [{"referrer": "news.example", "count": 1}])

    def test_data_persists_across_app_restarts(self):
        _, _, body = call(self.app, "POST", "/api/v1/links", {"url": "https://example.com/keep"})
        self.app.service._repo.close()
        self.app = build_app(self.db)
        status, headers, _ = call(self.app, "GET", f"/{body['code']}")
        self.assertEqual((status, headers["Location"]), (302, "https://example.com/keep"))

    def test_unknown_code_returns_404_json(self):
        status, _, body = call(self.app, "GET", "/nope123")
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], "not_found")

    def test_invalid_url_returns_400(self):
        status, _, body = call(self.app, "POST", "/api/v1/links", {"url": "javascript:alert(1)"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"]["code"], "invalid_request")

    def test_invalid_json_returns_400(self):
        status, _, _ = call(self.app, "POST", "/api/v1/links", b"{not json")
        self.assertEqual(status, 400)

    def test_alias_conflict_returns_409(self):
        call(self.app, "POST", "/api/v1/links", {"url": "https://example.com", "alias": "promo"})
        status, _, _ = call(self.app, "POST", "/api/v1/links", {"url": "https://other.example", "alias": "promo"})
        self.assertEqual(status, 409)

    def test_healthz(self):
        status, _, body = call(self.app, "GET", "/healthz")
        self.assertEqual((status, body), (200, {"status": "ok"}))

    def test_wrong_method_returns_405(self):
        status, _, _ = call(self.app, "DELETE", "/api/v1/links")
        self.assertEqual(status, 405)

    def test_stats_for_unknown_code_returns_404(self):
        status, _, _ = call(self.app, "GET", "/api/v1/links/missing/stats")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
