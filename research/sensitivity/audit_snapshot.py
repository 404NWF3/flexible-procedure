"""Read-only public-statistics audit, optionally checking all local raw hashes."""
import argparse
import csv
import gzip
import hashlib
import json
import math
import statistics
from collections import Counter

from scipy.stats import t
from model import ROOT, FACTORS, POLICIES, configuration, sha
from analysis import METRICS, summarize

OUT = ROOT / "outputs/sensitivity_20261022"


def read(path):
    return json.loads(path.read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(a, b):
    require(math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-7), f"Numbers differ: {a} != {b}")


def audit(full=False):
    protocol, progress, summary = (read(OUT / (name + ".json")) for name in ("protocol", "progress", "summary"))
    require(progress["status"] == "completed", "Study has not reached its fixed endpoint")
    require(protocol["not_optimization"] and protocol["study_type"] == "fixed-policy-physical-parameter-sensitivity", "Study identity differs")
    require(sha(OUT / "protocol.json") == progress["protocol_sha256"], "Preregistered protocol changed")
    require(protocol["primary_comparisons"] == 48 and protocol["replications"] == 200 and len(protocol["scenarios"]) == 17, "Design differs")
    for group in ("frozen_files", "prior_archive_files"):
        for path, expected in protocol[group].items():
            require(sha(ROOT / path) == expected, "Frozen archive changed: " + path)
    for scenario in protocol["scenarios"]:
        config, speed = configuration(scenario)
        require(config.to_dict() == scenario["configuration"] and speed == scenario["physical_processing_speed"], "Physical scenario differs")
    rows = [json.loads(line) for line in (OUT / "runs.jsonl").read_text().splitlines()]
    indexed = {(r["policy"], r["scenario"], r["replication"]): r for r in rows}
    expected = {(policy, scenario["id"], i) for policy in POLICIES for scenario in protocol["scenarios"] for i in range(200)}
    require(set(indexed) == expected and len(rows) == len(indexed) == progress["completed_runs"] == 10200, "Missing, duplicate or extra run")
    require(len(progress["completed_cells"]) == len({(c["policy"], c["scenario"]) for c in progress["completed_cells"]}) == 51, "Incomplete scenario matrix")
    previous, ledger_runs = "0" * 64, set()
    events = [json.loads(line) for line in (OUT / "events.jsonl").read_text().splitlines()]
    for event in events:
        payload = {k: v for k, v in event.items() if k != "sha256"}
        require(event["previous_sha256"] == previous, "Broken event chain")
        previous = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        require(previous == event["sha256"], "Event hash differs")
        if event["kind"] == "replication_finished":
            key = (event["policy"], event["scenario"], event["replication"])
            require(key not in ledger_runs and event["raw_sha256"] == indexed[key]["raw_sha256"], "Ledger run differs")
            ledger_runs.add(key)
    require(previous == progress["last_event_sha256"] and ledger_runs == expected, "Ledger does not cover every run")
    require(events[-1]["kind"] == "study_completed", "Events occurred after the endpoint")
    require(events[0]["at"] >= protocol["registered_at"] and events[0]["kind"] == "study_started", "Registration chronology differs")
    manifest_list = read(OUT / "raw_manifest.json")
    manifest = {r["path"]: r for r in manifest_list}
    require(len(manifest) == len(manifest_list) == 10200, "Raw manifest coverage differs")
    with (OUT / "replications.csv").open(encoding="utf-8-sig", newline="") as stream:
        records = list(csv.DictReader(stream))
    require(len(records) == 10200, "CSV row count differs")
    csv_keys = set()
    for entry in records:
        key = (entry["policy"], entry["scenario"], int(entry["replication"]))
        require(key not in csv_keys, "Duplicate CSV row")
        csv_keys.add(key)
        row = indexed[key]
        for metric in METRICS:
            close(float(entry[metric]), row[metric])
        require(entry["raw_sha256"] == row["raw_sha256"] and entry["action_trace_sha256"] == row["action_trace_sha256"], "CSV hash differs")
    require(csv_keys == expected, "CSV coverage differs")
    bank = read(OUT / "private/seeds.json") if full else None
    if full:
        require(len(bank) == len(set(bank)) == 200, "Seed bank size/uniqueness differs")
        require(hashlib.sha256(json.dumps(bank, separators=(",", ":")).encode()).hexdigest() == protocol["seed_commitment"], "Seed commitment differs")
    sampled_raw = 0
    for row in rows:
        close(row["operating_contribution"], row["revenue"] - row["processing_cost"] - row["setup_cost"])
        require(row["arrived"] == row["completed"] + row["external"] + row["wip"], "Population conservation failed")
        for product, values in row["products"].items():
            require(values["arrived"] == values["completed"] + values["external"] + values["wip"], "Product conservation failed")
            close(row[product + "_completed"], values["completed"])
        raw = manifest[row["raw_path"]]
        require(raw["sha256"] == row["raw_sha256"] and raw["bytes"] == row["raw_bytes"], "Raw commitment differs")
        if full:
            path = OUT / row["raw_path"]
            require(path.stat().st_size == raw["bytes"] and sha(path) == raw["sha256"], "Local raw file differs")
            # First and last replication of every cell independently inspect
            # raw seed/configuration/metrics; all 10,200 file hashes are checked.
            if row["replication"] in (0, 199):
                with gzip.open(path, "rt") as stream:
                    result = json.load(stream)
                scenario = next(s for s in protocol["scenarios"] if s["id"] == row["scenario"])
                require(result["seed"] == bank[row["replication"]] and result["config"] == scenario["configuration"], "Sampled seed/configuration differs")
                require(result["sensitivity"]["scenario"] == scenario and result["sensitivity"]["policy"] == row["policy"], "Sampled sensitivity metadata differs")
                close(result["summary"]["operating_contribution"], row["operating_contribution"])
                sampled_raw += 1
    require(summarize(protocol, rows) == summary, "Saved statistics do not reproduce from the published rows")
    # Independent check of primary standard errors using covariance, rather than
    # taking the standard deviation of the already paired differences.
    primary_checked = 0
    for policy in POLICIES:
        base = [indexed[(policy, "standard", i)]["operating_contribution"] for i in range(200)]
        for scenario in protocol["scenarios"]:
            if scenario["id"] == "standard":
                continue
            values = [indexed[(policy, scenario["id"], i)]["operating_contribution"] for i in range(200)]
            var_difference = statistics.variance(values) + statistics.variance(base) - 2 * statistics.covariance(values, base)
            se = math.sqrt(max(0, var_difference) / 200)
            mean = statistics.mean(values) - statistics.mean(base)
            delta = summary["policies"][policy]["scenarios"][scenario["id"]]["operating_contribution"]["delta"]
            half = float(t.ppf(1 - .05 / (2 * 48), 199)) * se
            close(delta["mean"], mean)
            close(delta["ci"][0], mean - half)
            close(delta["ci"][1], mean + half)
            primary_checked += 1
    return {"passed": True, "study_id": protocol["study_id"], "scope": "full-local" if full else "published-statistics",
            "runs": len(rows), "scenario_policy_cells": 51, "primary_paired_intervals": primary_checked,
            "hash_chain_events": len(events), "frozen_study_files": len(protocol["frozen_files"]),
            "prior_archive_files_unchanged": len(protocol["prior_archive_files"]), "raw_hashes_verified": len(rows) if full else 0,
            "raw_seed_configuration_samples": sampled_raw, "seed_commitment_verified": full,
            "no_new_candidate_search": True, "original_optimization_archive_unchanged": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    print(json.dumps(audit(args.full), ensure_ascii=False, indent=2))
