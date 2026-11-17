"""Guardrails: sandboxed paths, static safety checks on generated code, bounded test runs."""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import time
from pathlib import Path


class GuardrailViolation(Exception):
    pass


def safe_join(root, rel: str) -> Path:
    """Resolve `rel` under `root`; refuse anything that escapes the workspace."""
    root = Path(root).resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise GuardrailViolation(f"path escapes the workspace: {rel}")
    return target


BANNED_NAMES = {"eval", "exec", "__import__"}
BANNED_ATTRS = {
    ("os", "system"), ("os", "popen"), ("pickle", "load"), ("pickle", "loads"),
    ("subprocess", "run"), ("subprocess", "Popen"), ("subprocess", "call"), ("subprocess", "check_output"),
}
SQL_METHODS = {"execute", "executemany", "executescript"}


def scan_python(path: str, text: str) -> list[str]:
    """Static checks on generated Python: syntax, dangerous calls, SQL built by string formatting."""
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [f"{path}: syntax error at line {exc.lineno}"]
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id in BANNED_NAMES:
            findings.append(f"{path}:{node.lineno}: banned call {fn.id}()")
        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and (fn.value.id, fn.attr) in BANNED_ATTRS:
            findings.append(f"{path}:{node.lineno}: banned call {fn.value.id}.{fn.attr}()")
        if isinstance(fn, ast.Attribute) and fn.attr in SQL_METHODS and node.args:
            arg = node.args[0]
            built = isinstance(arg, (ast.JoinedStr, ast.BinOp)) or (
                isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "format")
            if built:
                findings.append(f"{path}:{node.lineno}: SQL built by string formatting (use parameters)")
    return findings


SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
    (re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)(api[_-]?key|secret|token)\s*=\s*['\"][A-Za-z0-9/+_\-]{16,}['\"]"), "hard-coded credential"),
]


def scan_secrets(path: str, text: str) -> list[str]:
    return [f"{path}: possible {label}" for rx, label in SECRET_PATTERNS if rx.search(text)]


_FAIL_LINE = re.compile(r"^(\w+) \(([\w.]+)\) \.\.\. (FAIL|ERROR)\s*$", re.M)
_RAN_LINE = re.compile(r"^Ran (\d+) tests?", re.M)


def run_unittests(cwd, timeout: int = 120) -> dict:
    """Run `unittest discover` in a subprocess with a hard timeout. No network access is needed or used."""
    cwd = Path(cwd)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(cwd))
    cmd = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
        ok = proc.returncode == 0
    except subprocess.TimeoutExpired:
        return {"ok": False, "ran": 0, "failures": ["(timeout)"], "output_tail": f"timed out after {timeout}s",
                "seconds": round(time.time() - t0, 2)}
    ran = _RAN_LINE.search(out)
    return {
        "ok": ok,
        "ran": int(ran.group(1)) if ran else 0,
        "failures": [m.group(1) for m in _FAIL_LINE.finditer(out)],
        "output_tail": out[-1800:],
        "seconds": round(time.time() - t0, 2),
    }
