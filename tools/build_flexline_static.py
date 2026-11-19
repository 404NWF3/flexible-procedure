"""Package existing results as two self-contained pages; never run simulations.

Uses only the Python standard library. Run from any working directory.
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "outputs/contribution_loop_20261022"
SOURCE = ROOT / "research/site"
DESTINATION = ROOT / "docs/flexline"


def script_json(value):
    # JSON is placed in an HTML script element, including user-authored hypotheses.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")


def pages():
    state = json.loads((RECORDS / "state.json").read_text(encoding="utf-8"))
    if state["status"] != "completed":
        raise ValueError("The repository snapshot must represent a completed campaign")
    files = {
        "loop_contract.json": "loop_contract.json",
        "ready_receipt.json": "evaluator/ready_receipt.json",
        "agent_prompt.txt": "agent_prompt.txt",
        "replications.csv": "replications.csv",
        "raw_manifest.json": "raw_manifest.json",
        "verification.json": "verification.json",
    }
    downloads = {name: (RECORDS / path).read_bytes().decode("utf-8") for name, path in files.items()}
    page = (SOURCE / "index.template.html").read_text(encoding="utf-8")
    page = page.replace('<link rel="stylesheet" href="styles.css">',
                        "<style>" + (SOURCE / "styles.css").read_text(encoding="utf-8") + "</style>")
    page = page.replace('<script src="progress.js"></script><script src="app.js"></script>',
                        "<script>window.INITIAL_PROGRESS=" + script_json(state) + ";\n"
                        "window.FLEXLINE_DOWNLOADS=" + script_json(downloads) + ";</script>\n"
                        "<script>" + (SOURCE / "app.js").read_text(encoding="utf-8") + "</script>")

    # Export the existing five-scenario workbench without its optional local API.
    web = ROOT / "src/soft_procedure/web"
    suite = json.loads((ROOT / "outputs/results.json").read_text(encoding="utf-8"))
    script = (web / "app.js").read_text(encoding="utf-8")
    health_line = next(line for line in script.splitlines() if "fetch('/api/health')" in line)
    script = script.replace(health_line + "\n  else $('mode-badge').textContent='离线结果快照';",
                            "  $('mode-badge').textContent='本地静态快照';")
    # Remove the unreachable POST implementation too: this deliverable has no API calls.
    begin = script.index("  async function run(")
    end = script.index("\n  function download(", begin)
    script = script[:begin] + """  function run(event) {
    event.preventDefault();
    $('form-error').textContent='此页展示已完成实验。重新计算请启动本地 SimPy 服务。';
    $('form-error').hidden=false;
  }
""" + script[end:]
    config_action = "$('config-button').addEventListener('click',()=>{populateForm();$('config-dialog').showModal();});"
    if script.count(config_action) != 1 or "fetch(" in script:
        raise ValueError("Workbench template changed; review the static export adapter")
    script = script.replace(config_action, """$('config-button').addEventListener('click',()=>{
    populateForm();
    document.querySelectorAll('#config-form input,#config-form select').forEach(el=>el.disabled=true);
    $('reset-config').hidden=true;$('run-button').hidden=true;
    $('config-dialog').showModal();
  });""")
    baseline = (web / "index.html").read_text(encoding="utf-8")
    baseline = baseline.replace("__STYLES__", (web / "styles.css").read_text(encoding="utf-8"))
    baseline = baseline.replace("__SCRIPT__", script).replace("__SIMULATION_DATA__", script_json(suite))
    baseline = baseline.replace('<span id="mode-badge"', '<a href="index.html">实验搜索树 ↗</a><span id="mode-badge"')
    baseline = baseline.replace("⚙</span> 配置与运行", "⚙</span> 查看配置")
    baseline = baseline.replace("<h2>配置下一次实验</h2>", "<h2>查看本次实验配置</h2>")
    return {"index.html": page, "baseline.html": baseline}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the committed HTML is out of date")
    args = parser.parse_args()
    for name, content in pages().items():
        path = DESTINATION / name
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                raise SystemExit(f"Stale static page: {path}; run {Path(__file__).name}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        print(f"{'Verified' if args.check else 'Wrote'} {path.relative_to(ROOT)} ({len(content.encode('utf-8')):,} bytes)")


if __name__ == "__main__":
    main()
