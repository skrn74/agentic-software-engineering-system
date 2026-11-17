from . import brownfield, codebase, design, generation, planner, reporter, requirement, risk, validator

AGENTS = {
    "analyze": requirement.run,
    "plan": planner.run,
    "design": design.run,
    "contract": generation.contract,
    "code": generation.code,
    "tests": generation.tests,
    "docs": generation.docs,
    "risk": risk.run,
    "validate": validator.run,
    "repair": generation.repair,
    "summary": reporter.run,
    "scan_repo": codebase.scan,
    "impact": codebase.impact,
    "baseline": brownfield.baseline,
    "bf_tests": brownfield.write_tests,
    "red_check": brownfield.red_check,
    "patch": brownfield.patch,
}
