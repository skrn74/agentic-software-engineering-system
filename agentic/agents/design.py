"""Design agent: architecture, data model, API, capacity estimate and recorded decisions (ADR-style)."""
from __future__ import annotations

from ..models import Outcome, TransientError

API = [
    {"method": "POST", "path": "/api/v1/links", "op": "createLink", "summary": "Create a short link",
     "request": {"url": "string, required, http(s) only", "alias": "string, optional, 3-32 chars"},
     "responses": {"201": "Created", "400": "Invalid request", "409": "Alias already in use"}, "schema": "Link"},
    {"method": "GET", "path": "/api/v1/links/{code}/stats", "op": "getLinkStats", "summary": "Click analytics for a link",
     "responses": {"200": "Statistics", "404": "Unknown code"}, "schema": "LinkStats"},
    {"method": "GET", "path": "/{code}", "op": "redirect", "summary": "Redirect to the original URL",
     "responses": {"302": "Redirect to the original URL", "404": "Unknown code"}},
    {"method": "GET", "path": "/healthz", "op": "health", "summary": "Liveness check",
     "responses": {"200": "Service is up"}},
]


def capacity(p: dict) -> dict:
    secs_month = 30 * 24 * 3600
    writes = p["new_urls_per_month"] / secs_month
    reads = writes * p["read_write_ratio"]
    records = p["new_urls_per_month"] * 12 * p["retention_years"]
    keyspace = 62 ** 7
    events_day = reads * 86400
    return {
        "writes_per_s": round(writes, 1), "reads_per_s": round(reads), "peak_reads_per_s": round(reads * p["peak_factor"]),
        "records": records, "link_storage_tb": round(records * p["avg_record_bytes"] / 1e12, 2),
        "keyspace": keyspace, "keyspace_used_pct": round(records / keyspace * 100, 3),
        "click_events_per_day_m": round(events_day / 1e6),
        "raw_click_storage_tb_per_year": round(events_day * 365 * p["click_event_bytes"] / 1e12, 1),
    }


DECISIONS = [
    ("Short-code generation", "Random base62, 7 chars, unique constraint + retry",
     "Counter+base62 is enumerable and needs coordination; hash-of-URL collides and cannot give two codes for one URL. "
     "Random codes need no coordination across nodes; the unique key makes collisions safe (retry)."),
    ("Redirect status", "HTTP 302",
     "301 is cached by browsers, so repeat clicks would never reach the service and analytics would undercount."),
    ("Datastore", "SQLite behind a repository interface (prototype); PostgreSQL/DynamoDB in production",
     "Zero-dependency and testable now; the interface isolates the swap. SQLite has one writer, so it caps write throughput."),
    ("Click analytics path", "Synchronous insert (prototype); queue + aggregation in production",
     "Simple and correct now, but it adds a write to every redirect. At the assumed scale raw events dominate storage."),
    ("Caching", "None in the prototype; CDN/Redis cache of code->url in production",
     "Reads outnumber writes 100:1 and popular links are hot, so caching is the main read-scaling lever."),
    ("Framework", "Plain WSGI, standard library only",
     "Runs anywhere and tests run without installs. Production would serve it with gunicorn behind a load balancer."),
]


def run(task, ctx) -> Outcome:
    if ctx.options.get("inject_fault") and task.attempts == 1:
        raise TransientError("simulated tool timeout while loading design knowledge")   # demonstrates retry-with-backoff
    req = ctx.get("analyze")
    return _greenfield(ctx, req) if task.params.get("mode") == "greenfield" else _brownfield(ctx, req)


def _greenfield(ctx, req) -> Outcome:
    p = req["parameters"]
    cap = capacity(p)
    md = ["# 03 Design", "", "## Architecture (target)", "", "```mermaid", "flowchart LR",
          "  C[Clients] --> LB[Load balancer / CDN]", "  LB --> API[Stateless API pods]",
          "  API --> CACHE[(Redis cache: code -> url)]", "  API --> DB[(Primary datastore)]",
          "  API --> Q[[Click event queue]]", "  Q --> AGG[Aggregator]", "  AGG --> AN[(Analytics store)]", "```", "",
          "The prototype implements the API tier, the repository interface and synchronous analytics. The cache, queue and aggregator are design-only.", "",
          "## Components (prototype)", "", "| Module | Responsibility |", "|---|---|",
          "| domain | Validation rules, code generation, error types (pure functions) |",
          "| repository | SQL persistence behind a small interface |", "| service | Business logic: shorten, resolve, stats |",
          "| app | WSGI HTTP layer and route table |", "| openapi.json | API contract verified by tests |", "",
          "## Data model", "", "- `links(code PK, url, created_at)`", "- `clicks(id PK, code, ts, referrer)` indexed on `(code, ts)`", "",
          "## API", "", "| Method | Path | Purpose | Responses |", "|---|---|---|---|"]
    md += [f"| {a['method']} | `{a['path']}` | {a['summary']} | {', '.join(a['responses'])} |" for a in API]
    md += ["", "## Capacity estimate (from assumptions)", "", "| Item | Value |", "|---|---|",
           f"| New links | {p['new_urls_per_month']:,} per month = {cap['writes_per_s']}/s |",
           f"| Redirects | {cap['reads_per_s']:,}/s average, {cap['peak_reads_per_s']:,}/s at {p['peak_factor']}x peak |",
           f"| Link storage ({p['retention_years']} years) | {cap['records']:,} records = {cap['link_storage_tb']} TB |",
           f"| Keyspace | 62^7 = {cap['keyspace']:,}; {cap['keyspace_used_pct']}% used at retention, so collision retries stay rare |",
           f"| Raw click events | {cap['click_events_per_day_m']}M/day = {cap['raw_click_storage_tb_per_year']} TB/year: aggregate, do not keep raw forever |",
           "", "## Key decisions and trade-offs", ""]
    for name, choice, why in DECISIONS:
        md += [f"- **{name}: {choice}.** {why}"]
    md += ["", "## Scale-out path", "", "1. Add a cache in front of the datastore (largest read win).",
           "2. Move to PostgreSQL with read replicas; shard by hash of the code if writes outgrow one primary.",
           "3. Make analytics asynchronous: queue, then batch aggregation into daily counters.",
           "4. Add rate limiting, abuse checks (reputation lists) and API keys at the edge."]
    ctx.write("docs/03_design.md", "\n".join(md) + "\n")
    lines = ["Architecture: stateless WSGI API + repository (SQLite now, PostgreSQL later) + synchronous click analytics.",
             f"API: {len(API)} endpoints (create link, stats, redirect, health).",
             f"Capacity at assumed scale: {cap['writes_per_s']} writes/s, {cap['reads_per_s']:,} reads/s ({cap['peak_reads_per_s']:,} peak).",
             "Decisions: random base62 codes, 302 redirects, repository interface, plain WSGI.",
             f"Design-only (not built): cache, async analytics, rate limiting. Raw click data would reach {cap['raw_click_storage_tb_per_year']} TB/year."]
    return Outcome("greenfield design with capacity estimate", {"api": API, "capacity": cap, "decisions": DECISIONS, "gate_lines": lines})


def _brownfield(ctx, req) -> Outcome:
    imp = ctx.get("impact")
    patch = req["patch_id"]
    desc = {
        "collision_fix": ("Collision-safe code generation and click analytics",
                          ["Replace truncated MD5 (4 hex chars) with a salted SHA-256 base62 code of 7 characters, retried on conflict",
                           "Replace INSERT OR REPLACE with an atomic insert-if-absent so one URL can never overwrite another",
                           "Add a clicks table (additive) and a GET /stats/<code> endpoint"]),
        "lru_cache": ("Bounded LRU cache in the storage layer",
                      ["Add a fixed-size LRU in front of the SQLite lookup",
                       "Invalidate the cached entry whenever a code is saved or overwritten",
                       "Expose a db_reads counter so the effect is measurable in tests"]),
        None: ("No matching change template", ["Analysis only: no automatic change is generated in offline mode"]),
    }[patch]
    md = ["# 03 Design: change proposal", "", f"## {desc[0]}", ""] + [f"- {x}" for x in desc[1]] + [
        "", "## Scope (from impact analysis)", "", f"- Files that may be modified: {', '.join(imp['modify']) or 'none'}",
        f"- Files affected but not modified (regression-test targets): {', '.join(imp['affected']) or 'none'}", "",
        "## Compatibility and rollout", "",
        "- Public API is unchanged except for one additive endpoint (collision fix with analytics).",
        "- Existing short codes keep working: lookup is by code and the lookup path is unchanged." if patch == "collision_fix"
        else "- No API or schema change; behaviour is identical apart from speed.",
        "- Schema change is additive (`CREATE TABLE IF NOT EXISTS`), so rollback is a redeploy of the previous version." if patch == "collision_fix"
        else "- Rollback is a redeploy of the previous version; the cache is in memory and disappears on restart.", ""]
    ctx.write("docs/03_design.md", "\n".join(md) + "\n")
    lines = [f"Change: {desc[0]}"] + [f"  - {x}" for x in desc[1]] + [
        f"Files to modify: {', '.join(imp['modify']) or 'none'}", f"Affected (tested, not modified): {', '.join(imp['affected']) or 'none'}"]
    return Outcome(desc[0], {"patch_id": patch, "gate_lines": lines})
