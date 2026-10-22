"""手算经济口径、期间截断、增量投资和统计/导出的一致性。"""
import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from soft_procedure import SimulationConfig, run_simulation
from soft_procedure.economics import economic_snapshot, investment_comparison
from soft_procedure.experiments import estimate, run_experiments, scenario_config
from soft_procedure.export import write_experiments
from soft_procedure.model.source import Arrival


class EconomicsTests(unittest.TestCase):
    def test_case_prices_and_machine_calendar_cost_hand_calculation(self):
        config = SimulationConfig(horizon=60, processing_cv=0, failures_enabled=False,
                                  operating_cost_basis="machine_calendar")
        result = run_simulation(config, schedule=[Arrival(0, 1, ("P1",))])
        self.assertEqual(result["summary"]["sales_revenue"], 200)
        self.assertEqual(result["summary"]["operating_cost"], 800)  # 8 台 × 1 h × 100 元
        self.assertEqual(result["summary"]["operating_contribution"], -600)
        self.assertEqual(result["economics"]["installed_equipment_value"], 4_000_000)
        self.assertEqual(sum(row["operating_cost"] for row in result["economics"]["machine_costs"]), 800)

    def test_weekly_cost_and_expansion_are_separate_from_capex(self):
        base = SimulationConfig()
        calendar = replace(base, operating_cost_basis="machine_calendar")
        for config, cost, equipment in ((base, 0, 4_000_000),
                                       (scenario_config(base, "m4_extra"), 0, 4_500_000),
                                       (calendar, 32_000, 4_000_000),
                                       (scenario_config(calendar, "m4_extra"), 36_000, 4_500_000)):
            with self.subTest(cost=cost):
                result = run_simulation(config, schedule=[])
                self.assertEqual(result["summary"]["operating_cost"], cost)
                self.assertEqual(result["summary"]["operating_contribution"], -cost)
                self.assertEqual(result["economics"]["installed_equipment_value"], equipment)

    def test_each_product_uses_its_own_price(self):
        for product, expected in (("P1", 200), ("P2", 180), ("P3", 250), ("P4", 300)):
            with self.subTest(product=product):
                result = run_simulation(SimulationConfig(horizon=40, processing_cv=0, failures_enabled=False),
                                        schedule=[Arrival(0, 1, (product,))])
                self.assertEqual(result["summary"]["sales_revenue"], expected)
                self.assertEqual(result["products"][product]["sales_revenue"], expected)

    def test_no_revenue_from_wip_external_or_exact_horizon_completion(self):
        config = SimulationConfig(horizon=26, processing_cv=0, failures_enabled=False, buffer_capacity=1,
                                  operating_cost_basis="machine_calendar")
        result = run_simulation(config, schedule=[Arrival(0, 1, ("P1",) * 100)])
        self.assertEqual(result["summary"]["sales_revenue"], 0)
        self.assertGreater(result["summary"]["wip"], 0)
        self.assertGreater(result["summary"]["external"], 0)
        self.assertAlmostEqual(result["summary"]["operating_cost"], 8 * 26 / 60 * 100)

    def test_cost_bases_include_only_their_defined_states(self):
        # 1 台机床的 1 小时：加工20 + 换模10 + 维修5 + 阻塞15 + 空闲10。
        times = [{"processing": 20, "setup": 10, "repair": 5, "blocked": 15, "idle": 10}]
        completed = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
        for basis, expected in ((None, 100), ("machine_calendar", 200), ("machine_active", 100), ("line_calendar", 100)):
            with self.subTest(basis=basis or "default"):
                config = SimulationConfig() if basis is None else SimulationConfig(operating_cost_basis=basis)
                value = economic_snapshot(config, completed, times * 2, 60)
                self.assertEqual(value["sales_revenue"], 2510)
                self.assertEqual(value["operating_cost"], expected)
                self.assertEqual(value["operating_contribution"], 2510 - expected)

    def test_default_cost_counts_only_work_executed_before_horizon(self):
        config = SimulationConfig(horizon=2, processing_cv=0, failures_enabled=False)
        result = run_simulation(config, schedule=[Arrival(0, 1, ("P1",))])
        self.assertAlmostEqual(result["summary"]["operating_cost"], 2 / 60 * 100)
        self.assertEqual(result["summary"]["sales_revenue"], 0)

    def test_line_cost_is_not_multiplied_by_machine_count(self):
        result = run_simulation(SimulationConfig(horizon=60, operating_cost_basis="line_calendar"), schedule=[])
        self.assertEqual(result["summary"]["operating_cost"], 100)
        self.assertEqual(result["economics"]["line_chargeable_hours"], 1)
        self.assertTrue(all(row["operating_cost"] is None for row in result["economics"]["machine_costs"]))

    def test_economic_parameters_do_not_change_production_events(self):
        config = SimulationConfig(horizon=150)
        first = run_simulation(config, seed=37)
        changed = replace(config, product_prices={"P1": 1, "P2": 2, "P3": 3, "P4": 4},
                          machine_purchase_cost=10, operating_cost_per_hour=9, operating_cost_basis="machine_calendar")
        second = run_simulation(changed, seed=37)
        self.assertEqual(first["jobs"], second["jobs"])
        self.assertEqual(first["machines"], second["machines"])
        self.assertEqual(first["stations"], second["stations"])

    def test_samples_and_product_ledger_reconcile_with_summary(self):
        for basis in ("machine_calendar", "machine_active", "line_calendar"):
            result = run_simulation(SimulationConfig(horizon=180, operating_cost_basis=basis), seed=21)
            for sample in result["samples"]:
                self.assertEqual(sample["sales_revenue"], sum(n * result["config"]["product_prices"][p]
                                                            for p, n in sample["products"].items()))
                self.assertAlmostEqual(sample["operating_contribution"], sample["sales_revenue"] - sample["operating_cost"])
            for key in ("sales_revenue", "operating_cost", "operating_contribution"):
                self.assertEqual(result["summary"][key], result["samples"][-1][key])
            self.assertEqual(result["summary"]["sales_revenue"], sum(r["sales_revenue"] for r in result["products"].values()))

    def test_paired_contribution_and_exports(self):
        suite = run_experiments(SimulationConfig(horizon=150, operating_cost_basis="machine_calendar"),
                                replications=3, seed=12)
        baseline = suite["scenarios"][0]
        for scenario in suite["scenarios"]:
            difference = estimate([a["operating_contribution"] - b["operating_contribution"]
                                   for a, b in zip(scenario["runs"], baseline["runs"])])
            self.assertEqual(scenario["paired_contribution_difference"], difference)
            self.assertAlmostEqual(scenario["summary"]["sales_revenue"]["mean"],
                                   sum(r["mean"] for r in scenario["product_revenues"].values()))
        expanded = suite["scenarios"][1]
        self.assertEqual(expanded["investment"]["additional_capex"], 500_000)
        self.assertAlmostEqual(expanded["summary"]["operating_cost"]["mean"] - baseline["summary"]["operating_cost"]["mean"], 250)
        with tempfile.TemporaryDirectory() as directory:
            write_experiments(suite, directory)
            with Path(directory, "economics.csv").open(encoding="utf-8-sig") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 5)
            self.assertEqual(float(rows[1]["additional_capex"]), 500_000)
            self.assertAlmostEqual(float(rows[1]["operating_contribution"]), expanded["summary"]["operating_contribution"]["mean"])
            self.assertTrue(Path(directory, "representative/baseline/product_revenue.csv").is_file())
            self.assertTrue(Path(directory, "representative/baseline/machine_costs.csv").is_file())

    def test_incremental_payback_uses_gain_not_total_profit(self):
        base = SimulationConfig(horizon=120)
        config = scenario_config(base, "m4_extra")
        result = investment_comparison(config, base, estimate([8_000, 10_000, 12_000]))
        self.assertEqual(result["payback_periods"], 50)
        self.assertEqual(result["payback_work_hours"], 100)
        self.assertEqual(result["first_period_incremental_cash"], -490_000)
        self.assertEqual(result["status"], "positive_gain")

    def test_no_payback_for_nonpositive_gain_or_no_investment(self):
        base = SimulationConfig()
        for gain in (-1000, 0):
            result = investment_comparison(scenario_config(base, "m4_extra"), base, estimate([gain, gain]))
            self.assertIsNone(result["payback_periods"])
            self.assertIsNone(result["payback_work_hours"])
            self.assertEqual(result["status"], "no_positive_gain")
        result = investment_comparison(base, base, estimate([1000]))
        self.assertIsNone(result["payback_periods"])
        self.assertEqual(result["status"], "no_additional_capex")
        uncertain = investment_comparison(scenario_config(base, "m4_extra"), base, estimate([1000]))
        self.assertEqual(uncertain["status"], "uncertain_gain")

    def test_zero_prices_and_costs_stay_finite(self):
        config = SimulationConfig(horizon=30, product_prices=dict.fromkeys(("P1", "P2", "P3", "P4"), 0),
                                  machine_purchase_cost=0, operating_cost_per_hour=0)
        suite = run_experiments(config, replications=1)
        json.dumps(suite, allow_nan=False)
        for scenario in suite["scenarios"]:
            self.assertEqual(scenario["summary"]["operating_contribution"]["mean"], 0)
            self.assertIsNone(scenario["investment"]["payback_periods"])

    def test_economic_config_validation_and_independent_defaults(self):
        for changes in ({"product_prices": {}}, {"product_prices": []}, {"product_prices": {"P1": 2}},
                        {"product_prices": {"P1": True, "P2": 1, "P3": 1, "P4": 1}},
                        {"product_prices": {"P1": float("inf"), "P2": 1, "P3": 1, "P4": 1}},
                        {"operating_cost_per_hour": -1}, {"machine_purchase_cost": float("nan")},
                        {"operating_cost_basis": "unknown"}, {"operating_cost_basis": []}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                SimulationConfig.from_dict(changes)
        first, second = SimulationConfig(), SimulationConfig()
        first.product_prices["P1"] = 999
        self.assertEqual(second.product_prices["P1"], 200)


if __name__ == "__main__":
    unittest.main()
