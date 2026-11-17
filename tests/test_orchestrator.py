import tempfile
import threading
import time
import unittest

from agentic.models import Outcome, Status, Task, TransientError, ValidationFailed
from agentic.orchestrator import Context, Orchestrator, ScriptedApprover, auto_approver
from agentic.reasoner import Reasoner


def make(agents, approver=auto_approver, **kw):
    tmp = tempfile.TemporaryDirectory()
    ctx = Context(tmp.name, {}, Reasoner(), quiet=True)
    return tmp, ctx, Orchestrator(ctx, agents, approver, backoff=0.01, **kw)


def ok(summary="ok", **data):
    return lambda task, ctx: Outcome(summary, data)


class TestScheduling(unittest.TestCase):
    def test_dependencies_are_respected_and_independent_tasks_run_in_parallel(self):
        live, peak, lock, order = 0, 0, threading.Lock(), []

        def work(task, ctx):
            nonlocal live, peak
            with lock:
                live += 1
                peak = max(peak, live)
                order.append(task.id)
            time.sleep(0.3)
            with lock:
                live -= 1
            return Outcome("done")

        tmp, ctx, orch = make({"w": work})
        for t in [Task("a", "w"), Task("b", "w", ["a"]), Task("c", "w", ["a"]), Task("d", "w", ["b", "c"])]:
            orch.add(t)
        t0 = time.time()
        self.assertEqual(orch.run(), "completed")
        self.assertEqual(order[0], "a")
        self.assertEqual(order[-1], "d")
        self.assertEqual(peak, 2)                       # b and c overlapped
        self.assertLess(time.time() - t0, 1.15)         # sequential would be >= 1.2 s
        tmp.cleanup()

    def test_agent_can_spawn_new_tasks_at_run_time(self):
        def planner(task, ctx):
            return Outcome("planned", spawn=[Task("x", "w", ["p"]), Task("y", "w", ["x"])])

        tmp, ctx, orch = make({"p": planner, "w": ok()})
        orch.add(Task("p", "p"))
        self.assertEqual(orch.run(), "completed")
        self.assertEqual({t.id: t.status for t in orch.tasks.values()}, {"p": Status.DONE, "x": Status.DONE, "y": Status.DONE})
        tmp.cleanup()

    def test_transient_error_is_retried_with_backoff(self):
        calls = []

        def flaky(task, ctx):
            calls.append(task.attempts)
            if len(calls) < 3:
                raise TransientError("timeout")
            return Outcome("recovered")

        tmp, ctx, orch = make({"f": flaky})
        orch.add(Task("t", "f", max_attempts=3))
        self.assertEqual(orch.run(), "completed")
        self.assertEqual(orch.tasks["t"].attempts, 3)
        tmp.cleanup()

    def test_permanent_failure_blocks_dependants(self):
        def boom(task, ctx):
            raise RuntimeError("bad")

        tmp, ctx, orch = make({"boom": boom, "w": ok()})
        for t in [Task("a", "w"), Task("b", "boom", ["a"]), Task("c", "w", ["b"]), Task("d", "w", ["a"])]:
            orch.add(t)
        self.assertEqual(orch.run(), "failed")
        st = {t.id: t.status for t in orch.tasks.values()}
        self.assertEqual((st["b"], st["c"], st["d"]), (Status.FAILED, Status.SKIPPED, Status.DONE))
        tmp.cleanup()


class TestRecovery(unittest.TestCase):
    def test_failed_validation_spawns_repair_and_rewires_downstream_tasks(self):
        state = {"fixed": False, "summary_ran_after_fix": None}

        def validate(task, ctx):
            if not state["fixed"]:
                raise ValidationFailed("tests failed", {"failures": ["test_x"]})
            return Outcome("green")

        def repair(task, ctx):
            state["fixed"] = True
            self.assertEqual(ctx.get("validation_failure")["failures"], ["test_x"])
            return Outcome("fixed")

        def summary(task, ctx):
            state["summary_ran_after_fix"] = state["fixed"]
            return Outcome("summary")

        tmp, ctx, orch = make({"validate": validate, "repair": repair, "summary": summary, "w": ok()})
        for t in [Task("code", "w"), Task("validate", "validate", ["code"]), Task("summary", "summary", ["validate"])]:
            orch.add(t)
        self.assertEqual(orch.run(), "completed")
        self.assertEqual(orch.tasks["validate"].status, Status.RECOVERED)
        self.assertEqual(orch.tasks["validate_2"].status, Status.DONE)
        self.assertEqual(orch.tasks["summary"].deps, ["validate_2"])
        self.assertTrue(state["summary_ran_after_fix"])
        tmp.cleanup()

    def test_repair_is_bounded(self):
        def validate(task, ctx):
            raise ValidationFailed("still failing", {"failures": ["t"]})

        tmp, ctx, orch = make({"validate": validate, "repair": ok(), "w": ok()}, max_repairs=2)
        orch.add(Task("code", "w"))
        orch.add(Task("validate", "validate", ["code"]))
        orch.add(Task("summary", "w", ["validate"]))
        self.assertEqual(orch.run(), "failed")
        self.assertEqual(orch.repairs, 2)
        self.assertEqual(orch.tasks["summary"].status, Status.SKIPPED)
        tmp.cleanup()


class TestHumanControl(unittest.TestCase):
    def test_rejected_gate_halts_everything_downstream(self):
        ran = []
        tmp, ctx, orch = make({"w": lambda t, c: (ran.append(t.id), Outcome("ok"))[1]}, approver=ScriptedApprover(reject={"approve"}))
        for t in [Task("design", "w"), Task("approve", "gate", ["design"]), Task("code", "w", ["approve"])]:
            orch.add(t)
        self.assertEqual(orch.run(), "halted_by_human")
        self.assertNotIn("code", ran)
        self.assertEqual(orch.tasks["code"].status, Status.SKIPPED)
        tmp.cleanup()

    def test_resume_continues_without_rerunning_finished_work(self):
        calls = {"design": 0, "code": 0}

        def agent(task, ctx):
            calls[task.id] += 1
            return Outcome("ok", {"gate_lines": ["x"]})

        tmp = tempfile.TemporaryDirectory()
        ctx = Context(tmp.name, {}, Reasoner(), quiet=True)
        orch = Orchestrator(ctx, {"w": agent}, ScriptedApprover(reject={"approve"}), backoff=0.01)
        for t in [Task("design", "w"), Task("approve", "gate", ["design"], params={"review": "design"}), Task("code", "w", ["approve"])]:
            orch.add(t)
        self.assertEqual(orch.run(), "halted_by_human")

        ctx2 = Context(tmp.name, {}, Reasoner(), quiet=True)
        orch2 = Orchestrator(ctx2, {"w": agent}, auto_approver, backoff=0.01)
        orch2.load_state()
        self.assertEqual(orch2.run(), "completed")
        self.assertEqual(calls, {"design": 1, "code": 1})          # design was NOT re-run
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
