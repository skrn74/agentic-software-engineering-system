"""Requirement agent: interpret intent, find ambiguities, normalise into an engineering problem."""
from __future__ import annotations

import re

from ..models import Outcome

NUMBER = re.compile(r"\d[\d,.]*\s*(k|m|b|million|billion|rps|qps|req|requests|ms|%|users)\b", re.I)
DATASTORE = re.compile(r"postgres|mysql|sqlite|dynamo|mongo|redis|cassandra|sql server|oracle", re.I)
AUTH_WORDS = re.compile(r"auth|login|api key|oauth|token|sso", re.I)

DEFAULT_PARAMS = {
    "new_urls_per_month": 100_000_000,
    "read_write_ratio": 100,
    "avg_record_bytes": 500,
    "retention_years": 5,
    "p95_redirect_ms": 100,
    "availability_pct": 99.9,
    "peak_factor": 3,
    "click_event_bytes": 100,
}


def _amb(aid, topic, question, assumption, severity="assumable"):
    return {"id": aid, "topic": topic, "question": question, "assumption": assumption,
            "severity": severity, "source": "rules"}


def analyze(text: str, repo_given: bool = False) -> dict:
    t = text.lower()
    domain = "url_shortener" if re.search(r"url.{0,25}shorten|shorten.{0,25}url|link.{0,10}shorten", t) else "generic"
    brownfield = repo_given or bool(re.search(
        r"\b(fix|bug|refactor|existing|enhance|slow|patch|regression|faster|speed)\b", t))
    req_type = "brownfield" if brownfield else "greenfield"

    intents: list[str] = []
    if re.search(r"collision|wrong (url|place|link|page)|overwrit|duplicate code|same code", t):
        intents.append("fix_collision")
    if re.search(r"analytic|stats|click|track", t):
        intents.append("add_analytics")
    if re.search(r"\bfast|slow|latenc|perform|speed|cache|optimi", t):
        intents.append("performance")

    ambiguities: list[dict] = []
    functional: list[str] = []
    non_functional: list[str] = []
    params: dict = {}
    patch_id = None

    if req_type == "greenfield" and domain == "url_shortener":
        functional = ["FR1 Create a short link for a long URL (optional custom alias) via a REST JSON API",
                      "FR2 Redirect a short code to the original URL (HTTP 302)"]
        if "persist" in t or "database" in t or "storage" in t:
            functional.append("FR3 Persist links durably so they survive restarts")
        if "analytic" in t:
            functional.append("FR4 Record clicks and expose analytics per link")
        functional.append("FR5 Validate input and return a consistent JSON error contract")
        non_functional = ["NFR1 Scalable: read-heavy workload, horizontally scalable stateless API tier",
                          "NFR2 Safe: only http/https destinations, no SQL injection, no PII in analytics",
                          "NFR3 Operable: health endpoint, structured errors, documented API"]
        params = dict(DEFAULT_PARAMS)
        if re.search(r"scalab|scale", t) and not NUMBER.search(t):
            ambiguities.append(_amb(
                "A1", "Scale", "What does 'scalable' mean in numbers (new URLs per month, redirects per second, latency, availability)?",
                "100M new URLs/month, 100:1 read:write, p95 redirect < 100 ms, 99.9% availability, 5-year retention."))
        if ("persist" in t or "database" in t) and not DATASTORE.search(t):
            ambiguities.append(_amb(
                "A2", "Datastore", "Which datastore, and how long must links be retained?",
                "SQLite behind a repository interface for the prototype; PostgreSQL or DynamoDB recommended in production."))
        if "analytic" in t:
            ambiguities.append(_amb(
                "A3", "Analytics scope", "Which metrics are needed, and may IP address or user agent be stored?",
                "Total clicks, clicks per day and top referrer hosts. No IP address or user agent is stored."))
        if "api" in t and not AUTH_WORDS.search(t):
            ambiguities.append(_amb(
                "A4", "Access control", "Who may create links, and is authentication or rate limiting required?",
                "No authentication in the prototype. API keys and rate limits are listed as production follow-up."))
        ambiguities.append(_amb(
            "A5", "Link semantics", "Must the same URL always return the same code? Are custom aliases or expiry needed?",
            "Every request creates a new random 7-char base62 code; optional custom alias; no expiry; redirects use 302 so every click is observable."))
        normalized = ("Build a URL shortener service exposing a REST JSON API to create short links and redirect to the original "
                      "URL (HTTP 302), persist links durably and record click analytics (total, per day, top referrers). "
                      "Assumed targets: 100M new URLs/month, 100:1 read:write, p95 redirect < 100 ms, 99.9% availability.")

    elif req_type == "brownfield":
        if "fix_collision" in intents:
            patch_id = "collision_fix"
            functional = ["FR1 Different URLs must never share a short code or overwrite one another",
                          "FR2 Existing short codes must keep redirecting correctly"]
            if "add_analytics" in intents:
                functional.append("FR3 Record clicks and expose per-link analytics")
            non_functional = ["NFR1 Backward compatible API and data", "NFR2 Additive, reversible schema change",
                              "NFR3 Regression test proves the bug before the fix and its absence after"]
            ambiguities.append(_amb(
                "B1", "Existing codes", "Must links created before the fix keep working, and may new codes use a different format?",
                "Yes: existing codes stay valid; new codes use a longer base62 format."))
            if "add_analytics" in intents:
                ambiguities.append(_amb(
                    "B2", "Analytics scope", "Which analytics are needed and what may be stored?",
                    "Total clicks, clicks per day, top referrer hosts. No IP address or user agent."))
            normalized = ("Fix the short-code collision bug in the existing URL shortener so that different URLs never overwrite "
                          "each other, keep existing codes working" + (", and add click analytics." if "add_analytics" in intents else "."))
        elif "performance" in intents:
            patch_id = "lru_cache"
            has_target = bool(NUMBER.search(t))
            if not has_target:
                ambiguities.append(_amb(
                    "B1", "Meaning of 'faster'", "Which operation must be faster (redirect lookup, link creation, stats) and by how much?",
                    "Redirect lookup. Success = repeated lookups of the same code are served without a database read.", "blocking"))
            if re.search(r"\bbetter\b|\bimprove", t):
                ambiguities.append(_amb(
                    "B2", "Meaning of 'better'", "'Better' is undefined: which quality attribute (speed, reliability, features, usability)?",
                    "Out of scope until defined. Only the performance change is made.", "blocking"))
            ambiguities.append(_amb(
                "B3", "Which users / traffic", "Which users or traffic pattern should benefit?",
                "Read-heavy redirect traffic with a skewed set of popular links."))
            functional = ["FR1 Repeated redirect lookups avoid a database round trip",
                          "FR2 A changed or overwritten code is never served stale"]
            non_functional = ["NFR1 Bounded memory (fixed-size cache)", "NFR2 No change to the public API"]
            normalized = ("Improve redirect-lookup performance of the existing URL shortener by caching hot lookups in a bounded "
                          "in-memory LRU with correct invalidation. (Interpretation of an under-specified request; needs confirmation.)")
        else:
            normalized = "Brownfield change requested, but no change template matches. Analysis and design only."
            functional = ["FR1 (to be defined with the requester)"]

    else:
        normalized = "Greenfield requirement outside the offline template set."

    blocking = sum(a["severity"] == "blocking" for a in ambiguities)
    level = "high" if blocking else ("medium" if len(ambiguities) >= 3 else "low")
    return {
        "raw": text, "type": req_type, "domain": domain, "intents": intents, "patch_id": patch_id,
        "functional": functional, "non_functional": non_functional, "ambiguities": ambiguities,
        "ambiguity_level": level, "parameters": params, "normalized": normalized,
        "assumptions": [f"{a['id']} {a['topic']}: {a['assumption']}" for a in ambiguities],
    }


def _render_md(d: dict) -> str:
    lines = ["# 01 Requirement analysis", "", f"**Input:** {d['raw']}", "",
             f"**Type:** {d['type']}  |  **Domain:** {d['domain']}  |  **Ambiguity level:** {d['ambiguity_level']}", "",
             "## Normalised engineering problem", "", d["normalized"], "", "## Functional requirements", ""]
    lines += [f"- {x}" for x in d["functional"]] + ["", "## Non-functional requirements", ""]
    lines += [f"- {x}" for x in d["non_functional"]] + ["", "## Ambiguities and proposed assumptions", ""]
    if d["ambiguities"]:
        lines += ["| ID | Topic | Question | Proposed assumption | Severity | Source |", "|---|---|---|---|---|---|"]
        lines += [f"| {a['id']} | {a['topic']} | {a['question']} | {a['assumption']} | {a['severity']} | {a['source']} |"
                  for a in d["ambiguities"]]
    else:
        lines.append("None found.")
    return "\n".join(lines) + "\n"


def run(task, ctx) -> Outcome:
    data = analyze(ctx.options["requirement"], bool(ctx.options.get("repo")))
    # Optional advisory enrichment from a hosted LLM (schema-validated, tagged source=llm).
    extra = ctx.reasoner.complete_json(
        "You are a requirements analyst. Reply as JSON: {\"ambiguities\":[{\"topic\":str,\"question\":str,\"assumption\":str}]}. Max 3 items.",
        data["raw"])
    if isinstance(extra, dict) and isinstance(extra.get("ambiguities"), list):
        for i, item in enumerate(extra["ambiguities"][:3], 1):
            if isinstance(item, dict) and all(isinstance(item.get(k), str) and item[k] for k in ("topic", "question", "assumption")):
                a = _amb(f"L{i}", item["topic"][:60], item["question"][:240], item["assumption"][:240])
                a["source"] = "llm"
                data["ambiguities"].append(a)
                data["assumptions"].append(f"{a['id']} {a['topic']}: {a['assumption']}")
    blocking = [a for a in data["ambiguities"] if a["severity"] == "blocking"]
    lines = [f"Interpreted as: {data['type']} / {data['domain']}", f"Normalised: {data['normalized']}", ""]
    if data["ambiguities"]:
        lines.append("Open questions and the assumption I will proceed with if you approve:")
        lines += [f"  [{a['severity'].upper()}] {a['id']} {a['question']}  ->  {a['assumption']}" for a in data["ambiguities"]]
    else:
        lines.append("No ambiguities detected.")
    data["gate_lines"] = lines
    ctx.write("docs/01_requirements.md", _render_md(data))
    return Outcome(f"{data['type']} / {data['domain']}; {len(data['ambiguities'])} ambiguities ({len(blocking)} blocking)", data)
