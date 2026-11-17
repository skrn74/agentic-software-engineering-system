# 02 Plan

Execution plan for a greenfield requirement. Tasks run as soon as their dependencies are done; independent tasks run in parallel.

| Task | Agent | Depends on | Purpose | Why |
|---|---|---|---|---|
| design | design | plan | Design architecture, data model, API and capacity | Design first: every later artifact derives from it. |
| approve_design | gate | design | Human approval of the design | Controlled autonomy: a human signs off before any code is generated. |
| contract | contract | approve_design | Generate OpenAPI contract from the design | Contract-first: tests will later verify the code against this file. |
| code | code | approve_design | Generate service code (domain, repository, service, HTTP) | Independent of the contract, so it runs in parallel with it. |
| tests | tests | contract, code | Generate unit, integration and contract tests | Needs the contract (what to verify) and the code (what to import). |
| docs | docs | contract, code | Generate README and runbook | Documentation must reflect the final contract and code. |
| risk | risk | design | Risk register, failure scenarios and test strategy | Pure analysis of the design, so it runs in parallel with code generation. |
| validate | validate | code, tests, contract, docs | Validate: static checks, tests, contract | Quality gate. On failure the orchestrator spawns repair and re-validation. |
| summary | summary | validate, risk, approve_design | Write the engineering summary | Assemble plan, artifacts, risks, trade-offs and limitations. |
| approve_final | gate | summary | Human approval of the final outcome | A human reviews the evidence before the outcome is accepted. |
