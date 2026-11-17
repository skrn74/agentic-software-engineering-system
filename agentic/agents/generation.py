"""Greenfield generation agents: contract, code, tests, docs - plus the repair agent for both modes.

Offline mode renders reviewed templates. The orchestration, validation and repair loop around them are
what the assignment evaluates; an LLM-backed generator can replace `render_*` without touching them.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..models import Outcome, Unrecoverable

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

# Fault catalogue used by --inject-fault to demonstrate detection and repair.
GREENFIELD_DEFECTS = {
    "D1": {
        "file": "shortener/service.py",
        "old": "        self._repo.record_click(code, now, referrer)\n", "new": "",
        "tests": ["test_resolve_records_click", "test_stats_aggregates", "test_create_redirect_and_stats_flow"],
        "desc": "redirect path forgets to record the click (analytics silently broken)",
    },
}


def render_tree(subdir: str, dest_prefix: str) -> dict[str, str]:
    out = {}
    for tpl in sorted((TEMPLATES / subdir).glob("*.tpl")):
        out[f"{dest_prefix}/{tpl.name[:-4]}"] = tpl.read_text(encoding="utf-8")
    return out


def render_greenfield_code() -> dict[str, str]:
    return render_tree("shortener", "project/shortener")


def apply_defect(files: dict[str, str], catalog: dict, did: str, prefix: str = "project/") -> None:
    d = catalog[did]
    key = prefix + d["file"]
    if d["old"] not in files[key]:
        raise RuntimeError(f"defect {did} does not apply to {key}")
    files[key] = files[key].replace(d["old"], d["new"])


# ----------------------------------------------------------------------------- agents
def contract(task, ctx) -> Outcome:
    api = ctx.get("design")["api"]
    schemas = {
        "Link": {"type": "object", "required": ["code", "short_url", "url", "created_at"],
                 "properties": {k: {"type": "string"} for k in ("code", "short_url", "url", "created_at")}},
        "LinkStats": {"type": "object", "required": ["code", "total_clicks", "clicks_by_day", "top_referrers"],
                      "properties": {"code": {"type": "string"}, "total_clicks": {"type": "integer"},
                                     "clicks_by_day": {"type": "array", "items": {"type": "object"}},
                                     "top_referrers": {"type": "array", "items": {"type": "object"}}}},
        "Error": {"type": "object", "required": ["error"],
                  "properties": {"error": {"type": "object", "required": ["code", "message"],
                                           "properties": {"code": {"type": "string"}, "message": {"type": "string"}}}}},
    }
    paths: dict = {}
    for a in api:
        responses = {}
        for status, text in a["responses"].items():
            resp: dict = {"description": text}
            if status in ("200", "201") and a.get("schema"):
                resp["content"] = {"application/json": {"schema": {"$ref": f"#/components/schemas/{a['schema']}"}}}
            elif status.startswith("4"):
                resp["content"] = {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}
            elif status == "302":
                resp["headers"] = {"Location": {"schema": {"type": "string"}}}
            responses[status] = resp
        op = {"operationId": a["op"], "summary": a["summary"], "responses": responses}
        if "{code}" in a["path"]:
            op["parameters"] = [{"name": "code", "in": "path", "required": True, "schema": {"type": "string"}}]
        if a["method"] == "POST":
            op["requestBody"] = {"required": True, "content": {"application/json": {"schema": {
                "type": "object", "required": ["url"],
                "properties": {"url": {"type": "string", "format": "uri"}, "alias": {"type": "string"}}}}}}
        paths.setdefault(a["path"], {})[a["method"].lower()] = op
    spec = {"openapi": "3.0.3", "info": {"title": "URL Shortener API", "version": "1.0.0"}, "paths": paths,
            "components": {"schemas": schemas}}
    ctx.write("project/openapi.json", json.dumps(spec, indent=2) + "\n")
    return Outcome(f"OpenAPI 3.0.3 with {sum(len(v) for v in paths.values())} operations", {"operations": len(api)})


def code(task, ctx) -> Outcome:
    files = render_greenfield_code()
    injected = []
    if ctx.options.get("inject_fault"):
        apply_defect(files, GREENFIELD_DEFECTS, "D1")
        injected.append("D1")
        ctx.log(task.id, "fault", "injected D1: " + GREENFIELD_DEFECTS["D1"]["desc"])
    ctx.put("active_defects", injected)
    for rel, text in files.items():
        ctx.write(rel, text)
    return Outcome(f"{len(files)} source files", {"files": sorted(files), "defects_injected": injected})


def tests(task, ctx) -> Outcome:
    files = render_tree("shortener_tests", "project/tests")
    for rel, text in files.items():
        ctx.write(rel, text)
    count = sum(t.count("    def test_") for t in files.values())
    return Outcome(f"{len(files)} test files, {count} test methods (unit, integration, contract)",
                   {"files": sorted(files), "test_methods": count})


def docs(task, ctx) -> Outcome:
    api = ctx.get("design")["api"]
    rows = "\n".join(f"| {a['method']} | `{a['path']}` | {a['summary']} |" for a in api)
    readme = f"""# URL Shortener

Generated by the agentic engineering system. Zero third-party dependencies (Python 3.9+).

## Run

```
python -m shortener.app            # serves on :8080, SQLite file shortener.db
curl -X POST localhost:8080/api/v1/links -H "Content-Type: application/json" -d '{{"url":"https://example.com/a/long/path"}}'
curl -i localhost:8080/<code>
curl localhost:8080/api/v1/links/<code>/stats
```

Configuration (environment): `PORT` (8080), `DB_PATH` (shortener.db), `BASE_URL` (http://localhost:8080).

## API

| Method | Path | Purpose |
|---|---|---|
{rows}

The full contract is in `openapi.json`; a contract test keeps the code and the contract in sync.

## Test

```
python -m unittest discover -s tests -t . -v
```

## Production notes

- Serve with a WSGI server (for example gunicorn) behind a load balancer; keep the API tier stateless.
- Replace SQLite with PostgreSQL by implementing the repository interface (`shortener/repository.py`).
- Add a cache, asynchronous analytics, rate limiting and abuse checks before real traffic (see `docs/03_design.md`).
"""
    runbook = """# Runbook

| Symptom | Check | Action |
|---|---|---|
| 5xx on create | Application log, database file permissions or disk space | Fix storage; retry is safe (codes are unique) |
| Redirects 404 | `GET /api/v1/links/<code>/stats` | Confirm the code exists in the `links` table |
| Slow redirects | Datastore latency; click insert on the request path | Add a cache; make analytics asynchronous |
| Analytics missing | `clicks` table and recent deployments | Roll back the last release |
"""
    ctx.write("project/README.md", readme)
    ctx.write("project/docs/runbook.md", runbook)
    return Outcome("README and runbook", {"files": ["project/README.md", "project/docs/runbook.md"]})


def repair(task, ctx) -> Outcome:
    """Map failing tests to the defect that caused them and regenerate only that file from the clean template."""
    from . import brownfield

    failure = ctx.get("validation_failure", {})
    failed = " ".join(failure.get("failures", []))
    mode = ctx.get("analyze")["type"]
    catalog = GREENFIELD_DEFECTS if mode == "greenfield" else brownfield.defects_for(ctx.get("analyze")["patch_id"])
    clean = render_greenfield_code() if mode == "greenfield" else brownfield.render_patch(ctx.get("analyze"), clean=True)
    active = list(ctx.get("active_defects", []))
    fixed = []
    for did in list(active):
        d = catalog.get(did)
        if d and any(name in failed for name in d["tests"]):
            key = "project/" + d["file"]
            ctx.write(key, clean[key])
            active.remove(did)
            fixed.append(did)
            ctx.log(task.id, "repaired", f"{did}: regenerated {d['file']} ({d['desc']})")
    if not fixed:
        raise Unrecoverable("no repair rule matches the failing tests; escalate to a human or an LLM-backed repair agent. "
                            f"Failing: {failed or failure.get('static', 'unknown')}")
    ctx.put("active_defects", active)
    return Outcome(f"repaired {', '.join(fixed)}", {"fixed": fixed})
