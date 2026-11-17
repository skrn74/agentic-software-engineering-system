# Agentic Software Engineering System

Turns a software requirement into a reviewable engineering outcome: requirement analysis, task graph, design, code, API contract, tests, validation, risks and a final summary. Agents execute across multiple steps; humans approve at gates. See `docs/ARCHITECTURE.md` for the architecture and `examples/` for real outputs.

**Requirements:** Python 3.10 or newer (tested on 3.10 and 3.12). **No third-party packages, no model, no network.**

## Quick start

```
python run.py --scenario greenfield --auto-approve
```

Open `runs/greenfield/ENGINEERING_SUMMARY.md`, then run the generated project:

```
cd runs/greenfield/project
python -m unittest discover -s tests -t . -v
python -m shortener.app            # http://localhost:8080
```

## The three required scenarios

| Scenario | Command | Input |
|---|---|---|
| Greenfield (mandatory use case) | `python run.py --scenario greenfield --auto-approve` | "Build a scalable URL shortener service with APIs, persistence, and analytics." |
| Brownfield | `python run.py --scenario brownfield --auto-approve` | "Fix the short-code collision bug in the existing URL shortener ... and add click analytics." on `samples/legacy_shortener` |
| Ambiguous | `python run.py --scenario ambiguous --auto-approve` | "Make the URL shortener faster and better for our users." on `samples/legacy_shortener` |

Any requirement: `python run.py --requirement "..." [--repo path] [--auto-approve]`.

### What each demonstrates

| | Task decomposition | Multi-step orchestration | Output validation |
|---|---|---|---|
| **Greenfield** | 10 tasks planned dynamically from the requirement | `contract` and `code` run in parallel, then `tests` and `docs` in parallel; `risk` runs beside the design approval | 24 tests (unit, integration, contract), static safety scan, OpenAPI check |
| **Brownfield** | 12 tasks: scan, impact, baseline, design, tests, red check, patch, validate | Tests are written first and must **fail** on the unpatched repo (3 of 8), then **pass** on the patched copy | Scope guard (only `codegen`, `store`, `app` may change), full suite, reviewable `changes.patch` |
| **Ambiguous** | Interprets "faster" as redirect-lookup latency and "better" as out of scope, and asks for confirmation (2 blocking questions) | The run pauses at the clarification gate; rejection stops before planning | Cache is proven by a DB-read counter; stale-cache and bounded-memory tests; only `store.py` changes |

## Human control

Without `--auto-approve` the system stops at each gate and asks `[a]pprove / [r]eject`:

1. **Interpretation and assumptions** (clarification gate)
2. **Design** (no code is generated before this)
3. **Final outcome**

`--auto-approve` is for demos only; blocking ambiguities are then recorded as "assumed, not answered".

## Error handling and recovery demo

```
python run.py --scenario greenfield --auto-approve --inject-fault
python run.py --scenario brownfield --auto-approve --inject-fault
```

`--inject-fault` causes (1) a transient error in the design agent, which is **retried with backoff**, and (2) a code defect in the generated output. Validation fails, the orchestrator spawns `repair_1` and `validate_2`, **rewires** the downstream tasks, and the run completes. The trace is in section 8 of `ENGINEERING_SUMMARY.md` and in `events.jsonl`.

Resume a halted run: `python run.py --resume runs/greenfield`.

## Optional: use a hosted LLM

Offline mode needs nothing. If your organisation allows a hosted model:

```
set LLM_API_KEY=...            (PowerShell: $env:LLM_API_KEY="...")
set LLM_BASE_URL=https://api.openai.com/v1
set LLM_MODEL=gpt-4o-mini
```

The LLM then adds extra ambiguities and risks, marked `source=llm`. It is advisory only: output is schema-validated, an LLM can never create a blocking ambiguity, and it cannot override validation or gates. If the call fails, the run continues offline.

## Run output layout

```
runs/<name>/
  ENGINEERING_SUMMARY.md      final summary with plan, artifacts, validation, risks, limits, execution trace
  docs/                       requirements, plan, design, risks and validation (and repo scan / impact for brownfield)
  project/                    generated project (greenfield) or patched copy of the repo (brownfield)
  changes.patch               reviewable diff (brownfield)
  events.jsonl, state.json    event log and checkpoint
```

## Testing approach

Run the system's own tests (about a minute, because they execute all scenarios):

```
python -m unittest discover -s tests -t . -v
```

| Layer | What is verified |
|---|---|
| Orchestrator (`test_orchestrator.py`) | Dependency order, real parallelism, spawn at run time, retry with backoff, failure propagation, repair and **rewiring**, bounded repair, rejected gates, resume without re-running finished work |
| Requirement and planner (`test_requirement.py`) | Ambiguity detection (assumable and blocking), numbers remove ambiguities, unsupported domains stop cleanly, planner graph has no dangling dependencies |
| Guardrails (`test_guardrails.py`) | Path escape blocked, banned calls, string-built SQL, secrets, syntax errors |
| End to end (`test_e2e.py`) | All three scenarios; fault detection, repair and re-validation; **nothing is generated before design approval**; the original repo is never modified; red-then-green regression; unsupported requirement fails cleanly |
| LLM adapter (`test_llm.py`) | Valid suggestions are tagged and malformed ones dropped; a failing endpoint degrades to offline rules (tested against a local mock server) |

How output quality is validated: generated code is scanned, then its own tests (unit, integration, contract) must pass; for brownfield, the new tests must fail before and pass after the change, and the existing suite must stay green.

## Known limitations and trade-offs

- **Generation is template-driven in offline mode.** Analysis, planning, impact analysis, orchestration, validation, repair and guardrails are real logic; open-ended code generation needs a hosted LLM behind the same interface.
- **Repair is rule-based.** It fixes failures that map to a known module and escalates everything else.
- **Scope of offline mode:** URL shortener (greenfield) and two change types on the sample repo. Other requirements stop with a clear message (tested).
- **Impact analysis is static and name-based** (AST, best-effort call resolution); it does not follow dynamic dispatch or reflection.
- **Capacity numbers are from stated assumptions**, not measurements. Load, soak, chaos and penetration tests are not included.
- **The LLM adapter** is tested only against a local mock, not a production provider.
- The generated shortener uses SQLite and synchronous analytics; the design document describes the production path (cache, PostgreSQL, asynchronous analytics, rate limiting).
