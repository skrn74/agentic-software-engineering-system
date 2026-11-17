import tempfile
import unittest

from agentic.guardrails import GuardrailViolation, safe_join, scan_python, scan_secrets


class TestGuardrails(unittest.TestCase):
    def test_safe_join_allows_children_and_blocks_escapes(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(str(safe_join(d, "a/b.txt")).endswith("b.txt"))
            for bad in ["../x.txt", "a/../../x.txt", "/etc/passwd"]:
                with self.subTest(path=bad):
                    with self.assertRaises(GuardrailViolation):
                        safe_join(d, bad)

    def test_scan_flags_dangerous_calls(self):
        code = "import os\nos.system('rm -rf /')\neval('1+1')\n"
        findings = scan_python("x.py", code)
        self.assertEqual(len(findings), 2)

    def test_scan_flags_string_built_sql_but_not_parameters(self):
        bad = "def f(c, x):\n    c.execute(f\"SELECT * FROM t WHERE a = {x}\")\n    c.execute('SELECT ' + x)\n"
        good = "def f(c, x):\n    c.execute('SELECT * FROM t WHERE a = ?', (x,))\n"
        self.assertEqual(len(scan_python("bad.py", bad)), 2)
        self.assertEqual(scan_python("good.py", good), [])

    def test_scan_reports_syntax_errors(self):
        self.assertIn("syntax error", scan_python("x.py", "def (:\n")[0])

    def test_secret_scan(self):
        self.assertTrue(scan_secrets("a.py", "KEY = 'AKIAABCDEFGHIJKLMNOP'"))
        self.assertTrue(scan_secrets("a.py", "api_key = 'abcdefghijklmnop1234'"))
        self.assertEqual(scan_secrets("a.py", "x = 1"), [])


if __name__ == "__main__":
    unittest.main()
