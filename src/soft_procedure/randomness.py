"""按用途拆分随机流；不使用 Python 进程间不稳定的 hash()。"""
import hashlib
import random

from .config import ROUTES, SimulationConfig


def stream(seed: int, *keys: object) -> random.Random:
    value = "|".join(map(str, (seed, *keys))).encode()
    return random.Random(int.from_bytes(hashlib.sha256(value).digest()[:16], "big"))


def processing_duration(config: SimulationConfig, seed: int, job) -> float:
    mean = ROUTES[job.product][job.operation_index][1]
    if config.processing_cv == 0:
        return float(mean)
    rng = stream(seed, "processing", job.job_id, job.operation_index)
    duration = rng.gauss(mean, mean * config.processing_cv)
    while duration <= 0:
        duration = rng.gauss(mean, mean * config.processing_cv)
    return duration
