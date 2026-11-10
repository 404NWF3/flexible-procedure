"""Validate the Case 22 SimPy core-experiment result contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


EXPECTED_SCENARIOS = {
    "baseline",
    "m4_extra",
    "same_family",
    "same_family_m4_extra",
}


def validate(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if data.get("schema_version") != 2:
        errors.append(f"schema_version={data.get('schema_version')!r}, expected 2")
    if data.get("replications") != 10:
        errors.append(f"replications={data.get('replications')!r}, expected 10")

    scenarios = data.get("scenarios", [])
    actual_scenarios = {scenario.get("id") for scenario in scenarios}
    if actual_scenarios != EXPECTED_SCENARIOS:
        errors.append(f"scenario_ids={sorted(actual_scenarios)!r}")

    for scenario in scenarios:
        scenario_id = scenario.get("id")
        investment = scenario.get("investment")
        if not isinstance(investment, dict) or "payback_periods" not in investment:
            errors.append(f"{scenario_id}: missing investment/payback result")
        if "conditional_static_payback_weeks" in scenario:
            errors.append(f"{scenario_id}: obsolete week-based payback field is present")
        expected_parent = "same_family" if scenario_id == "same_family_m4_extra" else "baseline"
        if scenario.get("paired_to") != expected_parent:
            errors.append(f"{scenario_id}: paired_to={scenario.get('paired_to')!r}, expected {expected_parent!r}")
        runs = scenario.get("runs", [])
        if len(runs) != 10:
            errors.append(f"{scenario_id}: runs={len(runs)}, expected 10")
        seeds = [run.get("seed") for run in runs]
        if seeds != list(range(42, 52)):
            errors.append(f"{scenario_id}: seeds={seeds!r}")
        for run in runs:
            seed = run.get("seed")
            arrived = run.get("arrived")
            completed = run.get("completed")
            wip = run.get("wip")
            external = run.get("external")
            if arrived != completed + wip + external:
                errors.append(
                    f"{scenario_id}/{seed}: conservation={arrived - completed - wip - external}"
                )
            if any(run.get(name, 0) < 0 for name in ("arrived", "completed", "wip", "external")):
                errors.append(f"{scenario_id}/{seed}: negative count")
            if abs(run.get("sales_revenue", 0) - run.get("operating_cost", 0)
                   - run.get("operating_contribution", 0)) > 0.01:
                errors.append(f"{scenario_id}/{seed}: economic accounting does not reconcile")
            state_sum = sum(
                run.get(name, 0.0)
                for name in (
                    "processing_utilization",
                    "setup_share",
                    "repair_share",
                    "blocked_share",
                )
            )
            if not 0.0 <= state_sum <= 1.0 + 1e-9:
                errors.append(f"{scenario_id}/{seed}: state_sum={state_sum}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    errors = validate(args.results)
    if errors:
        print("FAIL")
        print("\n".join(errors))
        return 1
    print("PASS: core results satisfy schema, four-scenario, seed, conservation and state-share checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
