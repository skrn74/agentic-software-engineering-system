"""Workflow orchestrator.

What makes this more than a linear pipeline:
  * Dynamic task graph    - an agent (the planner) can spawn new tasks at run time.
  * Dependency scheduling - every task whose dependencies are DONE runs, in parallel where possible.
  * Retry with backoff    - TransientError is retried; other errors fail the task.
  * Recovery loop         - a failed `validate` spawns `repair_N` + `validate_N+1` and REWIRES every
                            downstream task to wait for the new validation (cross-step coordination).
  * Human gates           - tasks of agent "gate" pause for approval; rejection halts all dependants.
  * Checkpoint / resume   - state.json is written after every task; --resume continues the run.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from .guardrails import safe_join
from .models import Outcome, Rejected, Status, Task, TransientError, ValidationFailed


class Context:
    """Shared run state (the blackboard), artifact writer and event log."""

    def __init__(self, run_dir, options: dict, reasoner, quiet: bool = False):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.options = options
        self.reasoner = reasoner
        self.quiet = quiet
        self.bb: dict = {}
        self.artifacts: dict[str, int] = {}
        self.events: list[dict] = []
        self.t0 = time.time()
        self._lock = threading.RLock()
        self._events_path = self.run_dir / "events.jsonl"

    # blackboard ---------------------------------------------------------
    def put(self, key: str, value) -> None:
        with self._lock:
            self.bb[key] = value

    def get(self, key: str, default=None):
        with self._lock:
            return self.bb.get(key, default)

    # artifacts ----------------------------------------------------------
    def write(self, rel: str, text: str) -> Path:
        path = safe_join(self.run_dir, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        with self._lock:
            self.artifacts[rel.replace("\\", "/")] = len(text.encode("utf-8"))
        return path

    # events -------------------------------------------------------------
    def log(self, task: str, event: str, detail: str = "") -> None:
        rec = {"t": round(time.time() - self.t0, 2), "task": task, "event": event, "detail": detail}
        with self._lock:
            self.events.append(rec)
            with self._events_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
            if not self.quiet:
                line = f"[{rec['t']:6.1f}s] {task:<16} {event:<9} {detail}"
                print(line.encode("ascii", "replace").decode(), flush=True)


class Orchestrator:
    def __init__(self, ctx: Context, agents: dict, approver, max_workers: int = 4,
                 backoff: float = 0.3, max_repairs: int = 2):
        self.ctx = ctx
        self.agents = agents
        self.approver = approver
        self.max_workers = max_workers
        self.backoff = backoff
        self.max_repairs = max_repairs
        self.tasks: dict[str, Task] = {}
        self.repairs = 0
        self._gate_lock = threading.Lock()
        ctx.tasks = self.tasks

    # graph --------------------------------------------------------------
    def add(self, task: Task) -> None:
        if task.id in self.tasks:
            raise ValueError(f"duplicate task id: {task.id}")
        self.tasks[task.id] = task

    def _ready(self) -> list[Task]:
        return [t for t in self.tasks.values()
                if t.status == Status.PENDING and all(self.tasks[d].status == Status.DONE for d in t.deps)]

    def _propagate_blocked(self) -> None:
        changed = True
        while changed:
            changed = False
            for t in self.tasks.values():
                if t.status != Status.PENDING:
                    continue
                bad = [d for d in t.deps if self.tasks[d].status in (Status.FAILED, Status.REJECTED, Status.SKIPPED)]
                if bad:
                    t.status = Status.SKIPPED
                    t.error = f"blocked by {', '.join(bad)}"
                    self.ctx.log(t.id, "skipped", t.error)
                    changed = True

    # execution ----------------------------------------------------------
    def run(self) -> str:
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            running: dict = {}
            while True:
                self._propagate_blocked()
                for t in self._ready():
                    t.status = Status.RUNNING
                    running[pool.submit(self._execute, t)] = t
                if not running:
                    break
                done, _ = wait(list(running), return_when=FIRST_COMPLETED)
                for fut in done:
                    task = running.pop(fut)
                    kind, payload = fut.result()
                    self._finish(task, kind, payload)
                self._checkpoint()
        self._checkpoint()
        return self.final_status()

    def _execute(self, t: Task):
        t.started = time.time()
        for attempt in range(1, t.max_attempts + 1):
            t.attempts = attempt
            self.ctx.log(t.id, "start", t.title or t.agent + (f" (attempt {attempt})" if attempt > 1 else ""))
            try:
                outcome = self._gate(t) if t.agent == "gate" else self.agents[t.agent](t, self.ctx)
                return "ok", outcome
            except TransientError as exc:
                self.ctx.log(t.id, "retry", f"{exc} (attempt {attempt}/{t.max_attempts})")
                if attempt == t.max_attempts:
                    return "error", exc
                time.sleep(self.backoff * attempt)
            except Exception as exc:  # noqa: BLE001
                return "error", exc
        return "error", RuntimeError("no attempts executed")

    def _gate(self, t: Task) -> Outcome:
        review = self.ctx.get(t.params.get("review", ""), {}) or {}
        lines = review.get("gate_lines", [])
        with self._gate_lock:
            approved, comment = self.approver(t, t.params.get("gate_title", t.title), lines)
        self.ctx.log(t.id, "gate", f"{'APPROVED' if approved else 'REJECTED'}: {comment}")
        if not approved:
            raise Rejected(comment)
        return Outcome(summary=f"approved: {comment}", data={"approved": True, "comment": comment})

    def _finish(self, t: Task, kind: str, payload) -> None:
        t.ended = time.time()
        if kind == "ok":
            out: Outcome = payload
            t.status = Status.DONE
            t.summary = out.summary
            self.ctx.put(t.id, out.data)
            self.ctx.log(t.id, "done", out.summary)
            for new in out.spawn:
                self.add(new)
            if out.spawn:
                self.ctx.log(t.id, "spawn", ", ".join(n.id for n in out.spawn))
            return
        exc = payload
        if isinstance(exc, Rejected):
            t.status = Status.REJECTED
            t.error = str(exc)
            self.ctx.log(t.id, "rejected", t.error)
        elif isinstance(exc, ValidationFailed) and t.agent == "validate" and self.repairs < self.max_repairs:
            self._recover_validation(t, exc)
        else:
            t.status = Status.FAILED
            t.error = f"{type(exc).__name__}: {exc}"
            self.ctx.log(t.id, "FAILED", t.error)

    def _recover_validation(self, t: Task, exc: ValidationFailed) -> None:
        """Validation failed: spawn repair -> re-validate and rewire everything that waited on `t`."""
        self.repairs += 1
        rid, vid = f"repair_{self.repairs}", f"validate_{self.repairs + 1}"
        self.ctx.put("validation_failure", exc.details)
        self.ctx.log(t.id, "failed", f"{exc} -> spawning {rid} and {vid}")
        self.add(Task(rid, "repair", deps=[], title="Repair from failing tests", max_attempts=1,
                      rationale="Map failing tests to the module that caused them and regenerate it."))
        self.add(Task(vid, "validate", deps=[rid], params=dict(t.params),
                      title=f"Re-validate (cycle {self.repairs + 1})", rationale=t.rationale))
        for other in self.tasks.values():
            if other.id not in (rid, vid) and t.id in other.deps:
                other.deps = [vid if d == t.id else d for d in other.deps]
        t.status = Status.RECOVERED
        t.error = str(exc)
        self.ctx.log(t.id, "rewire", f"downstream tasks now wait for {vid}")

    def final_status(self) -> str:
        statuses = {t.status for t in self.tasks.values()}
        if Status.REJECTED in statuses:
            return "halted_by_human"
        if Status.FAILED in statuses:
            return "failed"
        return "completed"

    # checkpoint / resume -------------------------------------------------
    def _checkpoint(self) -> None:
        state = {"options": self.ctx.options, "bb": self.ctx.bb, "repairs": self.repairs,
                 "artifacts": self.ctx.artifacts, "tasks": [t.to_dict() for t in self.tasks.values()]}
        (self.ctx.run_dir / "state.json").write_text(json.dumps(state, indent=1, default=str), encoding="utf-8")

    def load_state(self) -> None:
        state = json.loads((self.ctx.run_dir / "state.json").read_text(encoding="utf-8"))
        self.ctx.bb.update(state["bb"])
        self.ctx.artifacts.update(state.get("artifacts", {}))
        self.repairs = state.get("repairs", 0)
        for d in state["tasks"]:
            t = Task.from_dict(d)
            if t.status in (Status.RUNNING, Status.FAILED, Status.REJECTED, Status.SKIPPED):
                t.status, t.attempts, t.error = Status.PENDING, 0, ""
            self.tasks[t.id] = t
        self.ctx.log("orchestrator", "resume", f"{sum(t.status == Status.DONE for t in self.tasks.values())} tasks already done")


# approvers ------------------------------------------------------------
def auto_approver(task, title, lines):
    if any("[BLOCKING]" in line for line in lines):
        return True, "auto-approved (demo mode): BLOCKING ambiguities were assumed, not answered"
    return True, "auto-approved (demo mode)"


def interactive_approver(task, title, lines):
    print("\n" + "=" * 70)
    print(f"HUMAN APPROVAL GATE: {title}")
    print("=" * 70)
    for line in lines:
        print("  " + line.encode("ascii", "replace").decode())
    while True:
        ans = input("\n[a]pprove / [r]eject > ").strip().lower()
        if ans in ("a", "approve", "y", "yes"):
            return True, "approved by human"
        if ans in ("r", "reject", "n", "no"):
            reason = input("reason (optional) > ").strip()
            return False, reason or "rejected by human"


class ScriptedApprover:
    """Deterministic approver for tests: reject the listed gate ids, approve the rest."""

    def __init__(self, reject=()):
        self.reject = set(reject)
        self.seen: list[str] = []

    def __call__(self, task, title, lines):
        self.seen.append(task.id)
        if task.id in self.reject:
            return False, "rejected by test script"
        return True, "approved by test script"
