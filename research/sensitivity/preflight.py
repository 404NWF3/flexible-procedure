"""Physical-perturbation and fixed-policy replay gates, outside study samples."""
import json
import math
import statistics
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from model import (ROOT, FACTORS, POLICIES, FrozenPolicy, SensitivitySimulation,
                   configuration, scenarios, sha, simulate)
from analysis import paired_effect
from soft_procedure.config import SimulationConfig, ROUTES
from soft_procedure.model.source import Arrival, arrival_schedule
from soft_procedure.model.simulation import run_simulation
from soft_procedure.randomness import processing_duration

OUT = ROOT / "outputs/sensitivity_20261022"
REPLAYS = []


class SensitivityTests(unittest.TestCase):
    def policy(self, name="fifo"):
        return FrozenPolicy(name, sha(ROOT / f"search_workspace/candidates/{name}/policy.py"))

    def test_only_declared_physics_changes(self):
        standard = SimulationConfig().to_dict()
        for scenario in scenarios():
            config, speed = configuration(scenario)
            altered = {k for k, v in config.to_dict().items() if v != standard[k]}
            expected = {"arrival_rate": {"arrival_mean"}, "mtbf": {"mtbf"}, "mttr": {"mttr"}}
            self.assertEqual(altered, expected.get(scenario["factor"], set()))
            self.assertEqual(speed, 1 + scenario["delta"] if scenario["factor"] == "processing_speed" else 1)
        self.assertEqual(len(scenarios()), 17)

    def test_rate_uses_reciprocal_time(self):
        config, _ = configuration({"factor": "arrival_rate", "delta": .05})
        self.assertAlmostEqual(config.arrival_mean, 10 / 1.05)
        self.assertAlmostEqual(12.5 / config.arrival_mean, 1.25 * 1.05)

    def test_common_arrival_streams(self):
        baseline = arrival_schedule(SimulationConfig(), 43)
        config, _ = configuration({"factor": "arrival_rate", "delta": .05})
        changed = arrival_schedule(config, 43)
        self.assertGreaterEqual(len(changed), len(baseline))
        for a, b in zip(baseline, changed):
            self.assertEqual(a.products, b.products)
            self.assertAlmostEqual(a.time / 1.05, b.time)

    def test_processing_draws_scale_without_policy_recalibration(self):
        config = SimulationConfig()
        simulation = SensitivitySimulation(config, 43, self.policy("c20_hybrid"), speed=1.05)
        job = SimpleNamespace(product="P1", operation_index=0, job_id=99,
                              admitted_at=None, queue_entered_at=None, arrival_time=0)
        self.assertEqual(simulation.machines[0].processing_time(job), processing_duration(config, 43, job) / 1.05)
        observation = simulation.stations["M1"].observe(job)
        self.assertEqual(observation["current_mean"], 5)
        self.assertEqual(observation["remaining_mean"], 26)
        for factor in ("mtbf", "mttr"):
            changed, _ = configuration({"factor": factor, "delta": .05})
            a = SensitivitySimulation(config, 43, self.policy()).machines[0]
            b = SensitivitySimulation(changed, 43, self.policy()).machines[0]
            if factor == "mtbf":
                self.assertAlmostEqual(b._life_left, a._life_left * 1.05)
            else:
                self.assertAlmostEqual(b.repair_rng.expovariate(1 / changed.mttr), a.repair_rng.expovariate(1 / config.mttr) * 1.05)

    def test_hand_calculated_processing_and_cost(self):
        config = SimulationConfig(horizon=40, failures_enabled=False, processing_cv=0)
        for speed in (1.0, 1.05):
            simulation = SensitivitySimulation(config, 43, self.policy(), speed, [Arrival(1, 1, ("P1",))])
            result = simulation.run()
            self.assertEqual(result["summary"]["completed"], 1)
            self.assertAlmostEqual(result["jobs"][0]["completion_time"], 1 + 26 / speed)
            self.assertAlmostEqual(result["summary"]["operating_contribution"], 200 - 26 / speed * 100 / 60)

    def test_invalid_factor_and_source(self):
        for factor, delta in [("machines", .05), ("arrival_rate", -1), (None, .05)]:
            with self.assertRaises(ValueError):
                configuration({"factor": factor, "delta": delta})
        with self.assertRaises(ValueError):
            FrozenPolicy("c20_hybrid", "incorrect")
        with self.assertRaises(ValueError):
            FrozenPolicy("new_candidate", "incorrect")

    def test_full_fixed_policy_replay(self):
        selected = [scenarios()[0]] + [s for s in scenarios() if s["delta"] == .05]
        for policy in POLICIES:
            source = sha(ROOT / f"search_workspace/candidates/{policy}/policy.py")
            for scenario in selected:
                actual, metrics = simulate(policy, source, scenario, 43)
                reference, other = simulate(policy, source, scenario, 43, isolated=True)
                self.assertEqual(actual, reference, (policy, scenario["id"]))
                self.assertEqual(metrics, other, (policy, scenario["id"], "action/metric replay"))
                REPLAYS.append({"policy": policy, "scenario": scenario["id"], "seed": 43,
                                "full_trajectory_equal": True, "action_digest_equal": True})
                if scenario["id"] == "standard" and policy != "c20_hybrid":
                    native = run_simulation(SimulationConfig(policy_name=policy), 43)
                    for key in ["summary", "jobs", "machines", "stations", "samples", "queue_logs"]:
                        self.assertEqual(actual[key], native[key])


if __name__ == "__main__":
    start = time.monotonic()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SensitivityTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"passed": result.wasSuccessful(), "tests": result.testsRun, "errors": len(result.errors),
              "failures": len(result.failures), "seconds": time.monotonic() - start,
              "replays": REPLAYS, "sample_scope": "public seed 43; preflight only, excluded from the 200 study replicates",
              "source_hashes": {str(p.relative_to(ROOT)): sha(p) for p in Path(__file__).parent.glob("*.py")}}
    (OUT / "preflight.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
