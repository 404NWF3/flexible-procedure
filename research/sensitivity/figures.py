"""Export scientific figures from the same reviewed, completed summary."""
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/flexline-sensitivity-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/sensitivity_20261022"
TARGET = ROOT / "docs/sensitivity/figures"
protocol = json.loads((OUT / "protocol.json").read_text())
progress = json.loads((OUT / "progress.json").read_text())
summary = json.loads((OUT / "summary.json").read_text())
if progress["status"] != "completed":
    raise SystemExit("Figures require the fixed study endpoint")

font_path = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
if font_path.exists():
    font_manager.fontManager.addfont(str(font_path))
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font_path)).get_name()
plt.rcParams.update({"axes.unicode_minus": False, "font.size": 11, "svg.fonttype": "path",
                     "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#a6b3c3"})
colors = {"fifo": "#2865ad", "same_family": "#b47d28", "c20_hybrid": "#76559b"}
markers = {"fifo": "o", "same_family": "s", "c20_hybrid": "^"}
fig, axes = plt.subplots(2, 2, figsize=(12, 9), sharex=True, sharey=True)
handles = []
for ax, (factor, details) in zip(axes.flat, protocol["factors"].items()):
    scenarios = sorted([s for s in protocol["scenarios"] if s["factor"] == factor or s["id"] == "standard"], key=lambda s: s["delta"])
    for policy, label in protocol["policies"].items():
        records = [summary["policies"][policy]["scenarios"][s["id"]]["operating_contribution"]["delta"] for s in scenarios]
        x = [s["delta"] * 100 for s in scenarios]
        y = [r["mean"] for r in records]
        low, high = [r["ci"][0] for r in records], [r["ci"][1] for r in records]
        line, = ax.plot(x, y, color=colors[policy], marker=markers[policy], markersize=5, linewidth=1.5, label=label)
        ax.errorbar(x, y, yerr=[[v - lo for v, lo in zip(y, low)], [hi - v for v, hi in zip(y, high)]],
                    color=colors[policy], linewidth=1, capsize=3, fmt="none", alpha=.85)
        if len(handles) < 3:
            handles.append(line)
    ax.axhline(0, color="#718198", linewidth=1, linestyle="--")
    ax.set_title(details["label"], loc="left", fontweight="bold", fontsize=13, pad=12)
    ax.set_xticks([-5, -2, 0, 2, 5], ["−5%", "−2%", "0", "+2%", "+5%"])
    ax.set_xlim(-5.5, 5.5)
    ax.grid(axis="y", color="#e4e9f0", linewidth=.6)
    ax.set_axisbelow(True)
for ax in axes[:, 0]:
    ax.set_ylabel("相对自身标准情景的经营贡献变化 / 元")
for ax in axes[-1]:
    ax.set_xlabel("单一物理参数相对变化")
fig.suptitle("固定策略下的参数灵敏度 · 独立实验 SA-01", x=.07, ha="left", fontsize=17, fontweight="bold")
fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(.5, .94), ncols=3, frameon=False)
fig.text(.07, .035, "每情景 n=200，共同随机数配对；误差线为 48 项比较的 Bonferroni 双侧区间，整体 α=0.05。\n空系统起步 40 小时；只改一个参数；不重新优化策略，不计入上一轮系统提升。", fontsize=10, color="#526174")
fig.subplots_adjust(top=.84, bottom=.15, left=.10, right=.97, hspace=.30, wspace=.16)
TARGET.mkdir(parents=True, exist_ok=True)
for extension in ("svg", "png", "pdf"):
    path = TARGET / f"contribution-sensitivity.{extension}"
    fig.savefig(path, dpi=180, facecolor="white", metadata={"Creator": "Flexline sensitivity analysis"})
    if extension == "svg":
        path.write_text("\n".join(line.rstrip() for line in path.read_text().splitlines()) + "\n")
plt.close(fig)
print(str(TARGET))
