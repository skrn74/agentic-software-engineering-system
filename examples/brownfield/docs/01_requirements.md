# 01 Requirement analysis

**Input:** Fix the short-code collision bug in the existing URL shortener (different URLs sometimes redirect to the wrong place) and add click analytics.

**Type:** brownfield  |  **Domain:** url_shortener  |  **Ambiguity level:** low

## Normalised engineering problem

Fix the short-code collision bug in the existing URL shortener so that different URLs never overwrite each other, keep existing codes working, and add click analytics.

## Functional requirements

- FR1 Different URLs must never share a short code or overwrite one another
- FR2 Existing short codes must keep redirecting correctly
- FR3 Record clicks and expose per-link analytics

## Non-functional requirements

- NFR1 Backward compatible API and data
- NFR2 Additive, reversible schema change
- NFR3 Regression test proves the bug before the fix and its absence after

## Ambiguities and proposed assumptions

| ID | Topic | Question | Proposed assumption | Severity | Source |
|---|---|---|---|---|---|
| B1 | Existing codes | Must links created before the fix keep working, and may new codes use a different format? | Yes: existing codes stay valid; new codes use a longer base62 format. | assumable | rules |
| B2 | Analytics scope | Which analytics are needed and what may be stored? | Total clicks, clicks per day, top referrer hosts. No IP address or user agent. | assumable | rules |
