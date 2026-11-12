"""Run the unchanged Case 22 baseline for multiple working-year horizons.

Usage: uv run --locked python tools/run_long_horizon_experiments.py --output outputs/long_horizon
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import gc
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import subprocess
import time

from soft_procedure import SimulationConfig, run_simulation
from soft_procedure.experiments import estimate


def run_one(years: int, seed: int, annual_minutes: float) -> dict:
    started = time.monotonic()
    horizon = years * annual_minutes
    # Only playback sampling changes. All production events and random streams
    # still come from the project's original run_simulation implementation.
    config = SimulationConfig(horizon=horizon, sample_interval=horizon)
    result = run_simulation(config, seed)
    summary = result["summary"]
    assert sum(p["completed"] for p in result["products"].values()) == summary["completed"]
    assert sum(p["sales_revenue"] for p in result["products"].values()) == summary["sales_revenue"]
    assert summary["arrived"] == summary["completed"] + summary["wip"] + summary["external"]
    assert abs(summary["sales_revenue"] - summary["operating_cost"] - summary["operating_contribution"]) < 1e-6
    assert all(abs(sum(s["states"].values()) - 1) < 1e-9 for s in result["stations"])
    row = {
        "years": years, "seed": seed, "horizon_minutes": horizon,
        "elapsed_seconds": time.monotonic() - started,
        "summary": {**summary,
                    "completed_per_year": summary["completed"] / years,
                    "completion_fraction": summary["completed"] / summary["arrived"],
                    "external_per_year": summary["external"] / years,
                    "operating_contribution_per_year": summary["operating_contribution"] / years},
        "products": result["products"], "stations": result["stations"],
        "economics": result["economics"], "checks": result["checks"],
    }
    # Do not carry millions of job dictionaries back to the parent process.
    del result
    gc.collect()
    return row


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", nargs="+", type=int, default=[1, 5, 10])
    parser.add_argument("--working-days", type=int, default=250)
    parser.add_argument("--hours-per-day", type=float, default=8)
    parser.add_argument("--replications", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (not args.years or min(args.years) < 1 or len(set(args.years)) != len(args.years)
            or args.working_days < 1 or not 0 < args.hours_per_day <= 24
            or not 1 <= args.replications <= 30 or args.workers < 1):
        parser.error("Use unique positive years, positive working days, 0–24 hours/day, 1–30 repetitions and positive workers")
    annual_minutes = args.working_days * args.hours_per_day * 60
    # Fail on an existing directory, so this never overwrites prior evidence.
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    source_paths = sorted((root / "src").rglob("*.py")) + [Path(__file__).resolve()]
    manifest = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scenario": "baseline", "years": args.years,
        "working_days_per_year": args.working_days, "hours_per_day": args.hours_per_day,
        "annual_working_minutes": annual_minutes, "replications": args.replications,
        "seeds": list(range(args.seed, args.seed + args.replications)),
        "python": platform.python_version(), "simpy": version("simpy"),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "source_sha256": manifest, "base_config": SimulationConfig().to_dict(),
        "method": [
            "Actual independent SimPy runs from an empty system; no warm-up or annual reset.",
            "Working-time clock: no nights, holidays or calendar-time repair between shifts.",
            "Each horizon uses seeds 42–51 by default; horizons share arrival/random-stream prefixes.",
            "Only sample_interval is set to horizon; two playback snapshots, all event logs retained internally.",
            "Prices, arrivals, routing, FIFO, failure/repair and cost rules are unchanged.",
            "No equipment aging, replacement, depreciation, inflation, discounting or demand limits.",
            "Operating contribution is sales revenue minus modeled operating cost, not net profit.",
            "95% Student-t confidence intervals describe replication means under fixed model assumptions.",
            "Long-horizon output omits per-job/event serialization from saved files; summaries/checks come from the original engine.",
        ],
    }
    (args.output / "experiment.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, year, seed, annual_minutes): (year, seed)
                   for year in args.years for seed in metadata["seeds"]}
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            name = f"{row['years']}y_seed{row['seed']}.json"
            (args.output / name).write_text(json.dumps(row, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
            print(f"{len(rows)}/{len(futures)}: {row['years']}y seed={row['seed']} "
                  f"completed={row['summary']['completed']} external={row['summary']['external']} "
                  f"elapsed={row['elapsed_seconds']:.1f}s", flush=True)
    rows.sort(key=lambda r: (r["years"], r["seed"]))
    aggregates = []
    product_rows, station_rows = [], []
    for year in sorted(args.years):
        group = [r for r in rows if r["years"] == year]
        statistics = {key: estimate([r["summary"][key] for r in group]) for key in group[0]["summary"]}
        aggregates.append({"years": year, "statistics": statistics})
        for product in group[0]["products"]:
            product_rows.append({"years": year, "product": product,
                                 **estimate([r["products"][product]["completed"] for r in group])})
        for i, station in enumerate(group[0]["stations"]):
            for metric in station["states"]:
                station_rows.append({"years": year, "station": station["name"], "metric": metric,
                                     **estimate([r["stations"][i]["states"][metric] for r in group])})
            for metric in ("mean_queue", "mean_wait", "failure_count", "setup_count"):
                station_rows.append({"years": year, "station": station["name"], "metric": metric,
                                     **estimate([r["stations"][i][metric] for r in group])})
    bundle = {"experiment": metadata, "horizons": aggregates, "runs": rows}
    (args.output / "results.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    write_csv(args.output / "replications.csv", [{"years": r["years"], "seed": r["seed"], **r["summary"]} for r in rows])
    write_csv(args.output / "summary.csv", [{"years": a["years"], "metric": key, **stat,
        "ci95_low": stat["mean"] - stat["ci95"] if stat["ci95"] is not None else None,
        "ci95_high": stat["mean"] + stat["ci95"] if stat["ci95"] is not None else None}
        for a in aggregates for key, stat in a["statistics"].items()])
    write_csv(args.output / "products.csv", product_rows)
    write_csv(args.output / "stations.csv", station_rows)
    print(f"Complete: {args.output.resolve()}", flush=True)


if __name__ == "__main__":
    main()
