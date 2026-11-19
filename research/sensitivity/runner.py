"""One preregistered sensitivity study, separate from the optimization campaign."""
import argparse
import concurrent.futures
import csv
import datetime as dt
import gzip
import hashlib
import json
import os
import platform
import secrets
import subprocess
import sys
import time
from pathlib import Path

import numpy
import scipy
import simpy

from model import ROOT, FACTORS, POLICIES, configuration, scenarios, sha, simulate
from analysis import METRICS, summarize
from soft_procedure.config import SimulationConfig, ROUTES

OUT = ROOT / "outputs/sensitivity_20261022"
HERE = Path(__file__).resolve().parent


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    os.replace(temporary, path)


def parent_files():
    paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "f4d9674"], cwd=ROOT).decode().splitlines()
    prefixes = ("src/", "search_workspace/", "outputs/contribution_loop_20261022/",
                "research/contribution_loop/", "docs/flexline/")
    return {path: sha(ROOT / path) for path in paths if path.startswith(prefixes) or path in ("pyproject.toml", "uv.lock")}


def check_sources(protocol):
    for field in ("frozen_files", "prior_archive_files"):
        for path, digest in protocol[field].items():
            if sha(ROOT / path) != digest:
                raise ValueError("Frozen artifact changed: " + path)


def initialize():
    if (OUT / "protocol.json").exists():
        raise ValueError("Study already registered; do not overwrite its protocol or seeds")
    preflight = read(OUT / "preflight.json")
    if not preflight["passed"] or len(preflight["replays"]) != 15:
        raise ValueError("Physical adapter / exact fixed-policy replay gates must pass first")
    for path, digest in preflight["source_hashes"].items():
        if sha(ROOT / path) != digest:
            raise ValueError("Implementation changed after preflight")
    n = 200
    bank = []
    old_banks = ROOT / "outputs/contribution_loop_20261022/evaluator/private/seeds.json"
    used = set(range(42, 6001))
    if old_banks.exists():
        for values in read(old_banks).values():
            used.update(values)
    while len(bank) < n:
        value = secrets.randbits(63)
        if value not in used:
            bank.append(value)
            used.add(value)
    private = OUT / "private"
    private.mkdir(mode=0o700, exist_ok=True)
    os.chmod(private, 0o700)
    write(private / "seeds.json", bank)
    os.chmod(private / "seeds.json", 0o600)
    source_files = {str(p.relative_to(ROOT)): sha(p) for p in HERE.glob("*.py") if p.name in ("model.py", "analysis.py", "runner.py", "preflight.py")}
    variants = scenarios()
    for scenario in variants:
        config, speed = configuration(scenario)
        scenario["configuration"] = config.to_dict()
        scenario["physical_processing_speed"] = speed
    protocol = {"schema_version": 1, "study_id": "sensitivity-20261022-01", "study_type": "fixed-policy-physical-parameter-sensitivity",
                "registered_at": now(), "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
                "not_optimization": True, "previous_study": "contribution-loop-20261022-01",
                "question": "在三个固定调度策略下，物理参数的 ±2%/±5% 单独变化如何改变 40 小时结果？",
                "policies": POLICIES, "policy_sources": {p: {"path": f"search_workspace/candidates/{p}/policy.py",
                    "sha256": sha(ROOT / f"search_workspace/candidates/{p}/policy.py")} for p in POLICIES},
                "factors": FACTORS, "scenarios": variants, "replications": n,
                "planned_runs": len(POLICIES) * len(variants) * n, "primary_comparisons": len(POLICIES) * (len(variants) - 1),
                "baseline_configuration": SimulationConfig().to_dict(), "nominal_routes": ROUTES,
                "seed_commitment": hashlib.sha256(json.dumps(bank, separators=(",", ":")).encode()).hexdigest(),
                "randomization": "200 fresh distinct seeds committed before study; CRN across all 17 scenarios and all 3 fixed policies; no resampling or adaptive extra runs",
                "statistics": {"primary": "operating_contribution", "family_alpha": .05,
                               "family": "48 paired parameter-vs-own-standard contrasts, across 3 fixed policies × 4 factors × 4 nonzero levels",
                               "interval": "two-sided paired Student t, Bonferroni alpha=.05/48 for G; secondary metrics descriptive 95%",
                               "relative": "ratio of mean paired change to mean own baseline; approximate paired delta-method bounds",
                               "elasticity": "central ±5% relative response, approximate paired delta-method descriptive 95%; not a calibrated causal mechanism",
                               "interpretation": "interval crossing zero is unresolved at this sample size, not evidence of zero sensitivity"},
                "controls": ["fixed policy source and parameters", "fixed nominal means provided to each policy", "no strategy search, retraining or recalibration",
                             "same routes, machine counts, buffer, product mix, batch distribution, setup time, prices and costs",
                             "same empty start, [0,2400) window, unfinished-work costs and no inventory salvage",
                             "new study identity, output folder, ledger, seed bank and inference family; no changes to previous optimization alpha ledger"],
                "limitations": ["局部单参数分析，未评估参数交互或长期稳态", "完成周期只统计完成件，不能代表全部到达件的交期",
                                "故障较少；区间跨零时不能据此认定不敏感", "经营贡献不是完整净利润；不包含改变参数的实施成本",
                                "c20 的名义排序信息固定；这是固定控制器面对物理参数偏差的敏感性", "不将任何参数情景作为上一轮可行改进方案或新增胜出候选"],
                "runtime": {"python": platform.python_version(), "simpy": simpy.__version__, "scipy": scipy.__version__, "numpy": numpy.__version__,
                            "policy_execution": "hash-verified fixed policies in-process; 15 full trajectory/action replays against original isolated worker passed; not a sandbox for new candidates"},
                "frozen_files": source_files, "prior_archive_files": parent_files(),
                "privacy": "raw trajectories and seed bank remain local; only summaries, row metrics and hash manifests are tracked"}
    write(OUT / "protocol.json", protocol)
    progress = {"study_id": protocol["study_id"], "status": "registered", "started_at": None, "updated_at": now(),
                "completed_runs": 0, "planned_runs": protocol["planned_runs"], "completed_cells": [], "active_cell": None,
                "last_event_sha256": "0" * 64, "protocol_sha256": sha(OUT / "protocol.json")}
    write(OUT / "progress.json", progress)
    print(json.dumps({"registered": protocol["study_id"], "planned_runs": protocol["planned_runs"], "primary_comparisons": protocol["primary_comparisons"]}), flush=True)


def event(progress, kind, **values):
    value = {"at": now(), "kind": kind, **values, "previous_sha256": progress["last_event_sha256"]}
    digest = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    value["sha256"] = digest
    with (OUT / "events.jsonl").open("a") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    progress["last_event_sha256"] = digest
    progress["updated_at"] = value["at"]


def single(policy, digest, scenario, seed, replication):
    started = time.monotonic()
    result, metrics = simulate(policy, digest, scenario, seed)
    result["sensitivity"] = {"study_id": "sensitivity-20261022-01", "policy": policy, "scenario": scenario,
                             "nominal_policy_observations_fixed": True, "policy_sha256": digest}
    path = OUT / f"private/raw/{policy}/{scenario['id']}/{replication:03d}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "xt", encoding="utf-8", compresslevel=3) as stream:
        json.dump(result, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return {"policy": policy, "scenario": scenario["id"], "replication": replication,
            **metrics, "seconds": time.monotonic() - started,
            "raw_path": str(path.relative_to(OUT)), "raw_sha256": sha(path), "raw_bytes": path.stat().st_size}


def render_if_available():
    renderer = HERE / "render.py"
    if renderer.exists():
        subprocess.run([sys.executable, str(renderer)], cwd=ROOT, check=False, stdout=subprocess.DEVNULL)


def run(workers):
    protocol, progress = read(OUT / "protocol.json"), read(OUT / "progress.json")
    if progress["status"] != "registered" or (OUT / "runs.jsonl").exists():
        raise ValueError("Study already attempted; automatic replay/resampling is forbidden")
    check_sources(protocol)
    if sha(OUT / "protocol.json") != progress["protocol_sha256"]:
        raise ValueError("Protocol changed after registration")
    bank = read(OUT / "private/seeds.json")
    if hashlib.sha256(json.dumps(bank, separators=(",", ":")).encode()).hexdigest() != protocol["seed_commitment"]:
        raise ValueError("Seed commitment differs")
    progress.update(status="running", started_at=now())
    event(progress, "study_started", planned_runs=protocol["planned_runs"])
    rows = []
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            # Scenario order is fixed before any outcome is observed. Standard
            # cases for all three policies finish before perturbation cases.
            for scenario in protocol["scenarios"]:
                for policy in protocol["policies"]:
                    check_sources(protocol)
                    progress["active_cell"] = {"policy": policy, "scenario": scenario["id"]}
                    event(progress, "cell_started", **progress["active_cell"])
                    write(OUT / "progress.json", progress)
                    tasks = [pool.submit(single, policy, protocol["policy_sources"][policy]["sha256"], scenario, seed, i)
                             for i, seed in enumerate(bank)]
                    for future in concurrent.futures.as_completed(tasks):
                        row = future.result()
                        with (OUT / "runs.jsonl").open("a") as stream:
                            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                            stream.flush()
                            os.fsync(stream.fileno())
                        rows.append(row)
                        progress["completed_runs"] += 1
                        event(progress, "replication_finished", policy=policy, scenario=scenario["id"], replication=row["replication"], raw_sha256=row["raw_sha256"])
                        if progress["completed_runs"] % 25 == 0:
                            write(OUT / "progress.json", progress)
                    progress["completed_cells"].append(progress["active_cell"])
                    event(progress, "cell_finished", **progress["active_cell"])
                    write(OUT / "summary.json", summarize(protocol, rows))
                    write(OUT / "progress.json", progress)
                    render_if_available()
                    print(json.dumps({"completed": progress["completed_runs"], "total": protocol["planned_runs"], **progress["active_cell"]}), flush=True)
        check_sources(protocol)
        fields = ["policy", "scenario", "replication", *METRICS, "setup_count", "decisions", "seconds", "action_trace_sha256", "raw_sha256"]
        ordered = sorted(rows, key=lambda r: (r["policy"], r["scenario"], r["replication"]))
        with (OUT / "replications.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(ordered)
        write(OUT / "raw_manifest.json", [{"path": r["raw_path"], "sha256": r["raw_sha256"], "bytes": r["raw_bytes"]} for r in ordered])
        progress.update(status="completed", finished_at=now(), active_cell=None)
        event(progress, "study_completed", completed_runs=len(rows), outcome="parameter_sensitivity_estimated_not_strategy_optimization")
        write(OUT / "progress.json", progress)
        render_if_available()
    except BaseException as error:
        progress["status"] = "failed"
        event(progress, "study_failed", error=type(error).__name__ + ": " + str(error))
        write(OUT / "progress.json", progress)
        render_if_available()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "run"])
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error("workers must be between 1 and 8")
    initialize() if args.command == "init" else run(args.workers)
