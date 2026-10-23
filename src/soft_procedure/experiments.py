"""同种子配对实验：只改配置，复用同一模型。"""
from dataclasses import replace
from datetime import datetime, timezone
from math import sqrt
from statistics import mean, stdev

from .config import ASSUMPTIONS, OPERATING_COST_BASES, PRODUCT_MIX, ROUTES, SimulationConfig
from .economics import investment_comparison
from .model.simulation import run_simulation
from .model.source import arrival_schedule

SCENARIOS = {
    "baseline": ("基准方案", "原始配置与当前基准调度规则"),
    "m4_extra": ("M4 增加机床", "仅在 M4 增加 1 台机床"),
    "same_family": ("同类优先", "优先加工与本机当前模具相同的产品"),
    "no_setup": ("消除换模", "换模时间设为 0 的理想对照"),
    "no_failure": ("无故障", "关闭设备故障的理想对照"),
}

CORE_SCENARIOS = {
    "baseline": SCENARIOS["baseline"],
    "m4_extra": SCENARIOS["m4_extra"],
    "same_family": SCENARIOS["same_family"],
    "same_family_m4_extra": ("同类优先 + M4 增机", "同类优先并在 M4 增加 1 台机床"),
}
SCENARIO_DEFINITIONS = {**SCENARIOS, "same_family_m4_extra": CORE_SCENARIOS["same_family_m4_extra"]}

# 双侧 95% Student-t 临界值，df=1…29；实验入口限制为至多 30 次。
T975 = (0, 12.706205, 4.302653, 3.182446, 2.776445, 2.570582, 2.446912,
        2.364624, 2.306004, 2.262157, 2.228139, 2.200985, 2.178813,
        2.160369, 2.144787, 2.131450, 2.119905, 2.109816, 2.100922,
        2.093024, 2.085963, 2.079614, 2.073873, 2.068658, 2.063899,
        2.059539, 2.055529, 2.051831, 2.048407, 2.045230)


def estimate(values):
    observed = [v for v in values if v is not None]
    n = len(observed)
    if not observed:
        return {"mean": None, "sd": None, "ci95": None, "n": 0}
    sd = stdev(observed) if n > 1 else None
    return {"mean": mean(observed), "sd": sd, "ci95": T975[n - 1] * sd / sqrt(n) if n > 1 else None, "n": n}


def scenario_config(base, name):
    if name not in SCENARIO_DEFINITIONS:
        raise ValueError(f"未知方案：{name}")
    changes = {
        "baseline": {}, "m4_extra": {"machine_counts": {**base.machine_counts, "M4": base.machine_counts["M4"] + 1}},
        "same_family": {"policy_name": "same_family"}, "no_setup": {"setup_time": 0.0},
        "no_failure": {"failures_enabled": False},
        "same_family_m4_extra": {
            "policy_name": "same_family",
            "machine_counts": {**base.machine_counts, "M4": base.machine_counts["M4"] + 1},
        },
    }
    return replace(base, **changes[name]).validate()


def run_experiments(config=None, replications=10, seed=42, progress=None, scenario_ids=None):
    base = (config or SimulationConfig()).validate()
    if type(replications) is not int or not 1 <= replications <= 30:
        raise ValueError("重复次数必须为 1–30 的整数")
    if type(seed) is not int:
        raise ValueError("seed 必须为整数")
    seeds = [seed + i for i in range(replications)]
    schedules = {s: arrival_schedule(base, s) for s in seeds}
    selected = tuple(scenario_ids or SCENARIOS)
    unknown = set(selected) - set(SCENARIO_DEFINITIONS)
    if unknown:
        raise ValueError(f"未知方案：{', '.join(sorted(unknown))}")
    suite = {
        "schema_version": 2, "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "SimPy", "base_config": base.to_dict(), "replications": replications,
        "seeds": seeds, "assumptions": ASSUMPTIONS,
        "routes": ROUTES, "product_mix": PRODUCT_MIX,
        "operating_cost_bases": OPERATING_COST_BASES,
        "scenario_set": "core" if set(selected) == set(CORE_SCENARIOS) else "custom",
        "scenario_ids": list(selected),
        "source": {"document": "案例二十二.docx",
                   "description": "原始案例参数与项目参数契约；所有图表为 SimPy 实际运行结果"},
        "scenarios": [],
    }
    for name in selected:
        label, description = SCENARIO_DEFINITIONS[name]
        current = scenario_config(base, name)
        runs, representative, sample_rows, station_rows, product_rows = [], None, [], [], []
        for i, current_seed in enumerate(seeds):
            result = run_simulation(current, current_seed, schedule=schedules[current_seed])
            if i == 0:
                representative = result
            runs.append({"seed": current_seed, **result["summary"]})
            sample_rows.append(result["samples"])
            station_rows.append(result["stations"])
            product_rows.append(result["products"])
            if progress:
                progress(name, i + 1, replications)
        summary = {key: estimate([row[key] for row in runs]) for key in result["summary"]}
        stations = []
        for j, station in enumerate(representative["stations"]):
            stations.append({
                "name": station["name"], "machine_count": station["machine_count"],
                "states": {state: mean(rows[j]["states"][state] for rows in station_rows) for state in station["states"]},
                **{metric: estimate([rows[j][metric] for rows in station_rows]) for metric in
                   ("mean_queue", "mean_wait", "waiting_at_end", "censored_wait_mean", "setup_count", "failure_count")},
                "max_queue": max(rows[j]["max_queue"] for rows in station_rows),
            })
        samples = [{"time": sample["time"], **{key: mean(rows[j][key] for rows in sample_rows)
                    for key in ("arrived", "completed", "external", "wip", "sales_revenue", "operating_cost", "operating_contribution")}}
                   for j, sample in enumerate(representative["samples"])]
        products = {p: estimate([row[p]["completed"] for row in product_rows]) for p in PRODUCT_MIX}
        product_revenues = {p: estimate([row[p]["sales_revenue"] for row in product_rows]) for p in PRODUCT_MIX}
        suite["scenarios"].append({"id": name, "name": label, "description": description,
            "config": current.to_dict(), "stations": stations, "summary": summary,
            "products": products, "product_revenues": product_revenues,
            "samples": samples, "runs": runs, "representative": representative})
    scenario_by_id = {scenario["id"]: scenario for scenario in suite["scenarios"]}
    reference_id = "baseline" if "baseline" in scenario_by_id else selected[0]
    pairing = {name: reference_id for name in selected}
    pairing[reference_id] = None
    if "same_family_m4_extra" in pairing and "same_family" in pairing:
        pairing["same_family_m4_extra"] = "same_family"
    for scenario in suite["scenarios"]:
        parent_id = pairing[scenario["id"]]
        parent = scenario_by_id[parent_id] if parent_id else scenario
        paired = estimate([a["completed"] - b["completed"] for a, b in zip(scenario["runs"], parent["runs"])])
        paired_contribution = estimate([a["operating_contribution"] - b["operating_contribution"]
                                        for a, b in zip(scenario["runs"], parent["runs"])])
        base_output = parent["summary"]["completed"]["mean"]
        scenario["paired_output_difference"] = paired
        scenario["paired_contribution_difference"] = paired_contribution
        scenario["paired_to"] = parent_id or scenario["id"]
        scenario["output_change_pct"] = 100 * paired["mean"] / base_output if base_output else None
        scenario["investment"] = investment_comparison(
            SimulationConfig.from_dict(scenario["config"]), base, scenario["paired_contribution_difference"])
    return suite


def run_core_experiments(config=None, replications=10, seed=42, progress=None):
    """运行新版任务书规定的 FIFO/同类优先 × M4 配置四方案。"""
    return run_experiments(config, replications, seed, progress, scenario_ids=tuple(CORE_SCENARIOS))


def public_suite(suite):
    """面板保留第一轮回放；完整工件/队列明细单独保存 CSV。"""
    return {**suite, "scenarios": [{**s, "representative": {k: v for k, v in s["representative"].items()
             if k not in ("jobs", "queue_logs")}} for s in suite["scenarios"]]}
