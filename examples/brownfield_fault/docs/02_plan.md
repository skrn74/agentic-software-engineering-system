# 02 Plan

Execution plan for a brownfield requirement. Tasks run as soon as their dependencies are done; independent tasks run in parallel.

| Task | Agent | Depends on | Purpose | Why |
|---|---|---|---|---|
| scan | scan_repo | plan | Scan the existing repository (modules, imports, routes, tables) | Build a system-level model of the code before touching it. |
| impact | impact | scan | Impact analysis (root cause, impacted modules, APIs, data flows) | Decide what must change and what is only affected. |
| baseline | baseline | scan | Run the existing test suite on the untouched repo | Know the starting health so regressions are attributable. |
| design_change | design | impact | Design the change, compatibility and rollback | Change proposal grounded in the impact analysis. |
| approve_design | gate | design_change | Human approval of the change design | A human approves the scope before any code changes. |
| risk | risk | impact | Risk register, failure scenarios and test strategy | Runs in parallel with design and approval. |
| tests | bf_tests | approve_design | Write regression tests for the intended behaviour | Tests are written before the fix (test-first). |
| red | red_check | tests, baseline | Run new tests on the UNPATCHED repo (expect failures) | Proves the tests actually reproduce the problem. |
| patch | patch | approve_design, tests | Apply the change to a copy and produce a reviewable diff | Original repo is never modified; output is a patch. |
| validate | validate | patch, tests, red | Validate: scope guard, static checks, full test suite | Quality gate. On failure the orchestrator spawns repair and re-validation. |
| summary | summary | validate, risk, approve_design | Write the engineering summary | Assemble plan, artifacts, risks, trade-offs and limitations. |
| approve_final | gate | summary | Human approval of the final outcome | A human reviews the evidence before the outcome is accepted. |
