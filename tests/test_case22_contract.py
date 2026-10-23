import unittest
from dataclasses import replace

from soft_procedure import SimulationConfig, run_simulation
from soft_procedure.config import PRODUCT_PRICES, ROUTES
from soft_procedure.experiments import run_core_experiments, scenario_config
from soft_procedure.model.source import Arrival


class Case22ContractTests(unittest.TestCase):
    def test_default_contract_matches_updated_task(self):
        config = SimulationConfig()
        self.assertEqual(config.horizon, 2400.0)
        self.assertEqual((config.arrival_mean, config.batch_min, config.batch_max), (10.0, 5, 20))
        self.assertEqual(config.machine_counts, {"M1": 2, "M2": 1, "M3": 2, "M4": 1, "M5": 2})
        self.assertEqual(config.buffer_capacity, 50)
        self.assertEqual((config.mtbf, config.mttr), (6000.0, 240.0))
        self.assertEqual(config.setup_time, 15.0)

    def test_each_product_has_expected_route_and_economic_value(self):
        config = replace(SimulationConfig(), processing_cv=0.0, setup_time=0.0, failures_enabled=False)
        for product, route in ROUTES.items():
            with self.subTest(product=product):
                result = run_simulation(config, schedule=[Arrival(0.0, 1, (product,))])
                summary = result["summary"]
                self.assertEqual(summary["completed"], 1)
                self.assertEqual(result["products"][product]["completed"], 1)
                self.assertEqual(summary["sales_revenue"], PRODUCT_PRICES[product])
                expected_hours = sum(duration for _, duration in route) / 60.0
                self.assertAlmostEqual(summary["operating_cost"], expected_hours * config.operating_cost_per_hour)
                self.assertAlmostEqual(summary["operating_contribution"],
                                       PRODUCT_PRICES[product] - expected_hours * config.operating_cost_per_hour)

    def test_core_experiment_matrix_and_m4_pairing(self):
        base = replace(SimulationConfig(), horizon=120.0, processing_cv=0.0, failures_enabled=False)
        suite = run_core_experiments(base, replications=2, seed=42)
        self.assertEqual(suite["scenario_set"], "core")
        self.assertEqual(suite["scenario_ids"], ["baseline", "m4_extra", "same_family", "same_family_m4_extra"])
        scenarios = {s["id"]: s for s in suite["scenarios"]}
        self.assertEqual(scenarios["baseline"]["config"]["machine_counts"]["M4"], 1)
        self.assertEqual(scenarios["m4_extra"]["config"]["machine_counts"]["M4"], 2)
        self.assertEqual(scenarios["baseline"]["investment"]["additional_capex"], 0.0)
        self.assertEqual(scenarios["m4_extra"]["investment"]["additional_capex"], 500_000.0)
        self.assertEqual(scenarios["same_family"]["config"]["policy_name"], "same_family")
        self.assertEqual(scenarios["same_family_m4_extra"]["paired_to"], "same_family")
        for scenario in scenarios.values():
            self.assertEqual(len(scenario["runs"]), 2)
            self.assertIn("operating_contribution", scenario["summary"])
            self.assertIn("paired_contribution_difference", scenario)

    def test_scenario_config_preserves_base_configuration(self):
        base = SimulationConfig()
        same_family_m4 = scenario_config(base, "same_family_m4_extra")
        self.assertEqual(base.machine_counts["M4"], 1)
        self.assertEqual(same_family_m4.machine_counts["M4"], 2)
        self.assertEqual(same_family_m4.policy_name, "same_family")


if __name__ == "__main__":
    unittest.main()
