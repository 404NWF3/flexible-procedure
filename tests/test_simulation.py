"""可手算的模型契约测试；使用 unittest，无需额外测试依赖。"""
import math
import random
import unittest
from dataclasses import replace
from types import SimpleNamespace

import simpy

from soft_procedure import SimulationConfig, run_simulation
from soft_procedure.config import ROUTES
from soft_procedure.experiments import estimate, run_experiments, scenario_config
from soft_procedure.model.job import Job
from soft_procedure.model.machine import Machine
from soft_procedure.model.source import Arrival, arrival_schedule
from soft_procedure.model.station import Station
from soft_procedure.policies import choose
from soft_procedure.randomness import processing_duration


class FixedExponential:
    def __init__(self, *values):
        self.values = iter(values)

    def expovariate(self, _):
        return next(self.values)


class MachineTests(unittest.TestCase):
    def machine(self, config=None, duration=5, transfer_delay=0, failures=None, repairs=None):
        env = simpy.Environment()
        config = config or SimulationConfig(failures_enabled=False)
        station = Station(env, "M1", config)
        finished = []

        def transfer(job):
            def send():
                yield env.timeout(transfer_delay)
                finished.append((job.job_id, env.now))
            return env.process(send())

        machine = Machine(env, "M1-1", station, config,
                          duration if callable(duration) else lambda job: duration, transfer,
                          failure_rng=failures or random.Random(1), repair_rng=repairs or random.Random(2))
        return env, station, machine, finished

    def put_jobs(self, station, products):
        for i, p in enumerate(products):
            station.put(Job(i + 1, 1, p, 0))

    def test_reference_setup_example(self):
        env, station, machine, completed = self.machine(duration=lambda j: 5 if j.product == "P1" else 4)
        self.put_jobs(station, ["P1", "P1", "P2"])
        env.run(until=40)
        self.assertEqual(completed, [(1, 5), (2, 10), (3, 29)])
        self.assertEqual(machine.state_times(), {"processing": 14, "setup": 15, "repair": 0, "blocked": 0, "idle": 11})
        self.assertEqual(machine.setup_count, 1)

    def test_failure_resumes_without_resampling(self):
        calls = []
        env, station, machine, completed = self.machine(
            config=SimulationConfig(), duration=lambda job: calls.append(job.job_id) or 10,
            failures=FixedExponential(4, 1000), repairs=FixedExponential(2))
        self.put_jobs(station, ["P1"])
        env.run(until=15)
        self.assertEqual(completed, [(1, 12)])
        self.assertEqual(calls, [1])
        self.assertEqual(machine.state_times()["processing"], 10)
        self.assertEqual(machine.state_times()["repair"], 2)

    def test_failure_during_setup_resumes(self):
        env, station, machine, completed = self.machine(
            config=SimulationConfig(), duration=lambda j: 5 if j.product == "P1" else 4,
            failures=FixedExponential(8, 1000), repairs=FixedExponential(2))
        self.put_jobs(station, ["P1", "P2"])
        env.run(until=30)
        self.assertEqual(completed, [(1, 5), (2, 26)])
        self.assertEqual(machine.state_times()["setup"], 15)
        self.assertEqual(machine.state_times()["repair"], 2)

    def test_blocked_machine_retains_job(self):
        env, station, machine, completed = self.machine(duration=1, transfer_delay=7)
        self.put_jobs(station, ["P1", "P1"])
        env.run(until=7)
        self.assertEqual(machine.current_job.job_id, 1)
        self.assertEqual(machine.state, "blocked")
        self.assertEqual(machine.processed_count, 1)
        self.assertEqual(len(station.waiting), 1)
        self.assertEqual(completed, [])
        env.run(until=10)
        self.assertEqual(completed, [(1, 8)])

    def test_failure_clock_does_not_consume_idle_or_blocked_time(self):
        env, station, machine, _ = self.machine(config=SimulationConfig(), duration=1, transfer_delay=20,
            failures=FixedExponential(3, 100), repairs=FixedExponential(2))
        self.put_jobs(station, ["P1"])
        env.run(until=50)
        self.assertEqual(machine.failure_count, 0)
        self.assertEqual(machine._life_left, 2)

    def test_horizon_clips_active_work(self):
        env, station, machine, _ = self.machine(duration=100)
        self.put_jobs(station, ["P1"])
        env.run(until=20)
        self.assertEqual(machine.state_times()["processing"], 20)
        self.assertEqual(sum(machine.state_times().values()), 20)

    def test_parallel_machines_never_receive_same_job(self):
        env, station, first, completed = self.machine(duration=1)
        second = Machine(env, "M1-2", station, first.config, lambda _: 1, first.transfer,
                         failure_rng=random.Random(3), repair_rng=random.Random(4))
        self.put_jobs(station, ["P1"] * 10)
        env.run(until=6)
        self.assertEqual(len(completed), 10)
        self.assertEqual(len({j for j, t in completed}), 10)
        self.assertEqual([first.sent_count, second.sent_count], [5, 5])

    def test_invalid_transfer_rejected(self):
        env, station, machine, _ = self.machine()
        machine.transfer = lambda job: simpy.Environment().timeout(1)
        self.put_jobs(station, ["P1"])
        with self.assertRaises(TypeError):
            env.run(until=10)


class ModelTests(unittest.TestCase):
    def config(self, **changes):
        return replace(SimulationConfig(processing_cv=0, failures_enabled=False), **changes)

    def test_all_four_routes_have_hand_calculated_completion(self):
        for product, route in ROUTES.items():
            with self.subTest(product=product):
                result = run_simulation(self.config(horizon=100), schedule=[Arrival(0, 1, (product,))])
                self.assertEqual(result["jobs"][0]["completion_time"], sum(t for s, t in route))
                self.assertEqual([op["station"] for op in result["jobs"][0]["operations"]], [s for s, t in route])

    def test_stop_window_excludes_exact_horizon_completion(self):
        result = run_simulation(self.config(horizon=26), schedule=[Arrival(0, 1, ("P1",))])
        self.assertEqual(result["summary"]["completed"], 0)
        self.assertEqual(result["summary"]["wip"], 1)
        self.assertIsNone(result["summary"]["mean_cycle_time"])

    def test_external_arrivals_continue_under_full_buffers(self):
        result = run_simulation(self.config(horizon=2, buffer_capacity=1),
            schedule=[Arrival(0, 1, ("P1",) * 8), Arrival(1, 2, ("P1",) * 8)])
        self.assertEqual(result["summary"]["arrived"], 16)
        self.assertEqual(result["summary"]["external"], 13)
        self.assertEqual(result["summary"]["wip"], 3)
        self.assertTrue(all(r["max_queue"] <= 1 for r in result["stations"]))

    def test_conservation_and_residual_waits_under_load(self):
        result = run_simulation(self.config(horizon=300, buffer_capacity=3), seed=7)
        summary = result["summary"]
        self.assertEqual(summary["arrived"], summary["completed"] + summary["wip"] + summary["external"])
        self.assertEqual(result["checks"]["physical_wip"], summary["wip"])
        self.assertTrue(any(s["censored_wait_mean"] is not None for s in result["stations"]))
        for m in result["machines"]:
            self.assertAlmostEqual(sum(m["state_times"].values()), 300)

    def test_queue_mean_is_time_weighted(self):
        env = simpy.Environment()
        station = Station(env, "M1", self.config())
        station.queue_log = [{"time": 0, "length": 0}, {"time": 1, "length": 10}, {"time": 9, "length": 0}]
        self.assertEqual(station.mean_queue(10), 8)

    def test_reproducibility_and_fresh_state(self):
        config = self.config(horizon=200)
        self.assertEqual(run_simulation(config, 42), run_simulation(config, 42))

    def test_processing_samples_bound_to_job_operation(self):
        config = SimulationConfig()
        jobs = [Job(i, 1, "P1", 0) for i in range(1, 20)]
        forward = {j.job_id: processing_duration(config, 42, j) for j in jobs}
        backward = {j.job_id: processing_duration(config, 42, j) for j in reversed(jobs)}
        self.assertEqual(forward, backward)

    def test_arrival_schedule_unchanged_by_decisions(self):
        base = SimulationConfig()
        for name in ("m4_extra", "same_family", "no_setup", "no_failure"):
            self.assertEqual(arrival_schedule(base, 42), arrival_schedule(scenario_config(base, name), 42))

    def test_same_family_and_aging_priority(self):
        jobs = [Job(1, 1, "P1", 0, queue_entered_at=0), Job(2, 1, "P2", 0, queue_entered_at=10)]
        machine = SimpleNamespace(last_product="P2")
        self.assertEqual(choose(jobs, machine, 20, "same_family", 100).job_id, 2)
        self.assertEqual(choose(jobs, machine, 105, "aging", 100).job_id, 1)
        self.assertEqual(choose(jobs, machine, 20, "fifo", 100).job_id, 1)

    def test_student_t_interval_and_single_replication(self):
        result = estimate([10, 20, 30])
        self.assertAlmostEqual(result["mean"], 20)
        self.assertAlmostEqual(result["ci95"], 4.302653 * 10 / math.sqrt(3))
        self.assertIsNone(estimate([10])["ci95"])
        self.assertIsNone(estimate([None])["mean"])

    def test_experiments_paired_statistics_and_config_isolation(self):
        base = self.config(horizon=120)
        suite = run_experiments(base, replications=3)
        self.assertEqual(base.machine_counts["M4"], 1)
        self.assertEqual(suite["scenarios"][1]["config"]["machine_counts"]["M4"], 2)
        baseline = suite["scenarios"][0]
        for s in suite["scenarios"]:
            self.assertEqual([r["arrived"] for r in s["runs"]], [r["arrived"] for r in baseline["runs"]])
            expected = sum(a["completed"] - b["completed"] for a, b in zip(s["runs"], baseline["runs"])) / 3
            self.assertAlmostEqual(s["paired_output_difference"]["mean"], expected)

    def test_validation(self):
        for changes in ({"horizon": 0}, {"processing_cv": float("nan")}, {"batch_min": 3, "batch_max": 2},
                        {"machine_counts": {"M1": 0}}, {"buffer_capacity": True}, {"failures_enabled": 1},
                        {"sample_interval": float("inf")}, {"policy_name": "unknown"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                SimulationConfig.from_dict(changes)


if __name__ == "__main__":
    unittest.main()
