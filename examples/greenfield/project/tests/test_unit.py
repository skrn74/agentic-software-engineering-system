import unittest
from datetime import datetime, timezone

from shortener.domain import (ALPHABET, CODE_LENGTH, Conflict, NotFound, ValidationError,
                              generate_code, validate_alias, validate_url)
from shortener.repository import SqliteRepository
from shortener.service import ShortenerService


class FakeClock:
    def __init__(self):
        self.now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


class TestDomain(unittest.TestCase):
    def test_generate_code_uses_base62_alphabet_and_fixed_length(self):
        code = generate_code()
        self.assertEqual(len(code), CODE_LENGTH)
        self.assertTrue(set(code) <= set(ALPHABET))

    def test_generate_code_is_unique_over_a_sample(self):
        self.assertEqual(len({generate_code() for _ in range(2000)}), 2000)

    def test_validate_url_accepts_http_and_https(self):
        self.assertEqual(validate_url(" https://example.com/a?b=1 "), "https://example.com/a?b=1")
        self.assertEqual(validate_url("http://localhost:8080/x"), "http://localhost:8080/x")

    def test_validate_url_rejects_dangerous_or_malformed_input(self):
        bad = ["", "   ", "javascript:alert(1)", "data:text/html,hi", "ftp://example.com", "http://",
               "not a url", "http://exa mple.com", "https://example.com/" + "a" * 2100, None, 42]
        for value in bad:
            with self.subTest(value=str(value)[:30]):
                with self.assertRaises(ValidationError):
                    validate_url(value)

    def test_validate_alias_rules(self):
        self.assertEqual(validate_alias("my-link_1"), "my-link_1")
        for bad in ["ab", "has space", "x" * 40, "api", "HEALTHZ", None]:
            with self.subTest(alias=bad):
                with self.assertRaises(ValidationError):
                    validate_alias(bad)


class TestService(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.repo = SqliteRepository(":memory:")
        self.service = ShortenerService(self.repo, base_url="http://sho.rt", clock=self.clock)

    def test_shorten_returns_short_url(self):
        result = self.service.shorten("https://example.com/page")
        self.assertEqual(result["url"], "https://example.com/page")
        self.assertEqual(result["short_url"], f"http://sho.rt/{result['code']}")

    def test_shorten_with_custom_alias(self):
        self.assertEqual(self.service.shorten("https://example.com", alias="my-link")["code"], "my-link")

    def test_alias_conflict_raises(self):
        self.service.shorten("https://example.com", alias="taken")
        with self.assertRaises(Conflict):
            self.service.shorten("https://other.example", alias="taken")

    def test_collision_is_retried_with_a_new_code(self):
        codes = iter(["aaaaaaa", "aaaaaaa", "bbbbbbb"])
        service = ShortenerService(self.repo, clock=self.clock, code_factory=lambda: next(codes))
        first = service.shorten("https://one.example")
        second = service.shorten("https://two.example")
        self.assertEqual((first["code"], second["code"]), ("aaaaaaa", "bbbbbbb"))
        self.assertEqual(service.resolve("aaaaaaa"), "https://one.example")

    def test_resolve_unknown_code_raises_not_found(self):
        with self.assertRaises(NotFound):
            self.service.resolve("missing")

    def test_resolve_records_click(self):
        code = self.service.shorten("https://example.com")["code"]
        self.service.resolve(code)
        self.assertEqual(self.service.stats(code)["total_clicks"], 1)

    def test_stats_aggregates_clicks_by_day_and_referrer(self):
        code = self.service.shorten("https://example.com")["code"]
        self.service.resolve(code, "a.example")
        self.service.resolve(code, "a.example")
        self.clock.now = datetime(2026, 1, 2, 9, 0, tzinfo=timezone.utc)
        self.service.resolve(code)
        stats = self.service.stats(code)
        self.assertEqual(stats["total_clicks"], 3)
        self.assertEqual(stats["clicks_by_day"], [{"date": "2026-01-01", "count": 2}, {"date": "2026-01-02", "count": 1}])
        self.assertEqual(stats["top_referrers"][0], {"referrer": "a.example", "count": 2})
        self.assertEqual(stats["top_referrers"][1], {"referrer": "(direct)", "count": 1})


if __name__ == "__main__":
    unittest.main()
