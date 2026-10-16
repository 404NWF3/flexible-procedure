"""先生成外生到达清单；投料等待绝不延后后续批次。"""
from dataclasses import dataclass

from ..config import PRODUCT_MIX, ROUTES
from ..randomness import stream
from .job import Job


@dataclass(frozen=True)
class Arrival:
    time: float
    batch_id: int
    products: tuple[str, ...]


def arrival_schedule(config, seed):
    arrivals, batches, products = (stream(seed, name) for name in ("arrivals", "batches", "products"))
    result, now, batch_id = [], 0.0, 0
    while True:
        now += arrivals.expovariate(1.0 / config.arrival_mean)
        if now >= config.horizon:
            break
        batch_id += 1
        count = batches.randint(config.batch_min, config.batch_max)
        result.append(Arrival(now, batch_id, tuple(products.choices(list(PRODUCT_MIX), weights=list(PRODUCT_MIX.values()), k=count))))
    return result


class Source:
    def __init__(self, env, stations, schedule, jobs):
        self.env, self.stations, self.schedule, self.jobs = env, stations, schedule, jobs
        self.process = env.process(self._run())

    def _run(self):
        for batch in self.schedule:
            yield self.env.timeout(batch.time - self.env.now)
            for product in batch.products:
                job = Job(len(self.jobs) + 1, batch.batch_id, product, float(self.env.now))
                self.jobs.append(job)
                # put 自身返回等待事件，但到达生成器不 yield 这个事件。
                self.stations[ROUTES[product][0][0]].put(job)
