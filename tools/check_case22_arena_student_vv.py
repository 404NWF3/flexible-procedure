"""Check normalized Arena Student V&V outputs against the case-22 expectations.

Arena reports are intentionally normalized outside this checker. The input CSV
must contain one row per measured metric with these columns:

    experiment_id,metric,actual_value,unit,replication,model_version,evidence_path

The checker is deliberately small and dependency-free so it can run on the
same Windows Python installation used for the project.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


REQUIRED_ACTUAL_COLUMNS = {
    "experiment_id",
    "metric",
    "actual_value",
    "unit",
    "replication",
    "model_version",
    "evidence_path",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")
        return list(reader)


def _as_number(value: str) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize_text(value: str) -> str:
    return ";".join(part.strip() for part in value.strip().split(";"))


def _check_row(expected: dict[str, str], actual: dict[str, str]) -> dict[str, Any]:
    expected_value = expected["expected_value"]
    actual_value = actual["actual_value"]
    tolerance = float(expected["tolerance"])
    expected_number = _as_number(expected_value)
    actual_number = _as_number(actual_value)

    if expected_number is not None and actual_number is not None:
        error = abs(actual_number - expected_number)
        passed = error <= tolerance
    else:
        error = None
        passed = _normalize_text(actual_value) == _normalize_text(expected_value)

    return {
        "experiment_id": expected["experiment_id"],
        "metric": expected["metric"],
        "expected_value": expected_value,
        "actual_value": actual_value,
        "unit": expected["unit"],
        "tolerance": tolerance,
        "error": error,
        "replication": actual.get("replication", ""),
        "model_version": actual.get("model_version", ""),
        "evidence_path": actual.get("evidence_path", ""),
        "passed": passed,
    }


def check(expected_path: Path, actual_path: Path, require_evidence: bool) -> dict[str, Any]:
    expected_rows = _read_csv(expected_path)
    actual_rows = _read_csv(actual_path)
    missing_columns = REQUIRED_ACTUAL_COLUMNS.difference(actual_rows[0].keys() if actual_rows else set())
    if missing_columns:
        raise ValueError(
            "Actual CSV is missing columns: " + ", ".join(sorted(missing_columns))
        )

    actual_by_key: dict[tuple[str, str], dict[str, str]] = {}
    duplicate_keys: list[tuple[str, str]] = []
    for row in actual_rows:
        key = (row["experiment_id"].strip(), row["metric"].strip())
        if key in actual_by_key:
            duplicate_keys.append(key)
        actual_by_key[key] = row

    results: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for expected in expected_rows:
        key = (expected["experiment_id"].strip(), expected["metric"].strip())
        actual = actual_by_key.get(key)
        if actual is None:
            missing.append(expected)
            continue
        result = _check_row(expected, actual)
        if require_evidence and not result["evidence_path"]:
            result["passed"] = False
            result["evidence_error"] = "evidence_path is empty"
        results.append(result)

    invariant_failures: list[dict[str, Any]] = []
    for row in actual_rows:
        metric = row["metric"].strip()
        value = _as_number(row["actual_value"])
        if value is None:
            continue
        if metric == "max_entities" and value > 150:
            invariant_failures.append({"row": row, "reason": "Student entity limit exceeded"})
        if metric == "conservation_gap" and abs(value) > 0:
            invariant_failures.append({"row": row, "reason": "conservation gap is nonzero"})

    failed_results = [result for result in results if not result["passed"]]
    failed_results.extend(invariant_failures)
    return {
        "expected_path": str(expected_path),
        "actual_path": str(actual_path),
        "expected_count": len(expected_rows),
        "matched_count": len(results),
        "missing_count": len(missing),
        "failed_count": len(failed_results),
        "duplicate_keys": duplicate_keys,
        "missing": missing,
        "results": results,
        "invariant_failures": invariant_failures,
        "passed": not missing and not duplicate_keys and not failed_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--actual", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--require-evidence", action="store_true")
    args = parser.parse_args()

    report = check(args.expected, args.actual, args.require_evidence)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
