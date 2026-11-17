import unittest

from agentic.agents.planner import build_tasks
from agentic.agents.requirement import analyze
from agentic.models import UnsupportedRequirement


class TestRequirementAgent(unittest.TestCase):
    def test_mandatory_use_case_is_greenfield_with_assumable_ambiguities(self):
        r = analyze("Build a scalable URL shortener service with APIs, persistence, and analytics.")
        self.assertEqual((r["type"], r["domain"]), ("greenfield", "url_shortener"))
        self.assertGreaterEqual(len(r["ambiguities"]), 4)
        self.assertTrue(all(a["severity"] == "assumable" for a in r["ambiguities"]))
        self.assertEqual(r["parameters"]["read_write_ratio"], 100)
        self.assertTrue(any("analytics" in f.lower() for f in r["functional"]))

    def test_numbers_in_the_requirement_remove_the_scale_ambiguity(self):
        r = analyze("Build a scalable URL shortener handling 5,000 req/s with APIs and persistence in PostgreSQL.")
        topics = {a["topic"] for a in r["ambiguities"]}
        self.assertNotIn("Scale", topics)
        self.assertNotIn("Datastore", topics)

    def test_vague_request_is_flagged_blocking(self):
        r = analyze("Make the URL shortener faster and better for our users.", repo_given=True)
        self.assertEqual(r["type"], "brownfield")
        self.assertEqual(r["ambiguity_level"], "high")
        self.assertGreaterEqual(sum(a["severity"] == "blocking" for a in r["ambiguities"]), 2)
        self.assertEqual(r["patch_id"], "lru_cache")

    def test_bug_report_selects_the_collision_patch(self):
        r = analyze("Fix the short-code collision bug in the existing URL shortener and add click analytics.", repo_given=True)
        self.assertEqual(r["patch_id"], "collision_fix")
        self.assertIn("add_analytics", r["intents"])

    def test_unsupported_greenfield_domain_stops_with_a_clear_error(self):
        r = analyze("Build a hotel booking system.")
        with self.assertRaises(UnsupportedRequirement):
            build_tasks(r)

    def test_planner_graph_has_no_dangling_dependencies_and_parallel_branches(self):
        r = analyze("Build a scalable URL shortener service with APIs, persistence, and analytics.")
        tasks = build_tasks(r)
        ids = {t.id for t in tasks} | {"plan"}
        for t in tasks:
            self.assertTrue(set(t.deps) <= ids, t.id)
        by = {t.id: t for t in tasks}
        self.assertEqual(by["contract"].deps, by["code"].deps)      # siblings: can run in parallel
        self.assertIn("approve_design", by["code"].deps)             # nothing is generated before human approval


if __name__ == "__main__":
    unittest.main()
