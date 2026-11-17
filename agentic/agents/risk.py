"""Risk agent: risk register, failure scenarios and an explicit validation strategy."""
from __future__ import annotations

from ..models import Outcome

GREENFIELD_RISKS = [
    ("R1", "Abuse: shortener used to hide phishing or malware destinations", "High", "High",
     "Scheme allow-list (done). Reputation checks, takedown workflow and per-client rate limits.", "Partly mitigated"),
    ("R2", "Dangerous URI schemes (javascript:, data:) used as redirect targets", "Medium", "High",
     "Only absolute http/https URLs with a host are accepted; covered by a unit test.", "Mitigated, tested"),
    ("R3", "Short-code guessing or enumeration", "Medium", "Medium",
     "Random 7-char base62 from a secure source (3.5T keyspace). Add rate limiting at the edge.", "Mitigated"),
    ("R4", "Code collision on creation", "Low", "Medium",
     "Unique constraint plus bounded retry; covered by a unit test with a forced collision.", "Mitigated, tested"),
    ("R5", "Hot links overload the datastore (100:1 read-heavy)", "High", "Medium",
     "Cache in front of the datastore; CDN for the most popular links.", "Design only"),
    ("R6", "SQLite single writer and synchronous click insert cap throughput", "High", "Medium",
     "Repository interface allows PostgreSQL; make analytics asynchronous via a queue.", "Design only"),
    ("R7", "Raw click data grows to terabytes per year", "High", "Medium",
     "Aggregate into daily counters and expire raw events.", "Design only"),
    ("R8", "PII leaks through referrers or user agents", "Medium", "Medium",
     "Only the referrer host is stored; no IP or user agent.", "Mitigated"),
    ("R9", "API contract drifts from the implementation", "Medium", "Medium",
     "Contract test compares routes, status codes and required fields to openapi.json.", "Mitigated, tested"),
    ("R10", "Data loss", "Low", "High", "Backups and replication in production; not in the prototype.", "Design only"),
]
BROWNFIELD_RISKS = {
    "collision_fix": [
        ("R1", "Existing short links break", "Medium", "High", "Lookup path unchanged; legacy-code regression test.", "Mitigated, tested"),
        ("R2", "Schema change breaks rollback", "Low", "Medium", "Additive CREATE TABLE IF NOT EXISTS only; old version ignores the new table.", "Mitigated"),
        ("R3", "Concurrent creation races on the same code", "Medium", "High", "INSERT OR IGNORE is atomic; the caller verifies the stored URL and retries.", "Mitigated"),
        ("R4", "New code format surprises consumers", "Low", "Low", "Documented; codes are opaque strings and lookup is by exact match.", "Accepted"),
        ("R5", "Analytics writes slow the redirect path", "Medium", "Medium", "One small insert per click; make asynchronous at scale.", "Design only"),
    ],
    "lru_cache": [
        ("R1", "Stale cache serves an outdated URL", "Medium", "High", "Entry invalidated on every save; covered by a test.", "Mitigated, tested"),
        ("R2", "Cache invalidation does not reach other processes", "High", "Medium", "In-process cache only: use a TTL or shared cache before running multiple workers.", "Known limitation"),
        ("R3", "Unbounded memory growth", "Low", "Medium", "Fixed-size LRU with eviction; covered by a test.", "Mitigated, tested"),
        ("R4", "Negative lookups hammer the database", "Low", "Low", "Unknown codes are deliberately not cached; a negative cache could be added.", "Accepted"),
    ],
}

FAILURES_GREENFIELD = [
    ("Datastore unavailable", "Create and redirect return 500 with a generic JSON error; no data is corrupted. Retry is safe."),
    ("Duplicate alias requested concurrently", "The unique constraint decides; the loser gets 409."),
    ("Malformed or oversized request", "400 with a JSON error; body size is capped at 64 KB."),
    ("Unknown short code", "404 JSON error; no click is recorded."),
    ("Click insert fails", "In the prototype the redirect fails with 500 (analytics is on the request path); production moves it off the path."),
]


def run(task, ctx) -> Outcome:
    req = ctx.get("analyze")
    if req["type"] == "greenfield":
        risks, failures = GREENFIELD_RISKS, FAILURES_GREENFIELD
        strategy = [
            ("Unit tests", "Domain rules and service behaviour with an in-memory repository and a fake clock."),
            ("Integration tests", "Full HTTP flow through the WSGI app with a real SQLite file, including restart persistence."),
            ("Contract tests", "Routes, status codes and required response fields are checked against openapi.json."),
            ("Static checks", "Syntax, banned calls, string-built SQL and hard-coded secrets are scanned in generated code."),
            ("Repair loop", "On failure, failing tests are mapped to the faulty module, which is regenerated and re-validated (bounded)."),
            ("Not covered", "Load, soak, chaos and multi-node behaviour; real payment-scale data; penetration testing."),
        ]
    else:
        pid = req["patch_id"]
        risks = BROWNFIELD_RISKS.get(pid, [("R1", "No change generated, so no change risk", "-", "-", "Analysis only.", "n/a")])
        failures = [("Patch breaks existing behaviour", "The full existing suite plus new tests must pass; otherwise the repair loop or a human intervenes."),
                    ("Change touches unrelated files", "Scope guard rejects any file not named by the impact analysis.")]
        strategy = [
            ("Baseline", "Existing tests run on the untouched repo first, so regressions are attributable."),
            ("Test-first, red check", "New tests are written before the fix and must FAIL on the unpatched repo (proves they reproduce the issue)."),
            ("Green check", "The full suite (existing plus new) must pass on the patched copy."),
            ("Scope guard", "Only modules named by the impact analysis may change."),
            ("Reviewable diff", "The change is delivered as changes.patch; the original repo is never modified."),
            ("Not covered", "Production traffic, multi-process behaviour and performance under load."),
        ]
    extra = ctx.reasoner.complete_json(
        "You are a senior reviewer. Reply as JSON: {\"risks\":[{\"risk\":str,\"mitigation\":str}]}. Max 3 items.", req["normalized"])
    llm_rows = []
    if isinstance(extra, dict) and isinstance(extra.get("risks"), list):
        for i, item in enumerate(extra["risks"][:3], 1):
            if isinstance(item, dict) and isinstance(item.get("risk"), str) and isinstance(item.get("mitigation"), str):
                llm_rows.append((f"L{i}", item["risk"][:200], "?", "?", item["mitigation"][:240], "LLM suggestion, unreviewed"))
    risks = list(risks) + llm_rows
    md = ["# 04 Risks, trade-offs and validation", "", "## Risk register", "", "| ID | Risk | Likelihood | Impact | Mitigation | Status |", "|---|---|---|---|---|---|"]
    md += [f"| {' | '.join(r)} |" for r in risks]
    md += ["", "## Failure scenarios", "", "| Scenario | Expected behaviour |", "|---|---|"] + [f"| {a} | {b} |" for a, b in failures]
    md += ["", "## Validation strategy", "", "| Layer | What it verifies |", "|---|---|"] + [f"| {a} | {b} |" for a, b in strategy]
    md += ["", "## Guardrails", "", "- Writes are confined to the run workspace (path-escape check).",
           "- Generated code is scanned for banned calls, string-built SQL and secrets.",
           "- Tests run in a subprocess with a hard timeout.",
           "- Repair is bounded (max 2 cycles); unknown failures escalate to a human.",
           "- Humans approve the design and the final outcome."]
    ctx.write("docs/04_risks_and_validation.md", "\n".join(md) + "\n")
    return Outcome(f"{len(risks)} risks, {len(failures)} failure scenarios, {len(strategy)} validation layers",
                   {"risks": risks, "failures": failures, "strategy": strategy})
