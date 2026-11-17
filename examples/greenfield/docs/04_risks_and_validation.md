# 04 Risks, trade-offs and validation

## Risk register

| ID | Risk | Likelihood | Impact | Mitigation | Status |
|---|---|---|---|---|---|
| R1 | Abuse: shortener used to hide phishing or malware destinations | High | High | Scheme allow-list (done). Reputation checks, takedown workflow and per-client rate limits. | Partly mitigated |
| R2 | Dangerous URI schemes (javascript:, data:) used as redirect targets | Medium | High | Only absolute http/https URLs with a host are accepted; covered by a unit test. | Mitigated, tested |
| R3 | Short-code guessing or enumeration | Medium | Medium | Random 7-char base62 from a secure source (3.5T keyspace). Add rate limiting at the edge. | Mitigated |
| R4 | Code collision on creation | Low | Medium | Unique constraint plus bounded retry; covered by a unit test with a forced collision. | Mitigated, tested |
| R5 | Hot links overload the datastore (100:1 read-heavy) | High | Medium | Cache in front of the datastore; CDN for the most popular links. | Design only |
| R6 | SQLite single writer and synchronous click insert cap throughput | High | Medium | Repository interface allows PostgreSQL; make analytics asynchronous via a queue. | Design only |
| R7 | Raw click data grows to terabytes per year | High | Medium | Aggregate into daily counters and expire raw events. | Design only |
| R8 | PII leaks through referrers or user agents | Medium | Medium | Only the referrer host is stored; no IP or user agent. | Mitigated |
| R9 | API contract drifts from the implementation | Medium | Medium | Contract test compares routes, status codes and required fields to openapi.json. | Mitigated, tested |
| R10 | Data loss | Low | High | Backups and replication in production; not in the prototype. | Design only |

## Failure scenarios

| Scenario | Expected behaviour |
|---|---|
| Datastore unavailable | Create and redirect return 500 with a generic JSON error; no data is corrupted. Retry is safe. |
| Duplicate alias requested concurrently | The unique constraint decides; the loser gets 409. |
| Malformed or oversized request | 400 with a JSON error; body size is capped at 64 KB. |
| Unknown short code | 404 JSON error; no click is recorded. |
| Click insert fails | In the prototype the redirect fails with 500 (analytics is on the request path); production moves it off the path. |

## Validation strategy

| Layer | What it verifies |
|---|---|
| Unit tests | Domain rules and service behaviour with an in-memory repository and a fake clock. |
| Integration tests | Full HTTP flow through the WSGI app with a real SQLite file, including restart persistence. |
| Contract tests | Routes, status codes and required response fields are checked against openapi.json. |
| Static checks | Syntax, banned calls, string-built SQL and hard-coded secrets are scanned in generated code. |
| Repair loop | On failure, failing tests are mapped to the faulty module, which is regenerated and re-validated (bounded). |
| Not covered | Load, soak, chaos and multi-node behaviour; real payment-scale data; penetration testing. |

## Guardrails

- Writes are confined to the run workspace (path-escape check).
- Generated code is scanned for banned calls, string-built SQL and secrets.
- Tests run in a subprocess with a hard timeout.
- Repair is bounded (max 2 cycles); unknown failures escalate to a human.
- Humans approve the design and the final outcome.
