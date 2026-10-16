import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from soft_procedure import SimulationConfig
from soft_procedure.experiments import run_experiments
from soft_procedure.export import write_experiments
from soft_procedure.server import make_server, validate_request


class DeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suite = run_experiments(SimulationConfig(horizon=60), replications=2)

    def test_standalone_artifact_and_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_experiments(self.suite, directory)
            html = path.read_text()
            self.assertNotIn("__SIMULATION_DATA__", html)
            self.assertNotIn('<script src=', html)
            self.assertNotIn('<link rel="stylesheet"', html)
            self.assertIn('id="simulation-data"', html)
            result = json.loads(Path(directory, "results.json").read_text())
            self.assertEqual(len(result["scenarios"]), 5)
            self.assertEqual(len(Path(directory, "replications.csv").read_text().splitlines()), 11)
            self.assertTrue(Path(directory, "representative/baseline/operations.csv").is_file())

    def test_empty_completion_outputs_remain_valid_json(self):
        suite = run_experiments(SimulationConfig(horizon=1), replications=1)
        self.assertIsNone(suite["scenarios"][0]["summary"]["mean_cycle_time"]["mean"])
        json.dumps(suite, allow_nan=False)

    def test_http_run_and_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            server = make_server(self.suite, directory, port=0)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(base + "/api/health") as response:
                    self.assertEqual(json.load(response)["engine"], "SimPy")
                request = Request(base + "/api/run", data=json.dumps({"config": {"horizon": 80}, "replications": 2, "seed": 17}).encode(), headers={"Content-Type": "application/json"})
                with urlopen(request) as response:
                    updated = json.load(response)
                self.assertEqual(updated["seeds"], [17, 18])
                self.assertEqual(updated["base_config"]["horizon"], 80)
                invalid = Request(base + "/api/run", data=b'{"config":{"horizon":-1}}', headers={"Content-Type": "application/json"})
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(invalid)
                self.assertEqual(ctx.exception.code, 400)
                with urlopen(base + "/api/results") as response:
                    self.assertEqual(json.load(response)["seeds"], [17, 18])
            finally:
                server.shutdown()
                server.server_close()
                worker.join()

    def test_api_bounds(self):
        for payload in ([], {"replications": 0}, {"seed": True}, {"config": {"horizon": 999999}},
                        {"config": {"arrival_mean": .1}}, {"unexpected": 1}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_request(payload)


if __name__ == "__main__":
    unittest.main()
