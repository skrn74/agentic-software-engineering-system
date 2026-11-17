"""Brownfield agents: baseline, test-first regression tests, red check, patch generation and diffing."""
from __future__ import annotations

import difflib
import hashlib
import re
import shutil
from pathlib import Path

from ..guardrails import run_unittests, safe_join
from ..models import Outcome, Unrecoverable
from .generation import TEMPLATES, apply_defect

PATCH_DEFECTS = {
    "collision_fix": {
        "D3": {"file": "app.py", "old": "MAX_ATTEMPTS = 8", "new": "MAX_ATTEMPTS = 1",
               "tests": ["test_forced_collision_does_not_overwrite"],
               "desc": "retry loop reduced to one attempt, so a collision is not resolved"},
    },
    "lru_cache": {
        "D4": {"file": "store.py", "old": "            self._cache.pop(code, None)  # invalidate: never serve a stale mapping\n",
               "new": "            pass\n", "tests": ["test_cache_invalidated_on_overwrite"],
               "desc": "cache is not invalidated on overwrite, so stale URLs are served"},
    },
}


def defects_for(patch_id) -> dict:
    return PATCH_DEFECTS.get(patch_id, {})


def _strip_blocks(text: str, name: str, keep: bool) -> str:
    block = re.compile(rf"^[ \t]*# \[\[{name}\]\]\n(.*?)^[ \t]*# \[\[/{name}\]\]\n", re.S | re.M)
    return block.sub(lambda m: m.group(1) if keep else "", text)


def render_patch(req: dict, clean: bool = True) -> dict[str, str]:
    """Files of the patched project, keyed 'project/<name>'."""
    pid = req["patch_id"]
    keep_analytics = "add_analytics" in req["intents"]
    out = {}
    for tpl in sorted((TEMPLATES / "patches" / pid).glob("*.tpl")):
        text = _strip_blocks(tpl.read_text(encoding="utf-8"), "analytics", keep_analytics)
        out[f"project/{tpl.name[:-4]}"] = text
    return out


def _copy_repo(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def find_md5_collision(n: int = 4):
    seen, i = {}, 0
    while True:
        url = f"https://example.com/page/{i}"
        key = hashlib.md5(url.encode()).hexdigest()[:n]
        if key in seen:
            return seen[key], url
        seen[key] = url
        i += 1


WSGI_HELPER = '''import io
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

'''

COLLISION_TESTS = '''
A = "__A__"
B = "__B__"


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
'''

ANALYTICS_TESTS = '''

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
'''

CACHE_TESTS = '''

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
'''


def write_tests(task, ctx) -> Outcome:
    req = ctx.get("analyze")
    pid = req["patch_id"]
    if pid == "collision_fix":
        a, b = find_md5_collision(4)
        body = COLLISION_TESTS.replace("__A__", a).replace("__B__", b)
        if "add_analytics" in req["intents"]:
            body += ANALYTICS_TESTS
        name = "test_regression_collision.py"
    elif pid == "lru_cache":
        body, name = CACHE_TESTS, "test_regression_cache.py"
    else:
        raise Unrecoverable("no regression-test template for this change")
    ctx.write(f"new_tests/{name}", WSGI_HELPER + body)
    count = len(re.findall(r"    def test_", body))
    return Outcome(f"{count} regression tests written before the fix (test-first)", {"file": name, "test_methods": count})


def baseline(task, ctx) -> Outcome:
    src = Path(ctx.get("scan")["repo"])
    dst = safe_join(ctx.run_dir, "scratch/baseline")
    _copy_repo(src, dst)
    res = run_unittests(dst)
    if not res["ok"]:
        raise Unrecoverable(f"existing test suite already fails before any change: {res['failures']}")
    return Outcome(f"existing suite healthy: {res['ran']} tests pass", {"ran": res["ran"], "seconds": res["seconds"]})


def red_check(task, ctx) -> Outcome:
    src = Path(ctx.get("scan")["repo"])
    dst = safe_join(ctx.run_dir, "scratch/red")
    _copy_repo(src, dst)
    name = ctx.get("tests")["file"]
    shutil.copy(safe_join(ctx.run_dir, f"new_tests/{name}"), dst / "tests" / name)
    res = run_unittests(dst)
    if res["ok"]:
        raise Unrecoverable("new tests PASS on the unpatched repo: they do not reproduce the problem")
    return Outcome(f"reproduced: {len(res['failures'])} of {res['ran']} tests fail on the unpatched repo (expected)",
                   {"failing_before_fix": res["failures"], "ran": res["ran"]})


def make_diff(ctx) -> dict:
    """Unified diff of original repo vs patched project, written to changes.patch."""
    src = Path(ctx.get("scan")["repo"])
    proj = safe_join(ctx.run_dir, "project")
    rels = sorted({p.relative_to(base).as_posix() for base in (src, proj) for p in base.rglob("*")
                   if p.is_file() and p.suffix in (".py", ".md") and "__pycache__" not in p.parts})
    chunks, changed = [], []
    for rel in rels:
        a = (src / rel).read_text(encoding="utf-8").splitlines(keepends=True) if (src / rel).exists() else []
        b = (proj / rel).read_text(encoding="utf-8").splitlines(keepends=True) if (proj / rel).exists() else []
        if a == b:
            continue
        changed.append(rel)
        chunks += difflib.unified_diff(a, b, fromfile=f"a/{rel}" if a else "/dev/null", tofile=f"b/{rel}")
    ctx.write("changes.patch", "".join(chunks))
    added = sum(1 for line in chunks if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in chunks if line.startswith("-") and not line.startswith("---"))
    return {"changed": changed, "added": added, "removed": removed}


def patch(task, ctx) -> Outcome:
    req = ctx.get("analyze")
    pid = req["patch_id"]
    src = Path(ctx.get("scan")["repo"])
    _copy_repo(src, safe_join(ctx.run_dir, "project"))          # the original repo is never modified
    files = render_patch(req)
    injected = []
    if ctx.options.get("inject_fault") and defects_for(pid):
        did = next(iter(defects_for(pid)))
        apply_defect(files, defects_for(pid), did)
        injected.append(did)
        ctx.log(task.id, "fault", f"injected {did}: {defects_for(pid)[did]['desc']}")
    ctx.put("active_defects", injected)
    for rel, text in files.items():
        ctx.write(rel, text)
    name = ctx.get("tests")["file"]
    shutil.copy(safe_join(ctx.run_dir, f"new_tests/{name}"), safe_join(ctx.run_dir, f"project/tests/{name}"))
    diff = make_diff(ctx)
    return Outcome(f"patched {len([c for c in diff['changed'] if not c.startswith('tests/')])} file(s): +{diff['added']} -{diff['removed']} lines",
                   {"changed": diff["changed"], "defects_injected": injected})
