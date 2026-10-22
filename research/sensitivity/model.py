"""Separate physical-parameter adapter for fixed, hash-verified archived policies.

No original simulator, policy, or contribution-loop source is modified. All policy
observations retain the original nominal routing means; only the plant changes.
"""
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research/contribution_loop"))

from adapter import ControlledSimulation, Policy as IsolatedPolicy
from evaluator import audit
from soft_procedure.config import SimulationConfig

FACTORS = {
    "arrival_rate": {"label": "物件到达速率", "baseline": 1.25, "unit": "件 / min",
                     "meaning": "批量仍为 5–20 件；只改变批次到达率，名义物件率为 12.5 / 平均批间隔"},
    "processing_speed": {"label": "加工速度", "baseline": 1.0, "unit": "标准速度倍数",
                         "meaning": "所有产品/工序的加工速度同比例变化；工艺时间与标准差除以速度倍率，CV 仍为 0.10"},
    "mtbf": {"label": "平均无故障工作时间", "baseline": 6000.0, "unit": "有效工作 min",
             "meaning": "指数寿命均值；只累计加工和换模时间，不是日历时间"},
    "mttr": {"label": "平均修复时间", "baseline": 240.0, "unit": "min",
             "meaning": "指数维修时长均值；维修后继续原加工/换模任务"},
}
POLICIES = {"fifo": "原始 FIFO", "same_family": "同类优先", "c20_hybrid": "上一轮固定策略 c20"}
LEVELS = (-0.05, -0.02, 0.02, 0.05)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scenarios():
    result = [{"id": "standard", "factor": None, "delta": 0.0, "label": "标准参数"}]
    for factor, info in FACTORS.items():
        for delta in LEVELS:
            suffix = ("minus" if delta < 0 else "plus") + str(round(abs(delta) * 100))
            result.append({"id": f"{factor}_{suffix}", "factor": factor, "delta": delta,
                           "label": f"{info['label']} {delta:+.0%}"})
    return result


def configuration(scenario):
    config = SimulationConfig()
    factor, delta = scenario["factor"], scenario["delta"]
    if factor is not None and factor not in FACTORS:
        raise ValueError("Unknown physical factor")
    if not math.isfinite(delta) or delta <= -1 or (factor is None and delta != 0):
        raise ValueError("Invalid perturbation")
    multiplier = 1 + delta
    speed = 1.0
    if factor == "arrival_rate":
        config.arrival_mean /= multiplier
    elif factor == "processing_speed":
        speed = multiplier
    elif factor in ("mtbf", "mttr"):
        setattr(config, factor, getattr(config, factor) * multiplier)
    return config.validate(), speed


class FrozenPolicy:
    """Trusted replay only: exact approved source, JSON semantics, no agent search.

    In-process evaluation avoids thousands of IPC round trips per fixed-policy
    run. It is explicitly NOT a sandbox for arbitrary or newly generated code.
    Preflight compares all trajectories and action digests with the old sandbox.
    """
    def __init__(self, policy_id, expected_sha):
        if policy_id not in POLICIES:
            raise ValueError("Only the three preregistered fixed policies are accepted")
        path = ROOT / f"search_workspace/candidates/{policy_id}/policy.py"
        if sha(path) != expected_sha:
            raise ValueError("Frozen policy changed")
        namespace = {"__name__": "fixed_sensitivity_policy"}
        exec(compile(path.read_text(), str(path), "exec"), namespace)
        self.function = namespace["decide"]
        self.calls = 0
        self.digest = hashlib.sha256()

    def decide(self, observation):
        request = json.dumps(observation, separators=(",", ":"), allow_nan=False)
        action = self.function(json.loads(request))
        response = json.loads(json.dumps({"action": action}, allow_nan=False))
        action = response["action"]
        if not isinstance(action, dict):
            raise ValueError("Invalid action")
        if set(action) == {"job"}:
            if type(action["job"]) is not int or action["job"] not in {j["id"] for j in observation["jobs"]}:
                raise ValueError("Illegal job")
        elif set(action) == {"wait"}:
            if type(action["wait"]) not in (float, int) or not 0 < action["wait"] <= 15:
                raise ValueError("Illegal delay")
        else:
            raise ValueError("Invalid action fields")
        self.calls += 1
        self.digest.update(request.encode())
        self.digest.update(json.dumps(response, sort_keys=True).encode())
        return action


class SensitivitySimulation(ControlledSimulation):
    def __init__(self, config, seed, policy, speed=1.0, schedule=None):
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError("Processing speed must be finite and positive")
        super().__init__(config, seed, policy, schedule)
        if speed != 1.0:
            # Before the environment runs, replace only the physical-time callback.
            # Nominal means sent to the frozen rule are intentionally unchanged.
            for machine in self.machines:
                original = machine.processing_time
                machine.processing_time = lambda job, draw=original: draw(job) / speed


def simulate(policy_id, expected_sha, scenario, seed, *, isolated=False):
    config, speed = configuration(scenario)
    if isolated:
        policy = IsolatedPolicy(ROOT / f"search_workspace/candidates/{policy_id}/policy.py")
    else:
        policy = FrozenPolicy(policy_id, expected_sha)
    try:
        simulation = SensitivitySimulation(config, seed, policy, speed)
        result = simulation.run()
        metrics = audit(result)
        if simulation.tokens != metrics["wip"]:
            raise ValueError("In-line occupancy differs")
        metrics.update({key: result["summary"][key] for key in ["arrived", "failure_count", "mean_cycle_time", "setup_count"]})
        metrics["repair_minutes"] = sum(m["state_times"]["repair"] for m in result["machines"])
        for product, values in metrics["products"].items():
            metrics[product + "_completed"] = values["completed"]
        return result, {**metrics, "decisions": policy.calls, "action_trace_sha256": policy.digest.hexdigest()}
    finally:
        if isolated:
            policy.close()
            # Close wrappers here without changing the frozen historical adapter.
            policy.process.stdin.close()
            policy.process.stdout.close()
