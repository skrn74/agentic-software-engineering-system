"""Contract tests: the running app must match openapi.json (routes, status codes, required fields)."""
import json
import pathlib
import unittest

from shortener.app import ROUTES, create_app
from shortener.repository import SqliteRepository
from shortener.service import ShortenerService
from tests.helpers import call

SPEC = json.loads((pathlib.Path(__file__).resolve().parent.parent / "openapi.json").read_text(encoding="utf-8"))


def _resolve(schema):
    if "$ref" in schema:
        return SPEC["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


class TestContract(unittest.TestCase):
    def setUp(self):
        self.app = create_app(ShortenerService(SqliteRepository(":memory:")))

    def _declared(self, method, path):
        return SPEC["paths"][path][method.lower()]["responses"]

    def _required_fields(self, method, path, status):
        content = self._declared(method, path)[str(status)].get("content", {})
        schema = content.get("application/json", {}).get("schema")
        return _resolve(schema).get("required", []) if schema else []

    def test_routes_match_the_spec(self):
        implemented = {(m, p) for m, p, _ in ROUTES}
        documented = {(m.upper(), p) for p, item in SPEC["paths"].items() for m in item}
        self.assertEqual(implemented, documented)

    def test_observed_status_codes_are_declared(self):
        _, _, created = call(self.app, "POST", "/api/v1/links", {"url": "https://example.com"})
        code = created["code"]
        calls = [
            ("POST", "/api/v1/links", "/api/v1/links", {"url": "https://example.com"}),
            ("POST", "/api/v1/links", "/api/v1/links", {"url": "nope"}),
            ("POST", "/api/v1/links", "/api/v1/links", {"url": "https://example.com", "alias": "dup"}),
            ("POST", "/api/v1/links", "/api/v1/links", {"url": "https://example.com", "alias": "dup"}),
            ("GET", "/api/v1/links/{code}/stats", f"/api/v1/links/{code}/stats", None),
            ("GET", "/api/v1/links/{code}/stats", "/api/v1/links/missing/stats", None),
            ("GET", "/healthz", "/healthz", None),
            ("GET", "/{code}", f"/{code}", None),
            ("GET", "/{code}", "/missing", None),
        ]
        for method, template, path, body in calls:
            with self.subTest(call=f"{method} {path}"):
                status, _, _ = call(self.app, method, path, body)
                self.assertIn(str(status), self._declared(method, template))

    def test_success_bodies_contain_required_fields(self):
        status, _, body = call(self.app, "POST", "/api/v1/links", {"url": "https://example.com"})
        for field in self._required_fields("POST", "/api/v1/links", status):
            self.assertIn(field, body)
        status, _, stats = call(self.app, "GET", f"/api/v1/links/{body['code']}/stats")
        for field in self._required_fields("GET", "/api/v1/links/{code}/stats", status):
            self.assertIn(field, stats)


if __name__ == "__main__":
    unittest.main()
