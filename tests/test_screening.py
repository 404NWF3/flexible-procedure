import csv
import gzip
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from soft_procedure import SimulationConfig, run_simulation
from soft_procedure.model.job import Job
from soft_procedure.model.source import Arrival, arrival_schedule
from soft_procedure.randomness import processing_duration
from soft_procedure.screening import run_screening, screening_configs, screening_diagnostics


class ScreeningTests(unittest.TestCase):
    def test_station_override_validation_and_round_trip(self):
        config = SimulationConfig.from_dict({"buffer_capacity": 20, "buffer_capacities": {"M2": 75},
                                             "processing_time_multipliers": {"M2": 0.75}})
        self.assertEqual(config.buffer_capacity_for("M1"), 20)
        self.assertEqual(config.buffer_capacity_for("M2"), 75)
        self.assertEqual(config, SimulationConfig.from_dict(config.to_dict()))
        for bad in ({"M6": 1}, [], None, {"M2": True}, {"M2": 0}):
            for field in ("buffer_capacities", "processing_time_multipliers"):
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    SimulationConfig.from_dict({field: bad})
        for field, bad in (("buffer_capacities", {"M2": 1.5}),
                           ("processing_time_multipliers", {"M2": float("nan")}),
                           ("processing_time_multipliers", {"M2": float("inf")})):
            with self.assertRaises(ValueError):
                SimulationConfig.from_dict({field: bad})

    def test_speed_scales_identical_samples_only_at_target_station(self):
        for cv in (0, 0.1, 2):
            base = SimulationConfig(processing_cv=cv)
            changed = replace(base, processing_time_multipliers={"M2": 0.75})
            for i in range(1, 30):
                job = Job(i, 1, "P1", 0)
                self.assertEqual(processing_duration(base, 42, job), processing_duration(changed, 42, job))
                job.operation_index = 1
                self.assertEqual(processing_duration(base, 42, job) * 0.75, processing_duration(changed, 42, job))
        result = run_simulation(SimulationConfig(horizon=40, processing_cv=0, failures_enabled=False,
                                                processing_time_multipliers={"M2": 0.5}),
                                schedule=[Arrival(0, 1, ("P1",))])
        self.assertEqual(result["jobs"][0]["completion_time"], 22)
        self.assertEqual(result["summary"]["mean_wip"], 22 / 40)

    def test_target_buffer_releases_blocking_and_counts_censored_transfer(self):
        base = SimulationConfig(horizon=20.5, buffer_capacity=1, processing_cv=0, failures_enabled=False,
                                setup_time=0, machine_counts={"M1": 1, "M2": 1, "M3": 2, "M4": 1, "M5": 2})
        schedule = [Arrival(0, 1, ("P1",) * 4)]
        blocked = run_simulation(base, schedule=schedule)
        self.assertAlmostEqual(blocked["summary"]["blocked_machine_minutes"], 0.5)
        diagnostic = screening_diagnostics(blocked, base)
        self.assertEqual(diagnostic["admissions"]["M2"]["transfer"]["pending_count"], 1)
        self.assertEqual(diagnostic["admissions"]["M2"]["transfer"]["pending_age_minutes"], 0.5)
        expanded = run_simulation(replace(base, buffer_capacities={"M2": 2}), schedule=schedule)
        self.assertEqual(expanded["summary"]["blocked_machine_minutes"], 0)
        self.assertEqual([s["buffer_capacity"] for s in expanded["stations"]], [1, 2, 1, 1, 1])
        self.assertTrue(all(s["max_queue"] <= s["buffer_capacity"] for s in expanded["stations"]))

    def test_matrix_changes_one_station_and_preserves_arrivals(self):
        base = SimulationConfig(horizon=60)
        original = base.to_dict()
        scenarios = screening_configs(base)
        self.assertEqual(len(scenarios), 41)
        self.assertEqual(len({meta["id"] for meta, _ in scenarios}), 41)
        for meta, config in scenarios:
            differences = [key for key in original if config.to_dict()[key] != original[key]]
            self.assertEqual(len(differences), 0 if meta["id"] == "baseline" else 1)
            self.assertEqual(arrival_schedule(base, 42), arrival_schedule(config, 42))
        self.assertEqual(base.to_dict(), original)

    def test_screening_saves_every_run_and_reconciles_paired_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            base = SimulationConfig(horizon=60)
            suite = run_screening(base, replications=2, seed=42, output=directory)
            self.assertEqual(suite["run_count"], 82)
            self.assertEqual(suite["status"], "complete")
            files = list(Path(directory, "runs").rglob("*.json.gz"))
            self.assertEqual(len(files), 82)
            with gzip.open(Path(directory, "runs", "baseline", "42.json.gz"), "rt") as stream:
                saved = json.load(stream)
            self.assertEqual(saved["summary"], run_simulation(base, 42)["summary"])
            with Path(directory, "replications.csv").open(encoding="utf-8-sig") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 82)
            baseline = {int(r["seed"]): r for r in rows if r["scenario"] == "baseline"}
            for scenario in suite["scenarios"]:
                current = [r for r in rows if r["scenario"] == scenario["id"]]
                for key in ("completed", "blocked_machine_minutes"):
                    expected = sum(float(r[key]) - float(baseline[int(r["seed"])][key]) for r in current) / 2
                    self.assertAlmostEqual(scenario["paired"][key]["mean"], expected)
            with self.assertRaises(ValueError):
                run_screening(base, output=directory)


if __name__ == "__main__":
    unittest.main()
