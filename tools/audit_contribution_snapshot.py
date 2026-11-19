"""Read-only audit of the committed campaign; --full also requires local private evidence.

Does not register policies, run simulations, change receipts, or spend new alpha.
"""
import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from scipy.stats import t

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/contribution_loop_20261022"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close(actual, expected):
    require(math.isclose(actual, expected, rel_tol=1e-11, abs_tol=1e-7),
            f"Numerical mismatch: {actual} != {expected}")


def check_stats(values, stored):
    n = len(values)
    require(stored["n"] == n, "Replication count differs")
    mean = statistics.mean(values)
    sd = statistics.stdev(values)
    half = float(t.ppf(.975, n - 1)) * sd / math.sqrt(n)
    for actual, expected in zip([mean, sd, mean - half, mean + half],
                                [stored["mean"], stored["sd"], *stored["ci95"]]):
        close(actual, expected)


def audit(full=False):
    state = read(OUT / "state.json")
    require(state["status"] == "completed" and state["sealed"], "Campaign is not sealed and complete")
    candidates = {c["id"]: c for c in state["candidates"]}
    require(len(candidates) == 26 and sum(not c["reference"] for c in candidates.values()) == 24,
            "Candidate budget differs")
    frozen = state["freeze"]["files"]
    for path, sha in frozen.items():
        require(digest(ROOT / path) == sha, f"Frozen source changed: {path}")
    require(hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest() == state["freeze"]["sha256"],
            "Evaluator digest differs")
    ready = read(OUT / "evaluator/ready_receipt.json")
    require(ready["ready"] and ready["evaluator_sha256"] == state["freeze"]["sha256"]
            and ready["seed_commitments"] == state["seed_commitments"], "Ready receipt differs")

    previous = "0" * 64
    events = []
    for line in (OUT / "evaluator/ledger/events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        payload = {k: v for k, v in event.items() if k != "sha256"}
        require(payload["previous_sha256"] == previous, "Broken event chain")
        previous = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                             separators=(",", ":")).encode()).hexdigest()
        require(previous == event["sha256"], "Event digest differs")
        events.append(event)
    require(previous == state["last_event_sha256"] and events == state["events"], "State and ledger differ")
    require(events[-1]["kind"] == "campaign_finished", "Events occurred after the campaign finished")

    manifest = read(OUT / "raw_manifest.json")
    raw = {item["path"]: item for item in manifest}
    require(len(raw) == len(manifest) == 1402, "Raw manifest contains missing/duplicate paths")
    with (OUT / "replications.csv").open(encoding="utf-8-sig", newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    tabular = {(r["candidate"], r["phase"], int(r["replication"])): r for r in csv_rows}
    require(len(tabular) == len(csv_rows) == 1402, "CSV contains missing/duplicate rows")
    counts = Counter()
    expected_raw = set()
    expected_csv = set()
    for cid, candidate in candidates.items():
        require(digest(ROOT / candidate["source"]) == candidate["bundle_sha256"], f"Candidate changed: {cid}")
        submission = read((ROOT / candidate["source"]).with_name("submission.json"))
        for field in ["parameters", "hypothesis", "parents", "bundle_sha256", "source"]:
            require(submission[field] == candidate[field], f"Submission differs: {cid}/{field}")
        for phase, stage in candidate["stages"].items():
            rows = stage["rows"]
            require(stage["status"] == "complete" and len(rows) == stage["expected_runs"], "Incomplete stage")
            receipt = read(OUT / f"evaluator/receipts/{phase}-{cid}.json")
            require(receipt == {"candidate": cid, "bundle_sha256": candidate["bundle_sha256"], "phase": phase, **stage},
                    f"Receipt differs: {phase}/{cid}")
            counts[phase] += len(rows)
            for i, row in enumerate(rows):
                require(row["valid"] and row["checks_passed"] and row["replication"] == i, "Invalid run")
                close(row["operating_contribution"], row["revenue"] - row["processing_cost"] - row["setup_cost"])
                for product in row["products"].values():
                    require(product["arrived"] == product["completed"] + product["external"] + product["wip"],
                            "Product conservation failed")
                path = f"evaluator/raw/{phase}/{cid}/{i:03d}.json.gz"
                expected_raw.add(path)
                require(raw[path]["sha256"] == row["raw_sha256"], f"Raw commitment differs: {path}")
                if full:
                    require((OUT / path).stat().st_size == raw[path]["bytes"] and digest(OUT / path) == raw[path]["sha256"],
                            f"Raw file differs: {path}")
                key = (cid, phase, i)
                expected_csv.add(key)
                for field, value in tabular[key].items():
                    if field in row and isinstance(row[field], (int, float)):
                        close(float(value), row[field])
                    elif field.endswith("_completed"):
                        close(float(value), row["products"][field.split("_")[0]]["completed"])
            for metric, summary in stage["summary"].items():
                if metric == "products":
                    for product, fields in summary.items():
                        for field, value in fields.items():
                            close(statistics.mean(r["products"][product][field] for r in rows), value)
                else:
                    check_stats([r[metric] for r in rows], summary)
            for ref, comparison in stage.get("paired", {}).items():
                reference = candidates[ref]["stages"][phase]["rows"]
                check_stats([a["operating_contribution"] - b["operating_contribution"]
                             for a, b in zip(rows, reference)], comparison)
    require(expected_raw == set(raw) and expected_csv == set(tabular), "Evidence coverage differs")
    require(dict(counts) == state["run_count"] == {"smoke": 72, "development": 780, "validation": 250, "confirmation": 300},
            "Run budgets differ")
    require(sum(e["kind"] == "replication_finished" for e in events) == 1402, "Ledger run count differs")

    prereg = read(OUT / "evaluator/confirmation_preregistration.json")
    winner = candidates[state["winner"]]
    require(prereg["winner"] == winner["id"] and prereg["source_sha256"] == winner["bundle_sha256"]
            and prereg["seed_commitment"] == state["seed_commitments"]["confirmation"], "Preregistration differs")
    require(set(prereg["comparisons"]) == set(state["final_comparisons"]) == {"fifo", "same_family"}, "Contrasts differ")
    require(prereg["n"] == 100 and prereg["alpha_campaign"] == .025 and prereg["alpha_per_comparison"] == .0125,
            "Formal test allocation differs")
    quantile = float(t.ppf(1 - prereg["alpha_per_comparison"], prereg["n"] - 1))
    close(quantile, prereg["quantile"])
    for ref, comparison in state["final_comparisons"].items():
        a = winner["stages"]["confirmation"]["rows"]
        b = candidates[ref]["stages"]["confirmation"]["rows"]
        differences = [x["operating_contribution"] - y["operating_contribution"] for x, y in zip(a, b)]
        check_stats(differences, comparison)
        close(comparison["alpha"], prereg["alpha_per_comparison"])
        close(statistics.mean(differences) - quantile * statistics.stdev(differences) / math.sqrt(len(differences)),
              comparison["formal_lower"])
        for field, value in comparison["decomposition"].items():
            close(statistics.mean(x[field] - y[field] for x, y in zip(a, b)), value)
        require(comparison["formal_lower"] > 0, "Gain was not independently confirmed")
    alpha = read(OUT / "evaluator/alpha_ledger.json")
    require(alpha["spent_on_confirmation"] and alpha["alpha_reserved"] == .025
            and not alpha["reset_after_rebaseline"], "Alpha ledger differs")
    if full:
        banks = read(OUT / "evaluator/private/seeds.json")
        require(set(banks) == {"validation", "confirmation"}, "Unexpected seed banks")
        for phase, bank in banks.items():
            require(len(bank) == len(set(bank)) == {"validation": 50, "confirmation": 100}[phase], "Seed count differs")
            require(not any(42 <= value <= 51 or 1000 <= value <= 1029 or 2000 <= value <= 6000 for value in bank),
                    "Public seed reused")
            require(hashlib.sha256(json.dumps(bank, separators=(",", ":")).encode()).hexdigest() == state["seed_commitments"][phase],
                    "Seed commitment differs")
        require(not set(banks["validation"]) & set(banks["confirmation"]), "Held-out banks overlap")
    return {"passed": True, "scope": "full-local" if full else "published-summary",
            "candidate_sources": len(candidates), "frozen_files": len(frozen), "statistical_rows": sum(counts.values()),
            "hash_chain_events": len(events), "raw_manifest_records": len(raw),
            "raw_files_checked": len(raw) if full else 0, "seed_banks_checked": full,
            "winner": state["winner"], "outcome": state["outcome"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="Require original local trajectories and hidden seed banks")
    args = parser.parse_args()
    print(json.dumps(audit(args.full), ensure_ascii=False, indent=2))
