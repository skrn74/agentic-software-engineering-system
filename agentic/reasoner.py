"""Pluggable reasoning backend.

Offline (default): returns None, so every agent falls back to its deterministic rules.
LLM (optional): any OpenAI-compatible chat-completions endpoint, enabled by environment variables.

Safety rule: LLM output is ADVISORY. Agents only accept it after schema validation, tag it
source="llm", and never let it override guardrails, validation results or approval gates.
"""
from __future__ import annotations

import json
import os
import urllib.request


class Reasoner:
    name = "offline"
    enabled = False

    def complete_json(self, system: str, user: str):
        return None


class LLMReasoner(Reasoner):
    enabled = True

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.name = f"llm:{model}"
        self.last_error = ""

    def complete_json(self, system: str, user: str):
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }).encode()
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.load(resp)
            content = payload["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else None
        except Exception as exc:  # noqa: BLE001 - any failure degrades to offline rules
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None


def make_reasoner() -> Reasoner:
    key = os.environ.get("LLM_API_KEY")
    if not key:
        return Reasoner()
    return LLMReasoner(
        base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
        api_key=key,
        model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
    )
