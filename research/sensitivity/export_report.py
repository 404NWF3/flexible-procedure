"""Export exact comparison tables and a separate sensitivity readout."""
import csv
import json
from pathlib import Path

from analysis import METRICS

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/sensitivity_20261022"


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run():
    protocol, progress, summary = [json.loads((OUT / (name + ".json")).read_text()) for name in ("protocol", "progress", "summary")]
    if progress["status"] != "completed":
        raise ValueError("A final readout requires all fixed-budget runs")
    effects, elasticities = [], []
    for policy, own in summary["policies"].items():
        for scenario in protocol["scenarios"]:
            if scenario["factor"] is None:
                continue
            for metric, entry in own["scenarios"][scenario["id"]].items():
                effects.append({"study_id": protocol["study_id"], "policy": policy, "scenario": scenario["id"],
                                "factor": scenario["factor"], "input_relative_change": scenario["delta"], "metric": metric,
                                "unit": METRICS[metric]["unit"], "n": entry["delta"]["n"], "baseline_mean": entry["baseline_mean"],
                                "scenario_mean": entry["absolute"]["mean"], "paired_change": entry["delta"]["mean"],
                                "ci_low": entry["delta"]["ci"][0], "ci_high": entry["delta"]["ci"][1],
                                "interval_scope": "Bonferroni 48 comparisons, family alpha=0.05" if METRICS[metric].get("primary") else "descriptive paired 95%",
                                "relative_change_percent": entry["relative"]["percent"] if entry["relative"] else None})
        for factor, entry in own["elasticities"].items():
            elasticities.append({"policy": policy, "factor": factor, "elasticity": entry["estimate"],
                                 "descriptive_ci95_low": entry["ci95"][0], "descriptive_ci95_high": entry["ci95"][1], "method": entry["method"]})
    write_csv(OUT / "effects.csv", effects)
    write_csv(OUT / "elasticities.csv", elasticities)

    def number(value):
        return f"{value:,.2f}"

    def signed(value):
        return f"{value:+,.2f}"

    def percent(value):
        return f"{value:+.3f}" if 0 < abs(value) < .01 else f"{value:+.2f}"

    def cell(policy, factor):
        result = summary["policies"][policy]["scenarios"][factor + "_plus5"]["operating_contribution"]
        delta = result["delta"]
        return f"{signed(delta['mean'])}（{percent(result['relative']['percent'])}%）; [{signed(delta['ci'][0])}, {signed(delta['ci'][1])}]"

    lines = ["# SA-01 独立参数灵敏度实验结果", "",
             "本轮固定原始 FIFO、同类优先与 c20 策略，只改变一个物理参数。下面的变化全部相对于各策略自身、本轮新样本的标准参数结果；不能加到上一轮策略优化的提升成绩中。", "",
             "已按预注册完成 51 个策略×情景单元，每单元 200 次，共 10,200 次；四个物理参数分别取 −5%、−2%、+2%、+5%，没有按结果追加样本或重新选策略。", "",
             "## 本轮标准参数结果", "",
             "| 固定策略 | 经营贡献 / 元每40小时 | 成品 / 件 | 线外待投料 / 件 | 故障 / 次 | P1 / P2 完工 / 件 |",
             "|---|---:|---:|---:|---:|---:|"]
    for policy, label in protocol["policies"].items():
        base = summary["policies"][policy]["baseline"]
        values = [number(base[k]["mean"]) for k in ("operating_contribution", "completed", "external", "failure_count")]
        lines.append(f"| {label} | " + " | ".join(values) + f" | {number(base['P1_completed']['mean'])} / {number(base['P2_completed']['mean'])} |")
    lines += ["", "## 参数增加 5% 的配对经营贡献变化", "",
              "每格依次为增量（元）、相对自身标准情景的百分比、主要配对区间。区间对全部 48 个非零参数对比作 Bonferroni 校正，整体 α=0.05；不是只对这里摘出的 12 项校正。负向与 ±2% 的全部结果保存在页面和 `effects.csv`。", "",
              "| 物理参数 +5% | 原始 FIFO | 同类优先 | 固定 c20 |", "|---|---|---|---|"]
    for factor, info in protocol["factors"].items():
        lines.append("| " + info["label"] + " | " + " | ".join(cell(policy, factor) for policy in protocol["policies"]) + " |")
    lines += ["", "## 局部弹性", "",
              "中央 ±5% 差分的点估计。参数改变 1% 时，经营贡献相对变化约为下表数字的百分比；只在当前邻域作为局部近似，不能外推为大幅参数改变的收益。描述性 95% 区间见网页和 `elasticities.csv`。", "",
              "| 物理参数 | 原始 FIFO | 同类优先 | 固定 c20 |", "|---|---:|---:|---:|"]
    for factor, info in protocol["factors"].items():
        lines.append("| " + info["label"] + " | " + " | ".join(signed(summary["policies"][p]["elasticities"][factor]["estimate"]) for p in protocol["policies"]) + " |")
    largest = {p: max(own["elasticities"], key=lambda f: abs(own["elasticities"][f]["estimate"])) for p, own in summary["policies"].items()}
    lines += ["", "## 解读与限制", ""]
    if len(set(largest.values())) == 1:
        factor = next(iter(largest.values()))
        lines.append(f"在这四个参数的局部弹性点估计中，三个固定策略的绝对值最大项均为**{protocol['factors'][factor]['label']}**。这描述固定系统对参数偏差的响应，不是选择可改变物理参数来提高上一轮成绩。")
    for factor in protocol["factors"]:
        directions = []
        for policy, label in protocol["policies"].items():
            lo, hi = summary["policies"][policy]["scenarios"][factor + "_plus5"]["operating_contribution"]["delta"]["ci"]
            directions.append(label + ("：区间全为正" if lo > 0 else "：区间全为负" if hi < 0 else "：区间跨零，方向未确定"))
        lines += ["", f"{protocol['factors'][factor]['label']}增加 5%：" + "；".join(directions) + "。"]
    lines += ["", "到达速率改变时，外部到达仍持续，不能用限制来料掩盖积压。加工速度变化同时影响真实加工耗时及按有效时间计费的加工费。MTBF 使用有效加工/换模时间，MTTR 使用维修时长，不应把 MTBF 当作日历时长。", "",
              "故障在 40 小时窗口中较少；即使均值有方向，较宽或跨零的区间仍可能表示精度不足。完成周期只统计完成件，且本研究未施加分产品保供约束。没有研究参数交互、工位分别变速、长期稳态或改变参数的实施成本。", "",
              "## 证据与分离", "",
              "- 独立协议：`protocol.json`；完整公开逐轮记录：`runs.jsonl` / `replications.csv`。",
              "- 全部配对结果：`summary.json` / `effects.csv`；局部弹性：`elasticities.csv`。",
              "- 预检：7 项通过，15 组完整轨迹及动作摘要与原隔离执行器一致。",
              "- 旧归档由 `prior_archive_files` 摘要逐项保护；旧候选树、策略源代码、实验结果和 α 账本均不修改。",
              "- 原始轨迹与新种子库仅在 `private/` 本地保存；公开 `raw_manifest.json` 只提供路径、大小和 SHA-256。",
              "- 页面：`docs/sensitivity/index.html`；科研图：`docs/sensitivity/figures/`。", ""]
    (OUT / "report.md").write_text("\n".join(lines))
    print(json.dumps({"effect_rows": len(effects), "elasticity_rows": len(elasticities), "report": str(OUT / "report.md")}, ensure_ascii=False))


if __name__ == "__main__":
    run()
