# 04 Risks, trade-offs and validation

## Risk register

| ID | Risk | Likelihood | Impact | Mitigation | Status |
|---|---|---|---|---|---|
| R1 | Stale cache serves an outdated URL | Medium | High | Entry invalidated on every save; covered by a test. | Mitigated, tested |
| R2 | Cache invalidation does not reach other processes | High | Medium | In-process cache only: use a TTL or shared cache before running multiple workers. | Known limitation |
| R3 | Unbounded memory growth | Low | Medium | Fixed-size LRU with eviction; covered by a test. | Mitigated, tested |
| R4 | Negative lookups hammer the database | Low | Low | Unknown codes are deliberately not cached; a negative cache could be added. | Accepted |

## Failure scenarios

| Scenario | Expected behaviour |
|---|---|
| Patch breaks existing behaviour | The full existing suite plus new tests must pass; otherwise the repair loop or a human intervenes. |
| Change touches unrelated files | Scope guard rejects any file not named by the impact analysis. |

## Validation strategy

| Layer | What it verifies |
|---|---|
| Baseline | Existing tests run on the untouched repo first, so regressions are attributable. |
| Test-first, red check | New tests are written before the fix and must FAIL on the unpatched repo (proves they reproduce the issue). |
| Green check | The full suite (existing plus new) must pass on the patched copy. |
| Scope guard | Only modules named by the impact analysis may change. |
| Reviewable diff | The change is delivered as changes.patch; the original repo is never modified. |
| Not covered | Production traffic, multi-process behaviour and performance under load. |

## Guardrails

- Writes are confined to the run workspace (path-escape check).
- Generated code is scanned for banned calls, string-built SQL and secrets.
- Tests run in a subprocess with a hard timeout.
- Repair is bounded (max 2 cycles); unknown failures escalate to a human.
- Humans approve the design and the final outcome.
