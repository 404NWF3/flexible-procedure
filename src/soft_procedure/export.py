"""所有导出来自同一组计算结果。HTML 内嵌 CSS、JS 与数据，可直接打开。"""
import csv
import json
from importlib.resources import files
from pathlib import Path

from .experiments import public_suite


def write_csv(path, rows, fields=None):
    rows = list(rows)
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields or (list(rows[0]) if rows else []))
        writer.writeheader()
        writer.writerows(rows)


def render_dashboard(suite):
    web = files("soft_procedure").joinpath("web")
    data = json.dumps(public_suite(suite), ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    return web.joinpath("index.html").read_text().replace("__STYLES__", web.joinpath("styles.css").read_text()).replace(
        "__SCRIPT__", web.joinpath("app.js").read_text()).replace("__SIMULATION_DATA__", data)


def write_run(result, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    write_csv(directory / "jobs.csv", ({k: v for k, v in j.items() if k != "operations"} for j in result["jobs"]))
    write_csv(directory / "operations.csv", (
        {"job_id": j["job_id"], "product": j["product"], **op} for j in result["jobs"] for op in j["operations"]),
        ["job_id", "product", "station", "operation_index", "queue_entered_at", "start", "processing_start", "processed_at", "transferred_at", "machine", "required_processing"])
    write_csv(directory / "machine_states.csv", (
        {"machine": m["name"], **row} for m in result["machines"] for row in m["intervals"]))
    write_csv(directory / "queues.csv", (
        {"station": n, **row} for n, rows in result["queue_logs"].items() for row in rows))


def write_experiments(suite, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "results.json").write_text(json.dumps(public_suite(suite), ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    (directory / "dashboard.html").write_text(render_dashboard(suite))
    write_csv(directory / "replications.csv", ({"scenario": s["id"], **row} for s in suite["scenarios"] for row in s["runs"]))
    write_csv(directory / "summary.csv", ({"scenario": s["id"], "metric": key, **value}
               for s in suite["scenarios"] for key, value in s["summary"].items()))
    for scenario in suite["scenarios"]:
        if "jobs" in scenario["representative"]:
            write_run(scenario["representative"], directory / "representative" / scenario["id"])
    return directory / "dashboard.html"
