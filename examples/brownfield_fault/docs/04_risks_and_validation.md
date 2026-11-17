# 04 Risks, trade-offs and validation

## Risk register

| ID | Risk | Likelihood | Impact | Mitigation | Status |
|---|---|---|---|---|---|
| R1 | Existing short links break | Medium | High | Lookup path unchanged; legacy-code regression test. | Mitigated, tested |
| R2 | Schema change breaks rollback | Low | Medium | Additive CREATE TABLE IF NOT EXISTS only; old version ignores the new table. | Mitigated |
| R3 | Concurrent creation races on the same code | Medium | High | INSERT OR IGNORE is atomic; the caller verifies the stored URL and retries. | Mitigated |
| R4 | New code format surprises consumers | Low | Low | Documented; codes are opaque strings and lookup is by exact match. | Accepted |
| R5 | Analytics writes slow the redirect path | Medium | Medium | One small insert per click; make asynchronous at scale. | Design only |

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
