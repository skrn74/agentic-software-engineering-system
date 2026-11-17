"""Codebase analyst (brownfield): AST-based scan, call graph, data flows and impact analysis."""
from __future__ import annotations

import ast
import math
import re
from pathlib import Path

from ..models import Outcome

SQL_RX = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE\s+TABLE)\b", re.I)
TABLE_RX = re.compile(r"(?:FROM|INTO|UPDATE)\s+(\w+)|CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+(\w+)", re.I)
SKIP_TABLE_WORDS = {"if", "not", "exists", "select"}


def _tables(sql: str) -> set[str]:
    found = set()
    for m in TABLE_RX.finditer(sql):
        name = (m.group(1) or m.group(2) or "").lower()
        if name and name not in SKIP_TABLE_WORDS:
            found.add(name)
    return found


def _calls_in(fn: ast.AST, cls: str | None) -> list[tuple[str, str]]:
    """Return (receiver, name) pairs for every call inside a function."""
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                out.append(("", f.id))
            elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                out.append((f.value.id, f.attr))
    return out


def scan_repo(repo: Path) -> dict:
    modules: dict = {}
    for p in sorted(repo.rglob("*.py")):
        rel = p.relative_to(repo).as_posix()
        if "__pycache__" in rel:
            continue
        text = p.read_text(encoding="utf-8")
        tree = ast.parse(text)
        name = rel[:-3].replace("/", ".")
        info = {"path": rel, "loc": len(text.splitlines()), "imports": [], "functions": {}, "classes": [],
                "is_test": rel.startswith("tests/"), "routes": [], "text": text}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                info["imports"] += [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                info["imports"].append(node.module.split(".")[0])
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                info["functions"][node.name] = _fn_info(node, None)
            elif isinstance(node, ast.ClassDef):
                info["classes"].append(node.name)
                for sub in node.body:
                    if isinstance(sub, ast.FunctionDef):
                        info["functions"][f"{node.name}.{sub.name}"] = _fn_info(sub, node.name)
            elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ROUTES" for t in node.targets):
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    for el in node.value.elts:
                        if isinstance(el, ast.Tuple) and len(el.elts) >= 3 and isinstance(el.elts[0], ast.Constant) \
                                and isinstance(el.elts[1], ast.Constant) and isinstance(el.elts[2], ast.Name):
                            info["routes"].append({"method": el.elts[0].value, "path": el.elts[1].value, "handler": el.elts[2].id})
        modules[name] = info
    for m in modules.values():
        m["imports"] = sorted({i for i in m["imports"] if i in modules})
    return modules


def _fn_info(node: ast.FunctionDef, cls: str | None) -> dict:
    sql = [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str) and SQL_RX.search(n.value)]
    return {"calls": _calls_in(node, cls), "cls": cls, "line": node.lineno, "sql": sql,
            "tables": sorted({t for s in sql for t in _tables(s)}),
            "writes": any(re.search(r"\b(INSERT|UPDATE|DELETE)\b", s, re.I) for s in sql),
            "reads": any(re.search(r"\bSELECT\b", s, re.I) for s in sql)}


def _resolve(modules: dict, mod: str, fn_cls: str | None, receiver: str, name: str):
    """Best-effort resolution of a call to (module, qualified function)."""
    if receiver == "self" and fn_cls:
        q = f"{fn_cls}.{name}"
        return (mod, q) if q in modules[mod]["functions"] else None
    if receiver:
        for m, info in modules.items():
            for cls in info["classes"]:
                if cls.lower() == receiver.lower() and f"{cls}.{name}" in info["functions"]:
                    return (m, f"{cls}.{name}")
            if m == receiver and name in info["functions"]:
                return (m, name)
        return None
    if name in modules[mod]["functions"]:
        return (mod, name)
    for m in modules[mod]["imports"]:
        if name in modules[m]["functions"]:
            return (m, name)
    return None


def build_flows(modules: dict) -> list[dict]:
    flows = []
    for mod, info in modules.items():
        for route in info["routes"]:
            handler = route["handler"]
            seen, queue, touched, tables = set(), [(mod, handler)], [], set()
            while queue:
                m, q = queue.pop(0)
                if (m, q) in seen or q not in modules[m]["functions"]:
                    continue
                seen.add((m, q))
                fn = modules[m]["functions"][q]
                touched.append((m, q))
                tables |= set(fn["tables"])
                for rcv, nm in fn["calls"]:
                    r = _resolve(modules, m, fn["cls"], rcv, nm)
                    if r:
                        queue.append(r)
            flows.append({"route": f"{route['method']} {route['path']}", "handler": handler,
                          "functions": [f"{m}.{q}" for m, q in touched], "tables": sorted(tables)})
    return flows


def find_smells(modules: dict) -> list[dict]:
    smells = []
    for mod, info in modules.items():
        if info["is_test"]:
            continue
        for i, line in enumerate(info["text"].splitlines(), 1):
            m = re.search(r"hashlib\.(md5|sha1)\(.*\)\.hexdigest\(\)\[:(\d+)\]", line)
            if m:
                n = int(m.group(2))
                space = 16 ** n
                smells.append({"module": mod, "line": i, "kind": "truncated_hash",
                               "detail": f"{m.group(1)} digest truncated to {n} hex chars = {space:,} possible codes; "
                                         f"birthday collisions are expected after about {round(math.sqrt(2 * space * math.log(2))):,} links"})
            if re.search(r"INSERT\s+OR\s+REPLACE", line, re.I):
                smells.append({"module": mod, "line": i, "kind": "silent_overwrite",
                               "detail": "INSERT OR REPLACE silently overwrites an existing row with the same key"})
    return smells


def scan(task, ctx) -> Outcome:
    repo = Path(ctx.options["repo"]).resolve()
    modules = scan_repo(repo)
    flows = build_flows(modules)
    smells = find_smells(modules)
    public = {m: {k: v for k, v in info.items() if k not in ("text",)} for m, info in modules.items()}
    for m in public.values():
        m["functions"] = {k: {"line": v["line"], "tables": v["tables"], "reads": v["reads"], "writes": v["writes"]}
                          for k, v in m["functions"].items()}
    routes = [{"module": m, **r} for m, info in modules.items() for r in info["routes"]]
    tables = sorted({t for info in modules.values() for f in info["functions"].values() for t in f["tables"]})
    data = {"repo": str(repo), "modules": public, "routes": routes, "flows": flows, "tables": tables, "smells": smells,
            "tests": sorted(m for m, i in modules.items() if i["is_test"])}
    md = ["# Repository scan", "", f"Repository: `{repo.name}`", "", "| Module | LOC | Imports | Functions |", "|---|---|---|---|"]
    md += [f"| {m} | {i['loc']} | {', '.join(i['imports']) or '-'} | {', '.join(i['functions']) or '-'} |"
           for m, i in public.items() if not i["is_test"]]
    md += ["", "## Data flows", ""] + [f"- `{f['route']}` -> {' -> '.join(f['functions'])}  (tables: {', '.join(f['tables']) or 'none'})" for f in flows]
    md += ["", "## Findings", ""] + [f"- `{s['module']}.py:{s['line']}` {s['kind']}: {s['detail']}" for s in smells]
    ctx.write("docs/repo_scan.md", "\n".join(md) + "\n")
    return Outcome(f"{len(modules)} modules, {len(routes)} routes, {len(tables)} tables, {len(smells)} findings", data)


def impact(task, ctx) -> Outcome:
    req = ctx.get("analyze")
    sc = ctx.get("scan")
    intents = req["intents"]
    modules = scan_repo(Path(sc["repo"]))
    seeds: dict[str, list[str]] = {}
    seed_funcs: set[tuple[str, str]] = set()

    def add(mod, why, fn=None):
        seeds.setdefault(mod, []).append(why)
        if fn:
            seed_funcs.add((mod, fn))

    root_cause = ""
    if "fix_collision" in intents:
        hs = [s for s in sc["smells"] if s["kind"] == "truncated_hash"]
        ow = [s for s in sc["smells"] if s["kind"] == "silent_overwrite"]
        for s in hs:
            fn = max((q for q, f in modules[s["module"]]["functions"].items() if f["line"] <= s["line"]),
                     key=lambda q: modules[s["module"]]["functions"][q]["line"], default=None)
            add(s["module"], s["detail"], fn)
        for s in ow:
            fn = max((q for q, f in modules[s["module"]]["functions"].items() if f["line"] <= s["line"]),
                     key=lambda q: modules[s["module"]]["functions"][q]["line"], default=None)
            add(s["module"], s["detail"], fn)
        root_cause = ("Short codes are a truncated hash, so different URLs can map to the same code, and the store overwrites on conflict. "
                      + " ".join(s["detail"] + "." for s in hs + ow))
    if "performance" in intents:
        for mod, info in modules.items():
            for q, f in info["functions"].items():
                if f["reads"] and not info["is_test"]:
                    add(mod, f"{q} runs a SELECT on the hot read path", q)
        root_cause = root_cause or "Every redirect performs a database read; there is no caching layer."
    if "add_analytics" in intents:
        for mod, info in modules.items():
            if info["routes"]:
                add(mod, "route table: a new stats endpoint is needed")
            if any(f["writes"] for f in info["functions"].values()):
                add(mod, "persistence layer: a clicks table and recorder are needed")

    callers: set[str] = set()
    for mod, info in modules.items():
        if info["is_test"]:
            continue
        for q, f in info["functions"].items():
            for rcv, nm in f["calls"]:
                r = _resolve(modules, mod, f["cls"], rcv, nm)
                if r and r in seed_funcs and mod not in seeds:
                    callers.add(mod)
                if r and r in seed_funcs and mod != r[0]:
                    callers.add(mod)
    if "fix_collision" in intents:           # callers must adapt to the new function contracts
        for c in callers:
            add(c, "calls a function whose contract changes (make_code / save)")
    modify = sorted(seeds)
    affected = sorted((callers | {m for m, i in modules.items() if any(x in modify for x in i["imports"]) and not i["is_test"]}) - set(modify))
    covering = sorted(m for m, i in modules.items() if i["is_test"] and (set(i["imports"]) & (set(modify) | set(affected))))
    apis = sorted({f["route"] for f in sc["flows"] if any(fn.split(".")[0] in modify for fn in f["functions"])})
    data = {"root_cause": root_cause or "No automatic root cause found for this requirement.", "modify": modify, "affected": affected,
            "tests_covering": covering, "apis": apis, "reasons": seeds}
    md = ["# Impact analysis", "", f"**Root cause / driver:** {data['root_cause']}", "", "## Modules to modify", ""]
    md += [f"- `{m}`: {'; '.join(dict.fromkeys(w))}" for m, w in seeds.items()] or ["- none"]
    md += ["", f"## Affected but not modified: {', '.join(affected) or 'none'}", "", f"## APIs impacted: {', '.join(apis) or 'none'}", "",
           f"## Existing tests covering these modules: {', '.join(covering) or 'none'}"]
    ctx.write("docs/impact_analysis.md", "\n".join(md) + "\n")
    return Outcome(f"modify {len(modify)} module(s), {len(affected)} affected, {len(apis)} API(s) impacted", data)
