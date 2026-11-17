"""Reporter: the structured engineering summary, completed with the full execution trace at the end of the run."""
from __future__ import annotations

from pathlib import Path

from ..models import Outcome, Status

LIMITATIONS = [
    "Offline mode generates code from reviewed templates. Requirement analysis, planning, impact analysis, validation and repair are "
    "real logic, but open-ended code generation needs a hosted LLM behind the same agent interface.",
    "Repair is rule-based: it fixes failures that map to a known module and escalates everything else to a human.",
    "Offline mode covers the URL shortener domain (greenfield) and two change types on the sample repo (collision fix, LRU cache). "
    "Other requirements stop with a clear message.",
    "The optional LLM adapter is advisory only and has been exercised against a local mock endpoint, not a production provider.",
    "Validation runs the generated tests in a subprocess; it does not include load, soak, chaos or security penetration testing.",
    "Thresholds and capacity figures come from stated assumptions, not measurements.",
]


def _files(root: Path, sub: str) -> list[tuple[str, int]]:
    base = root / sub
    if not base.exists():
        return []
    return sorted((p.relative_to(root).as_posix(), p.stat().st_size) for p in base.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")


def run(task, ctx) -> Outcome:
    req = ctx.get("analyze")
    plan = ctx.get("plan")["plan"]
    risk = ctx.get("risk") or {}
    gates = [(t.id, t.summary) for t in getattr(ctx, "tasks", {}).values() if t.agent == "gate" and t.status == Status.DONE]
    lines = ["# Engineering summary", "",
             f"**Requirement:** {req['raw']}", f"**Interpreted as:** {req['type']} change ({req['domain']}); ambiguity level {req['ambiguity_level']}.", "",
             "## 1. What was built and why", "", req["normalized"], ""]
    design = ctx.get("design") or ctx.get("design_change") or {}
    if req["type"] == "greenfield" and design.get("capacity"):
        cap = design["capacity"]
        lines += ["Key design points:", "",
                  f"- API tier is stateless; capacity at the assumed scale is about {cap['writes_per_s']} writes/s and {cap['reads_per_s']:,} reads/s.",
                  "- Random base62 codes with a unique constraint; HTTP 302 so every click is observable; repository interface for the datastore.",
                  f"- Raw click events would reach about {cap['raw_click_storage_tb_per_year']} TB/year, so production must aggregate them.", ""]
    elif req["type"] == "brownfield":
        imp = ctx.get("impact") or {}
        lines += ["Impact analysis:", "", f"- Driver: {imp.get('root_cause', 'n/a')}",
                  f"- Modules modified: {', '.join(imp.get('modify', [])) or 'none'}; affected but unchanged: {', '.join(imp.get('affected', [])) or 'none'}",
                  f"- APIs impacted: {', '.join(imp.get('apis', [])) or 'none'}", ""]
    lines += ["## 2. Assumptions the human approved", ""]
    lines += [f"- {a}" for a in req["assumptions"]] or ["- none needed"]
    lines += ["", "Human approvals recorded: " + (", ".join(f"{g} ({s})" for g, s in gates) or "none") + "", "",
              "## 3. Implementation plan and rationale", "", "| Task | Agent | Depends on | Why |", "|---|---|---|---|"]
    lines += [f"| {p['id']} | {p['agent']} | {', '.join(p['deps']) or '-'} | {p['rationale']} |" for p in plan]
    lines += ["", "## 4. Generated artifacts", ""]
    for sub, label in (("project", "Project"), ("docs", "Documentation"), ("new_tests", "Regression tests (brownfield)")):
        files = _files(ctx.run_dir, sub)
        if files:
            lines += [f"**{label}**", ""] + [f"- `{n}` ({s:,} bytes)" for n, s in files] + [""]
    if (ctx.run_dir / "changes.patch").exists():
        lines += ["**Reviewable diff:** `changes.patch`", ""]
    lines += ["## 5. Validation results", ""]
    val = ctx.get("last_validation")
    if val:
        lines += [f"- [{'PASS' if c['passed'] else 'FAIL'}] {c['check']}: {c['detail']}" for c in val["checks"]]
    red = ctx.get("red")
    if red:
        lines += [f"- [PASS] red check: {len(red['failing_before_fix'])} of {red['ran']} new tests failed on the unpatched repo, "
                  "then passed after the change"]
    base = ctx.get("baseline")
    if base:
        lines += [f"- [PASS] baseline: the existing suite ({base['ran']} tests) passed before any change"]
    lines += ["", "## 6. Risks, trade-offs and validation approach", ""]
    lines += ["| ID | Risk | Mitigation | Status |", "|---|---|---|---|"]
    lines += [f"| {r[0]} | {r[1]} | {r[4]} | {r[5]} |" for r in risk.get("risks", [])]
    lines += ["", "Validation strategy:", ""] + [f"- **{a}:** {b}" for a, b in risk.get("strategy", [])]
    if design.get("decisions"):
        lines += ["", "Key trade-offs:", ""] + [f"- **{n}:** {c}. {w}" for n, c, w in design["decisions"]]
    lines += ["", "## 7. Assumptions and limitations", ""] + [f"- {x}" for x in LIMITATIONS]
    if ctx.options.get("inject_fault"):
        lines += ["- A fault was deliberately injected in this run to demonstrate detection and repair (see the execution trace)."]
    gate_lines = [f"Requirement: {req['raw']}", f"Validation: {val['tests_run']} tests pass, {len(val['checks'])} checks green." if val else "Analysis only: no code change generated.",
                  f"Artifacts: {len(_files(ctx.run_dir, 'project'))} project files, {len(_files(ctx.run_dir, 'docs'))} documents.",
                  "Full summary: ENGINEERING_SUMMARY.md"]
    ctx.write("ENGINEERING_SUMMARY.md", "\n".join(lines) + "\n")
    return Outcome("engineering summary written", {"gate_lines": gate_lines})


def finalize(ctx, orch, status: str) -> None:
    """Append the execution trace now that every task has finished."""
    path = ctx.run_dir / "ENGINEERING_SUMMARY.md"
    if not path.exists():
        return
    tasks = list(orch.tasks.values())
    t0 = min((t.started for t in tasks if t.started), default=0)
    lines = ["", "## 8. Execution trace", "", f"**Run status: {status}**", "",
             "| Task | Agent | Status | Attempts | Start (s) | Duration (s) | Result |", "|---|---|---|---|---|---|---|"]
    for t in tasks:
        start = f"{t.started - t0:.1f}" if t.started else "-"
        dur = f"{t.ended - t.started:.1f}" if t.ended and t.started else "-"
        lines.append(f"| {t.id} | {t.agent} | {t.status.value} | {t.attempts} | {start} | {dur} | {(t.summary or t.error)[:90]} |")
    spans = [(t.started, t.ended, t.id) for t in tasks if t.agent != "gate" and t.started and t.ended]
    best, who = 0, []
    for s, _, _ in spans:
        live = [i for a, b, i in spans if a <= s < b]
        if len(live) > best:
            best, who = len(live), live
    lines += ["", f"Maximum tasks running at the same time: {best} ({', '.join(who)})." if best else "", "",
              "Notable events (retries, faults, repairs, graph rewiring, gates):", ""]
    for e in ctx.events:
        if e["event"] in ("retry", "fault", "failed", "repaired", "rewire", "spawn", "gate", "rejected", "FAILED", "skipped", "resume"):
            lines.append(f"- {e['t']:>6.1f}s  `{e['task']}`  {e['event']}: {e['detail']}")
    colour = {"DONE": "#c8f0d8", "RECOVERED": "#ffe3a3", "FAILED": "#f9c0c0", "REJECTED": "#f9c0c0", "SKIPPED": "#e5e5e5"}
    lines += ["", "Task graph:", "", "```mermaid", "flowchart LR"]
    for t in tasks:
        lines.append(f'  {t.id}["{t.id}<br/>{t.status.value}"]')
    for t in tasks:
        for d in t.deps:
            lines.append(f"  {d} --> {t.id}")
    for t in tasks:
        if t.status.value in colour:
            lines.append(f"  style {t.id} fill:{colour[t.status.value]}")
    lines.append("```")
    path.write_text(path.read_text(encoding="utf-8") + "\n".join(lines) + "\n", encoding="utf-8")
