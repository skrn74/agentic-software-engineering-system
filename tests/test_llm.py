import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from agentic.agents.requirement import run as analyze_run
from agentic.orchestrator import Context
from agentic.reasoner import LLMReasoner, Reasoner

import os
import urllib.request

# Local mock servers must bypass any corporate proxy configured on this machine.
for _k in ("NO_PROXY", "no_proxy"):
    os.environ[_k] = "127.0.0.1,localhost"
urllib.request.install_opener(None)

def serve(handler_cls):
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Good(BaseHTTPRequestHandler):
    def do_POST(self):
        content = {"ambiguities": [{"topic": "Multi-region", "question": "Is multi-region needed?", "assumption": "Single region."},
                                   {"topic": "bad item"}, "not a dict"]}
        body = json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class Broken(Good):
    def do_POST(self):
        self.send_response(500)
        self.send_header("Content-Length", "0")
        self.end_headers()


class TestLlmAdapter(unittest.TestCase):
    def _ctx(self, reasoner):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Context(tmp.name, {"requirement": "Build a scalable URL shortener service with APIs, persistence, and analytics."},
                       reasoner, quiet=True)

    def test_valid_llm_suggestions_are_added_and_tagged_and_malformed_ones_are_dropped(self):
        srv = serve(Good)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        r = LLMReasoner(f"http://127.0.0.1:{srv.server_port}", "k", "m", timeout=5)
        out = analyze_run(None, self._ctx(r))
        llm = [a for a in out.data["ambiguities"] if a["source"] == "llm"]
        self.assertEqual([a["topic"] for a in llm], ["Multi-region"])
        self.assertEqual(llm[0]["severity"], "assumable")           # an LLM can never create a blocking item

    def test_llm_failure_degrades_to_offline_rules(self):
        srv = serve(Broken)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        r = LLMReasoner(f"http://127.0.0.1:{srv.server_port}", "k", "m", timeout=5)
        out = analyze_run(None, self._ctx(r))
        self.assertTrue(r.last_error)
        self.assertEqual([a for a in out.data["ambiguities"] if a["source"] == "llm"], [])
        self.assertGreaterEqual(len(out.data["ambiguities"]), 4)

    def test_offline_reasoner_returns_nothing(self):
        self.assertIsNone(Reasoner().complete_json("s", "u"))


if __name__ == "__main__":
    unittest.main()
