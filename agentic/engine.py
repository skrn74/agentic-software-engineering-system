"""Wires the bootstrap graph and runs a requirement end to end."""
from __future__ import annotations

import time
from pathlib import Path

from .agents import AGENTS, reporter
from .models import Task
from .orchestrator import Context, Orchestrator, auto_approver
from .reasoner import make_reasoner

PRESETS = {
    "greenfield": {
        "requirement": "Build a scalable URL shortener service with APIs, persistence, and analytics.",
        "repo": None,
    },
    "brownfield": {
        "requirement": "Fix the short-code collision bug in the existing URL shortener (different URLs sometimes redirect to the wrong place) and add click analytics.",
        "repo": "samples/legacy_shortener",
    },
    "ambiguous": {
        "requirement": "Make the URL shortener faster and better for our users.",
        "repo": "samples/legacy_shortener",
    },
}


def run_requirement(requirement: str, out_dir, repo=None, approver=auto_approver, inject_fault=False,
                    quiet=False, resume=False, reasoner=None, name=None) -> dict:
    out_dir = Path(out_dir)
    if not resume:
        out_dir = out_dir / (name or time.strftime("run_%Y%m%d_%H%M%S"))
    options = {"requirement": requirement, "repo": str(Path(repo).resolve()) if repo else None, "inject_fault": inject_fault}
    ctx = Context(out_dir, options, reasoner or make_reasoner(), quiet=quiet)
    orch = Orchestrator(ctx, AGENTS, approver)
    if resume:
        orch.load_state()
        ctx.options.update(options)
    else:
        orch.add(Task("analyze", "analyze", title="Understand the requirement and find ambiguities",
                      rationale="Everything downstream depends on a clear problem statement."))
        orch.add(Task("clarify", "gate", deps=["analyze"], title="Human confirms interpretation and assumptions",
                      rationale="Ambiguity is resolved by a human, not silently guessed.",
                      params={"gate_title": "Confirm interpretation and assumptions", "review": "analyze"}))
        orch.add(Task("plan", "plan", deps=["clarify"], title="Decompose into a task graph",
                      rationale="The plan spawns the rest of the workflow dynamically."))
    status = orch.run()
    reporter.finalize(ctx, orch, status)
    return {"status": status, "run_dir": str(ctx.run_dir), "tasks": orch.tasks, "ctx": ctx}
