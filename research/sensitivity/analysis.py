"""Paired OAT estimates; parameter effects never count as strategy improvement."""
import math
import statistics
from scipy.stats import t

METRICS = {
    "operating_contribution": {"label": "经营贡献", "unit": "元 / 40 小时", "primary": True},
    "completed": {"label": "成品总数", "unit": "件"},
    "external": {"label": "线外待投料", "unit": "件"},
    "wip": {"label": "线内在制", "unit": "件"},
    "arrived": {"label": "到达物件", "unit": "件"},
    "failure_count": {"label": "故障次数", "unit": "次"},
    "repair_minutes": {"label": "机床维修时间合计", "unit": "机床分钟"},
    "blocked_minutes": {"label": "机床阻塞时间合计", "unit": "机床分钟"},
    "mean_cycle_time": {"label": "已完成件平均周期", "unit": "min（仅完成件）"},
    "revenue": {"label": "完工收入", "unit": "元"},
    "processing_cost": {"label": "加工费", "unit": "元"},
    "setup_cost": {"label": "换模费", "unit": "元"},
    **{f"P{i}_completed": {"label": f"P{i} 完工", "unit": "件"} for i in range(1, 5)},
}


def estimate(values, alpha=.05):
    if len(values) < 2 or any(v is None or not math.isfinite(v) for v in values):
        raise ValueError("A complete, finite paired sample is required")
    mean = statistics.mean(values)
    sd = statistics.stdev(values)
    se = sd / math.sqrt(len(values))
    half = float(t.ppf(1 - alpha / 2, len(values) - 1)) * se
    return {"n": len(values), "mean": mean, "sd": sd, "se": se, "ci": [mean - half, mean + half], "alpha": alpha}


def paired_effect(rows, baseline, primary_comparisons):
    if [r["replication"] for r in rows] != [r["replication"] for r in baseline]:
        raise ValueError("CRN pair IDs differ")
    result = {}
    for metric, info in METRICS.items():
        values = [r[metric] for r in rows]
        bases = [r[metric] for r in baseline]
        differences = [a - b for a, b in zip(values, bases)]
        alpha = .05 / primary_comparisons if info.get("primary") else .05
        delta = estimate(differences, alpha)
        delta["ci95"] = estimate(differences)["ci"]
        base_mean = statistics.mean(bases)
        # Ratio of means, not average per-replication percentages. No artificial
        # relative effect when the standard case is zero (notably P1/P2 delivery).
        relative = None
        if base_mean != 0:
            ratio = statistics.mean(differences) / base_mean
            influence = [(d - ratio * b) / base_mean for d, b in zip(differences, bases)]
            half = float(t.ppf(1 - alpha / 2, len(rows) - 1)) * statistics.stdev(influence) / math.sqrt(len(rows))
            relative = {"percent": ratio * 100, "ci_percent": [(ratio - half) * 100, (ratio + half) * 100],
                        "method": "paired delta-method ratio of means", "approximate": True}
        result[metric] = {"absolute": estimate(values), "baseline_mean": base_mean, "delta": delta, "relative": relative}
    return result


def elasticity(minus_rows, plus_rows, baseline, half_width=.05):
    """Relative G response per relative input, central ±5%; descriptive 95% CI."""
    g0 = [r["operating_contribution"] for r in baseline]
    mean0 = statistics.mean(g0)
    slope = [(p["operating_contribution"] - m["operating_contribution"]) / (2 * half_width)
             for m, p in zip(minus_rows, plus_rows)]
    value = statistics.mean(slope) / mean0
    influence = [(s - value * b) / mean0 for s, b in zip(slope, g0)]
    half = float(t.ppf(.975, len(g0) - 1)) * statistics.stdev(influence) / math.sqrt(len(g0))
    return {"estimate": value, "ci95": [value - half, value + half], "half_width": half_width,
            "method": "central finite difference; paired delta-method ratio; descriptive 95%", "approximate": True}


def summarize(protocol, rows):
    cells = {}
    for row in rows:
        cells.setdefault((row["policy"], row["scenario"]), []).append(row)
    for group in cells.values():
        group.sort(key=lambda r: r["replication"])
    result = {"policies": {}, "primary_comparisons": protocol["primary_comparisons"], "replications": protocol["replications"]}
    for policy in protocol["policies"]:
        standard = cells.get((policy, "standard"), [])
        if len(standard) != protocol["replications"]:
            continue
        item = {"baseline": {m: estimate([r[m] for r in standard]) for m in METRICS}, "scenarios": {}, "elasticities": {}}
        for scenario in protocol["scenarios"]:
            group = cells.get((policy, scenario["id"]), [])
            if len(group) == protocol["replications"]:
                item["scenarios"][scenario["id"]] = paired_effect(group, standard, protocol["primary_comparisons"])
        for factor in protocol["factors"]:
            minus, plus = cells.get((policy, factor + "_minus5"), []), cells.get((policy, factor + "_plus5"), [])
            if len(minus) == len(plus) == protocol["replications"]:
                item["elasticities"][factor] = elasticity(minus, plus, standard)
        result["policies"][policy] = item
    return result
