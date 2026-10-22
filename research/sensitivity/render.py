"""Build the separate local static sensitivity page from completed records only."""
import argparse
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "outputs/sensitivity_20261022"
TARGET = ROOT / "docs/sensitivity/index.html"


def render(check=False):
    # Importing the metric vocabulary does not run simulations or select policies.
    from analysis import METRICS
    protocol = json.loads((OUT / "protocol.json").read_text())
    progress = json.loads((OUT / "progress.json").read_text())
    summary_path = OUT / "summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {"policies": {}}
    downloads = {name: (OUT / name).read_bytes().decode("utf-8")
                 for name in ("protocol.json", "summary.json", "replications.csv", "raw_manifest.json") if (OUT / name).exists()}
    data = {"protocol": protocol, "progress": progress, "summary": summary, "metrics": METRICS, "downloads": downloads}
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    page = (HERE / "index.template.html").read_text().replace("__STYLES__", (HERE / "styles.css").read_text())
    page = page.replace("__DATA__", encoded).replace("__SCRIPT__", (HERE / "app.js").read_text())
    figures = TARGET.parent / "figures"
    links = ""
    if progress["status"] == "completed" and all((figures / ("contribution-sensitivity." + suffix)).exists() for suffix in ("svg", "png", "pdf")):
        links = '<section class="panel"><h2>科研图导出</h2><p>四参数 × 三固定策略；直接由最终统计绘制，含统一校正的配对区间。</p><div class="downloads">' + " · ".join(
            f'<a href="figures/contribution-sensitivity.{suffix}" download>下载 {suffix.upper()}</a>' for suffix in ("svg", "png", "pdf")) + '</div></section>'
    page = page.replace("__FIGURE_LINKS__", links)
    if check:
        if not TARGET.exists() or TARGET.read_text() != page:
            raise ValueError("Static sensitivity page is stale")
    else:
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=TARGET.parent, suffix=".tmp", delete=False) as stream:
            stream.write(page)
            temporary = Path(stream.name)
        temporary.replace(TARGET)
    print(f"{'Verified' if check else 'Wrote'} {TARGET.relative_to(ROOT)} ({len(page.encode()):,} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    render(args.check)
