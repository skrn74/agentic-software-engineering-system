"""Validator: the quality gate. Deterministic code, no LLM, so its verdict is reproducible."""
from __future__ import annotations

import json

from ..guardrails import run_unittests, scan_python, scan_secrets
from ..models import Outcome, ValidationFailed
from . import brownfield


def run(task, ctx) -> Outcome:
    mode = ctx.get("analyze")["type"]
    root = ctx.run_dir / "project"
    checks, problems = [], []

    def check(name, ok, detail=""):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})
        if not ok:
            problems.append(f"{name}: {detail}")

    static = []
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel, text = p.relative_to(root).as_posix(), p.read_text(encoding="utf-8")
        static += scan_python(rel, text) + scan_secrets(rel, text)
    check("static analysis: syntax, banned calls, SQL parameterisation, secrets", not static, "; ".join(static[:5]) or "clean")

    if mode == "greenfield":
        try:
            spec = json.loads((root / "openapi.json").read_text(encoding="utf-8"))
            check("OpenAPI contract is valid JSON with paths", spec.get("openapi", "").startswith("3.") and bool(spec.get("paths")),
                  f"{len(spec.get('paths', {}))} paths")
        except Exception as exc:  # noqa: BLE001
            check("OpenAPI contract is valid JSON with paths", False, str(exc))
        check("README present", (root / "README.md").exists())
    else:
        diff = brownfield.make_diff(ctx)
        allowed = {f"{m}.py" for m in ctx.get("impact")["modify"]}
        out_of_scope = [c for c in diff["changed"] if not c.startswith("tests/") and c not in allowed]
        check("scope guard: only files named by the impact analysis were modified", not out_of_scope,
              f"changed {', '.join(c for c in diff['changed'] if not c.startswith('tests/'))}" + (f"; OUT OF SCOPE: {out_of_scope}" if out_of_scope else ""))

    tests = run_unittests(root)
    check("test suite (unit, integration, contract / regression)", tests["ok"],
          f"{tests['ran']} tests in {tests['seconds']}s" + (f"; failing: {', '.join(tests['failures'])}" if tests["failures"] else ""))
    ctx.put("last_validation", {"checks": checks, "tests_run": tests["ran"], "seconds": tests["seconds"]})

    if problems:
        raise ValidationFailed("; ".join(problems)[:300],
                               {"failures": tests["failures"], "static": static, "output_tail": tests["output_tail"]})
    return Outcome(f"all {len(checks)} checks passed, {tests['ran']} tests pass", {"checks": checks, "tests_run": tests["ran"]})
