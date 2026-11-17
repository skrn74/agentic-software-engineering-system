"""Planner agent: turn the approved requirement into a dependency graph and spawn it into the orchestrator."""
from __future__ import annotations

from ..models import Outcome, Task, UnsupportedRequirement


def _t(tid, agent, deps, title, why, **params):
    return Task(tid, agent, deps=list(deps), params=params, title=title, rationale=why)


def build_tasks(req: dict) -> list[Task]:
    if req["type"] == "greenfield":
        if req["domain"] != "url_shortener":
            raise UnsupportedRequirement(
                "Offline mode has code templates only for the URL shortener domain. "
                "Set LLM_API_KEY to enable a hosted model, or extend agentic/templates.")
        return [
            _t("design", "design", ["plan"], "Design architecture, data model, API and capacity",
               "Design first: every later artifact derives from it.", mode="greenfield"),
            _t("approve_design", "gate", ["design"], "Human approval of the design",
               "Controlled autonomy: a human signs off before any code is generated.", gate_title="Approve architecture and design", review="design"),
            _t("contract", "contract", ["approve_design"], "Generate OpenAPI contract from the design",
               "Contract-first: tests will later verify the code against this file."),
            _t("code", "code", ["approve_design"], "Generate service code (domain, repository, service, HTTP)",
               "Independent of the contract, so it runs in parallel with it."),
            _t("tests", "tests", ["contract", "code"], "Generate unit, integration and contract tests",
               "Needs the contract (what to verify) and the code (what to import)."),
            _t("docs", "docs", ["contract", "code"], "Generate README and runbook",
               "Documentation must reflect the final contract and code."),
            _t("risk", "risk", ["design"], "Risk register, failure scenarios and test strategy",
               "Pure analysis of the design, so it runs in parallel with code generation."),
            _t("validate", "validate", ["code", "tests", "contract", "docs"], "Validate: static checks, tests, contract",
               "Quality gate. On failure the orchestrator spawns repair and re-validation."),
            _t("summary", "summary", ["validate", "risk", "approve_design"], "Write the engineering summary",
               "Assemble plan, artifacts, risks, trade-offs and limitations."),
            _t("approve_final", "gate", ["summary"], "Human approval of the final outcome",
               "A human reviews the evidence before the outcome is accepted.", gate_title="Approve final engineering outcome", review="summary"),
        ]

    # brownfield
    tasks = [
        _t("scan", "scan_repo", ["plan"], "Scan the existing repository (modules, imports, routes, tables)",
           "Build a system-level model of the code before touching it."),
        _t("impact", "impact", ["scan"], "Impact analysis (root cause, impacted modules, APIs, data flows)",
           "Decide what must change and what is only affected."),
        _t("baseline", "baseline", ["scan"], "Run the existing test suite on the untouched repo",
           "Know the starting health so regressions are attributable."),
        _t("design_change", "design", ["impact"], "Design the change, compatibility and rollback",
           "Change proposal grounded in the impact analysis.", mode="brownfield"),
        _t("approve_design", "gate", ["design_change"], "Human approval of the change design",
           "A human approves the scope before any code changes.", gate_title="Approve change design", review="design_change"),
        _t("risk", "risk", ["impact"], "Risk register, failure scenarios and test strategy",
           "Runs in parallel with design and approval."),
    ]
    if req["patch_id"]:
        tasks += [
            _t("tests", "bf_tests", ["approve_design"], "Write regression tests for the intended behaviour",
               "Tests are written before the fix (test-first)."),
            _t("red", "red_check", ["tests", "baseline"], "Run new tests on the UNPATCHED repo (expect failures)",
               "Proves the tests actually reproduce the problem."),
            _t("patch", "patch", ["approve_design", "tests"], "Apply the change to a copy and produce a reviewable diff",
               "Original repo is never modified; output is a patch."),
            _t("validate", "validate", ["patch", "tests", "red"], "Validate: scope guard, static checks, full test suite",
               "Quality gate. On failure the orchestrator spawns repair and re-validation."),
            _t("summary", "summary", ["validate", "risk", "approve_design"], "Write the engineering summary",
               "Assemble plan, artifacts, risks, trade-offs and limitations."),
        ]
    else:
        tasks += [_t("summary", "summary", ["risk", "approve_design"], "Write the engineering summary (analysis only)",
                     "No change template matches in offline mode, so the outcome is analysis and design.")]
    tasks.append(_t("approve_final", "gate", ["summary"], "Human approval of the final outcome",
                    "A human reviews the evidence before the outcome is accepted.", gate_title="Approve final engineering outcome", review="summary"))
    return tasks


def run(task, ctx) -> Outcome:
    req = ctx.get("analyze")
    spawned = build_tasks(req)
    plan = [{"id": t.id, "agent": t.agent, "deps": t.deps, "title": t.title, "rationale": t.rationale} for t in spawned]
    lines = ["# 02 Plan", "", f"Execution plan for a {req['type']} requirement. Tasks run as soon as their dependencies are done; "
             "independent tasks run in parallel.", "", "| Task | Agent | Depends on | Purpose | Why |", "|---|---|---|---|---|"]
    lines += [f"| {p['id']} | {p['agent']} | {', '.join(p['deps']) or '-'} | {p['title']} | {p['rationale']} |" for p in plan]
    ctx.write("docs/02_plan.md", "\n".join(lines) + "\n")
    return Outcome(f"{len(spawned)} tasks planned", {"plan": plan, "mode": req["type"]}, spawn=spawned)
