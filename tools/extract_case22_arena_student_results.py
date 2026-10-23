"""Extract a compact, auditable summary from an Arena SQLite report database."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--evidence-path", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    reps = conn.execute(
        "SELECT ID, ReplicationNumber FROM Rep ORDER BY ReplicationNumber"
    ).fetchall()
    definitions = {
        row["ID"]: row["Name"]
        for row in conn.execute("SELECT ID, Name FROM Definition")
    }
    output_rows = conn.execute(
        "SELECT DefinitionID, ReplicationID, Value FROM Output ORDER BY ReplicationID, DefinitionID"
    ).fetchall()
    count_rows = conn.execute(
        "SELECT DefinitionID, ReplicationID, Count FROM Count ORDER BY ReplicationID, DefinitionID"
    ).fetchall()
    stat_rows = conn.execute(
        "SELECT DefinitionID, ReplicationID, AvgObs, MaxObs, LastValue, NumObs "
        "FROM Statistic ORDER BY ReplicationID, DefinitionID"
    ).fetchall()
    conn.close()

    rep_number_by_id = {row["ID"]: row["ReplicationNumber"] for row in reps}
    rows: list[dict[str, object]] = []

    def add(replication: int, metric: str, value: object, unit: str, notes: str = "") -> None:
        rows.append(
            {
                "experiment_id": args.experiment,
                "metric": metric,
                "actual_value": value,
                "unit": unit,
                "replication": replication,
                "model_version": args.model_version,
                "evidence_path": args.evidence_path,
                "status": "observed",
                "notes": notes,
            }
        )

    for row in output_rows:
        name = definitions.get(row["DefinitionID"], "")
        rep = rep_number_by_id.get(row["ReplicationID"], row["ReplicationID"])
        metric_map = {
            "Entity 1.NumberIn": ("arrived_entities", "items"),
            "Entity 1.NumberOut": ("entity_number_out", "entities"),
            "System.NumberOut": ("system_number_out", "entities"),
        }
        mapped = metric_map.get(name)
        if mapped:
            add(rep, mapped[0], row["Value"], mapped[1], name)

    for row in count_rows:
        name = definitions.get(row["DefinitionID"], "")
        rep = rep_number_by_id.get(row["ReplicationID"], row["ReplicationID"])
        if name == "Counter 1":
            add(rep, "completed_counter", row["Count"], "items", "current Record OutPut path")
        elif name == "Counter 2":
            add(rep, "value_counter", row["Count"], "CNY", "current Record Revenue path")

    for row in stat_rows:
        name = definitions.get(row["DefinitionID"], "")
        if not name.endswith(".NumberInQueue"):
            continue
        rep = rep_number_by_id.get(row["ReplicationID"], row["ReplicationID"])
        safe_name = name.replace(".NumberInQueue", "").replace(" ", "_").replace(".", "_")
        add(rep, f"{safe_name}_queue_max", row["MaxObs"], "items", name)

    for rep in sorted(rep_number_by_id.values()):
        rep_rows = [row for row in rows if row["replication"] == rep]
        entity_out = next((row["actual_value"] for row in rep_rows if row["metric"] == "entity_number_out"), None)
        counter = next((row["actual_value"] for row in rep_rows if row["metric"] == "completed_counter"), None)
        if entity_out is not None and counter is not None:
            mismatch = float(entity_out) != float(counter)
            add(
                rep,
                "entity_out_counter_mismatch",
                int(mismatch),
                "flag",
                "1 means Entity.NumberOut includes an exit path not counted by Record OutPut",
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "experiment_id",
            "metric",
            "actual_value",
            "unit",
            "replication",
            "model_version",
            "evidence_path",
            "status",
            "notes",
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
