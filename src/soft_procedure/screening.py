"""41 组阻塞筛选：同种子配对，逐次保存原始运行，独立于原五组实验。"""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import platform

import simpy

from .config import PRODUCT_MIX, ROUTES, STATIONS, SimulationConfig
from .experiments import estimate
from .export import write_csv
from .model.simulation import run_simulation
from .model.source import arrival_schedule


def screening_configs(base):
    """基准 + 5×2 增机 + 5×3 缓冲 + 5×3 加工时间倍率。"""
    base.validate()
    scenarios = [(dict(id="baseline", family="baseline", station=None, level=None), replace(base))]
    for station in STATIONS:
        for extra in (1, 2):
            scenarios.append((dict(id=f"machine_{station}_plus{extra}", family="machine", station=station,
                                   level=base.machine_counts[station] + extra),
                              replace(base, machine_counts={**base.machine_counts, station: base.machine_counts[station] + extra})))
        for extra in (25, 50, 150):
            capacity = base.buffer_capacity_for(station) + extra
            scenarios.append((dict(id=f"buffer_{station}_{capacity}", family="buffer", station=station, level=capacity),
                              replace(base, buffer_capacities={**base.buffer_capacities, station: capacity})))
        for factor in (0.90, 0.75, 0.50):
            multiplier = base.processing_multiplier_for(station) * factor
            scenarios.append((dict(id=f"processing_{station}_{factor:.2f}", family="processing", station=station, level=multiplier),
                              replace(base, processing_time_multipliers={**base.processing_time_multipliers, station: multiplier})))
    return scenarios


def screening_diagnostics(result, base):
    """从工件记录重建准入等待，包含期末仍在等待的截断时长。"""
    horizon = result["config"]["horizon"]
    original = {f"{station}-{i + 1}" for station, count in base.machine_counts.items() for i in range(count)}
    admissions = {s: {kind: dict(admitted_count=0, admitted_wait_minutes=0.0,
                                pending_count=0, pending_age_minutes=0.0)
                      for kind in ("external", "transfer")} for s in STATIONS}
    products = {}
    for job in result["jobs"]:
        operations = job["operations"]
        for index, operation in enumerate(operations):
            kind = "external" if index == 0 else "transfer"
            since = job["arrival_time"] if index == 0 else operations[index - 1]["processed_at"]
            row = admissions[operation["station"]][kind]
            row["admitted_count"] += 1
            row["admitted_wait_minutes"] += operation["queue_entered_at"] - since
        if job["admitted_at"] is None:
            row = admissions[ROUTES[job["product"]][0][0]]["external"]
            row["pending_count"] += 1
            row["pending_age_minutes"] += horizon - job["arrival_time"]
        elif operations and operations[-1]["processed_at"] is not None and operations[-1]["transferred_at"] is None:
            next_index = operations[-1]["operation_index"] + 1
            if next_index < len(ROUTES[job["product"]]):
                row = admissions[ROUTES[job["product"]][next_index][0]]["transfer"]
                row["pending_count"] += 1
                row["pending_age_minutes"] += horizon - operations[-1]["processed_at"]
    for station in admissions.values():
        for row in station.values():
            row["mean_pending"] = (row["admitted_wait_minutes"] + row["pending_age_minutes"]) / horizon
    for product in PRODUCT_MIX:
        jobs = [j for j in result["jobs"] if j["product"] == product]
        ages = [horizon - j["arrival_time"] for j in jobs if j["completion_time"] is None]
        products[product] = {**result["products"][product], "unfinished_count": len(ages),
                             "unfinished_age_mean": sum(ages) / len(ages) if ages else None,
                             "unfinished_age_max": max(ages, default=None)}
    return {
        "original_machine_blocked_minutes": sum(m["state_times"]["blocked"] for m in result["machines"] if m["name"] in original),
        "admissions": admissions, "products": products,
    }


def run_screening(config=None, replications=10, seed=42, *, output, progress=None):
    base = (config or SimulationConfig()).validate()
    if type(replications) is not int or not 1 <= replications <= 30:
        raise ValueError("重复次数必须为 1–30 的整数")
    if type(seed) is not int:
        raise ValueError("seed 必须为整数")
    output = Path(output)
    if (output / "manifest.json").exists():
        raise ValueError("目标目录已有筛选实验；请使用新的输出目录，保留原始记录")
    output.mkdir(parents=True, exist_ok=True)
    seeds = list(range(seed, seed + replications))
    schedules = {s: arrival_schedule(base, s) for s in seeds}
    scenarios = screening_configs(base)
    manifest = {
        "schema_version": 1, "status": "running", "generated_at": datetime.now(timezone.utc).isoformat(),
        "study": "blocking_screening_41", "base_config": base.to_dict(), "seeds": seeds,
        "replications": replications, "python": platform.python_version(), "simpy": simpy.__version__,
        "source_sha256": {str(p.relative_to(Path(__file__).parent)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(Path(__file__).parent.rglob("*.py"))},
        "arrival_schedule_sha256": {str(s): hashlib.sha256(json.dumps([asdict(a) for a in schedule], sort_keys=True).encode()).hexdigest()
                                    for s, schedule in schedules.items()},
        "scenarios": [{**meta, "config": current.to_dict()} for meta, current in scenarios],
        "inference": "第一轮探索；95% t 区间为逐项配对区间，非多重比较校正或独立种子确认。",
        "breakthrough_target": {"blocked_reduction": 0.30, "output_increase": 0.10},
    }

    def save(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))

    save("manifest.json", manifest)
    summaries, all_runs, baseline = [], [], None
    for meta, current in scenarios:
        directory = output / "runs" / meta["id"]
        directory.mkdir(parents=True, exist_ok=True)
        runs = []
        for current_seed in seeds:
            result = run_simulation(current, current_seed, schedule=schedules[current_seed])
            diagnostic = screening_diagnostics(result, base)
            result["screening_diagnostics"] = diagnostic
            assert result["checks"]["conservation_error"] == 0
            # 准入等待面积独立地对应线外存量和加工后占机阻塞。
            transfer_minutes = sum(row["transfer"]["mean_pending"] * current.horizon for row in diagnostic["admissions"].values())
            external_minutes = sum(row["external"]["mean_pending"] * current.horizon for row in diagnostic["admissions"].values())
            assert abs(transfer_minutes - result["summary"]["blocked_machine_minutes"]) < 1e-6
            assert abs(external_minutes / current.horizon - result["summary"]["mean_external"]) < 1e-6
            raw_path = directory / f"{current_seed}.json.gz"
            with gzip.open(raw_path, "wt", encoding="utf-8", compresslevel=3) as stream:
                json.dump(result, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            row = {"scenario": meta["id"], "seed": current_seed, **result["summary"],
                   "original_machine_blocked_minutes": diagnostic["original_machine_blocked_minutes"]}
            for product, data in diagnostic["products"].items():
                for key in ("arrived", "completed", "unfinished_count", "unfinished_age_mean", "unfinished_age_max"):
                    row[f"{product}_{key}"] = data[key]
            for station in result["stations"]:
                for key in ("blocked_machine_minutes", "mean_queue", "full_buffer_share"):
                    row[f"{station['name']}_{key}"] = station[key]
                for state, value in station["states"].items():
                    row[f"{station['name']}_{state}_share"] = value
                for kind, data in diagnostic["admissions"][station["name"]].items():
                    for key, value in data.items():
                        row[f"{station['name']}_{kind}_{key}"] = value
            runs.append(row)
            all_runs.append(row)
        if baseline is None:
            baseline = runs
        metrics = [k for k in runs[0] if k not in ("scenario", "seed")]
        stats = {k: estimate([r[k] for r in runs]) for k in metrics}
        paired_keys = ("completed", "blocked_machine_minutes", "original_machine_blocked_minutes",
                       "mean_wip", "wip", "external", "mean_cycle_time", "unfinished_age_mean",
                       *[f"{p}_completed" for p in PRODUCT_MIX])
        paired = {k: estimate([r[k] - b[k] if r[k] is not None and b[k] is not None else None
                               for r, b in zip(runs, baseline)]) for k in paired_keys}
        targets = {
            "blocked_30pct_margin": estimate([r["blocked_machine_minutes"] - 0.7 * b["blocked_machine_minutes"] for r, b in zip(runs, baseline)]),
            "output_10pct_margin": estimate([r["completed"] - 1.1 * b["completed"] for r, b in zip(runs, baseline)]),
        }
        summaries.append({**meta, "config": current.to_dict(), "summary": stats, "paired": paired, "targets": targets})
        if progress:
            progress(meta, summaries[-1], len(summaries), len(scenarios))
    write_csv(output / "replications.csv", all_runs)
    write_csv(output / "summary.csv", ({"scenario": s["id"], "metric": k, **v} for s in summaries for k, v in s["summary"].items()))
    write_csv(output / "paired.csv", ({"scenario": s["id"], "metric": k, **v} for s in summaries for k, v in s["paired"].items()))
    manifest.update(status="complete", completed_at=datetime.now(timezone.utc).isoformat(), run_count=len(all_runs))
    save("results.json", {**manifest, "scenarios": summaries})
    save("manifest.json", manifest)
    return {**manifest, "scenarios": summaries}
