#!/usr/bin/env python
"""CLI: python run.py --scenario greenfield|brownfield|ambiguous  [--auto-approve] [--inject-fault]"""
import argparse
import sys

from agentic.engine import PRESETS, run_requirement
from agentic.orchestrator import auto_approver, interactive_approver


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Agentic software engineering system")
    ap.add_argument("--scenario", choices=sorted(PRESETS), help="run a preset example")
    ap.add_argument("--requirement", help="free-text requirement")
    ap.add_argument("--repo", help="path to an existing repository (brownfield)")
    ap.add_argument("--out", default="runs", help="output directory (default: runs)")
    ap.add_argument("--auto-approve", action="store_true", help="demo mode: approve every gate (assumptions are auto-accepted)")
    ap.add_argument("--inject-fault", action="store_true", help="inject a transient error and a code defect to demonstrate retry and repair")
    ap.add_argument("--resume", metavar="RUN_DIR", help="resume a previous run directory")
    args = ap.parse_args()

    if args.resume:
        res = run_requirement("", args.resume, resume=True, approver=auto_approver if args.auto_approve else interactive_approver)
    else:
        preset = PRESETS.get(args.scenario, {})
        requirement = args.requirement or preset.get("requirement")
        if not requirement:
            ap.error("give --scenario or --requirement")
        res = run_requirement(requirement, args.out, repo=args.repo or preset.get("repo"),
                              approver=auto_approver if args.auto_approve else interactive_approver,
                              inject_fault=args.inject_fault, name=args.scenario and f"{args.scenario}{'_fault' if args.inject_fault else ''}")
    print("\n" + "=" * 70)
    print(f"RUN STATUS: {res['status']}")
    print(f"Output:     {res['run_dir']}")
    print(f"Summary:    {res['run_dir']}/ENGINEERING_SUMMARY.md")
    return 0 if res["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
