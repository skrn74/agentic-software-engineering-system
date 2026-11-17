import json
import tempfile
import unittest
from pathlib import Path

from agentic.engine import PRESETS, run_requirement
from agentic.models import Status
from agentic.orchestrator import ScriptedApprover

ROOT = Path(__file__).resolve().parent.parent


def run(scenario, approver=None, **kw):
    tmp = tempfile.TemporaryDirectory()
    p = PRESETS[scenario]
    kwargs = dict(repo=(ROOT / p["repo"]) if p["repo"] else None, quiet=True, name="r")
    if approver:
        kwargs["approver"] = approver
    kwargs.update(kw)
    res = run_requirement(p["requirement"], tmp.name, **kwargs)
    return tmp, res


class TestEndToEnd(unittest.TestCase):
    def test_greenfield_url_shortener_end_to_end(self):
        tmp, res = run("greenfield")
        self.assertEqual(res["status"], "completed")
        root = Path(res["run_dir"])
        for rel in ["project/shortener/app.py", "project/openapi.json", "project/tests/test_contract.py",
                    "docs/03_design.md", "docs/04_risks_and_validation.md", "ENGINEERING_SUMMARY.md"]:
            self.assertTrue((root / rel).exists(), rel)
        self.assertGreaterEqual(res["ctx"].get("validate")["tests_run"], 20)
        self.assertIn("Execution trace", (root / "ENGINEERING_SUMMARY.md").read_text(encoding="utf-8"))
        tmp.cleanup()

    def test_greenfield_fault_is_detected_repaired_and_revalidated(self):
        tmp, res = run("greenfield", inject_fault=True)
        t = res["tasks"]
        self.assertEqual(res["status"], "completed")
        self.assertEqual(t["validate"].status, Status.RECOVERED)
        self.assertEqual(t["repair_1"].status, Status.DONE)
        self.assertEqual(t["validate_2"].status, Status.DONE)
        self.assertEqual(t["design"].attempts, 2)                  # transient fault retried
        self.assertIn("validate_2", t["summary"].deps)
        tmp.cleanup()

    def test_nothing_is_generated_before_design_approval(self):
        tmp, res = run("greenfield", approver=ScriptedApprover(reject={"approve_design"}))
        self.assertEqual(res["status"], "halted_by_human")
        self.assertFalse((Path(res["run_dir"]) / "project").exists())
        tmp.cleanup()

    def test_rejected_assumptions_stop_the_run_before_planning(self):
        tmp, res = run("ambiguous", approver=ScriptedApprover(reject={"clarify"}))
        self.assertEqual(res["status"], "halted_by_human")
        self.assertNotIn("plan", [k for k, v in res["tasks"].items() if v.status == Status.DONE])
        tmp.cleanup()

    def test_brownfield_bug_is_reproduced_then_fixed_within_scope(self):
        tmp, res = run("brownfield")
        self.assertEqual(res["status"], "completed")
        self.assertGreaterEqual(len(res["ctx"].get("red")["failing_before_fix"]), 1)    # red before the fix
        self.assertTrue(res["ctx"].get("validate")["checks"][-1]["passed"])             # green after
        patch = (Path(res["run_dir"]) / "changes.patch").read_text(encoding="utf-8")
        self.assertIn("+++ b/codegen.py", patch)
        self.assertEqual(sorted(res["ctx"].get("impact")["modify"]), ["app", "codegen", "store"])
        tmp.cleanup()

    def test_original_repository_is_never_modified(self):
        before = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "samples/legacy_shortener").glob("*.py")}
        tmp, res = run("brownfield")
        after = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "samples/legacy_shortener").glob("*.py")}
        self.assertEqual(before, after)
        tmp.cleanup()

    def test_ambiguous_requirement_is_clarified_then_executed_with_recorded_assumptions(self):
        tmp, res = run("ambiguous")
        self.assertEqual(res["status"], "completed")
        self.assertIn("BLOCKING", res["tasks"]["clarify"].summary.upper())
        self.assertEqual(res["ctx"].get("impact")["modify"], ["store"])                # minimal blast radius
        self.assertIn("db_reads", (Path(res["run_dir"]) / "project/store.py").read_text(encoding="utf-8"))
        tmp.cleanup()

    def test_brownfield_fault_is_repaired(self):
        tmp, res = run("brownfield", inject_fault=True)
        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["tasks"]["validate"].status, Status.RECOVERED)
        tmp.cleanup()

    def test_unsupported_requirement_fails_cleanly(self):
        tmp = tempfile.TemporaryDirectory()
        res = run_requirement("Build a hotel booking system.", tmp.name, quiet=True, name="r")
        self.assertEqual(res["status"], "failed")
        self.assertIn("UnsupportedRequirement", res["tasks"]["plan"].error)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
