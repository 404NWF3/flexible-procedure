"""唯一的单次仿真入口；每次调用重建全部状态。"""
import simpy

from ..config import ROUTES, STATIONS, SimulationConfig
from ..metrics import collect_result
from ..randomness import processing_duration, stream
from .machine import Machine
from .source import Source, arrival_schedule
from .station import Station


class Simulation:
    def __init__(self, config, seed, schedule=None):
        self.config, self.seed = config.validate(), seed
        self.env = simpy.Environment()
        self.jobs, self.completed, self.samples = [], [], []
        self.stations = {name: Station(self.env, name, config) for name in STATIONS}
        self.machines = []
        for name, station in self.stations.items():
            for index in range(config.machine_counts[name]):
                machine_name = f"{name}-{index + 1}"
                machine = Machine(
                    self.env, machine_name, station, config,
                    lambda job: processing_duration(config, seed, job),
                    lambda job: self.env.process(self._transfer(job)),
                    failure_rng=stream(seed, "failure", machine_name),
                    repair_rng=stream(seed, "repair", machine_name),
                )
                self.machines.append(machine)
                station.machines.append(machine)
        self.source = Source(self.env, self.stations, arrival_schedule(config, seed) if schedule is None else schedule, self.jobs)
        self.env.process(self._monitor())

    def _transfer(self, job):
        job.operation_index += 1
        if job.operation_index == len(ROUTES[job.product]):
            job.completion_time = float(self.env.now)
            job.location = "completed"
            self.completed.append(job)
        else:
            next_station = ROUTES[job.product][job.operation_index][0]
            yield self.stations[next_station].put(job)

    def snapshot(self):
        external = sum(job.admitted_at is None for job in self.jobs)
        return {
            "time": float(self.env.now), "arrived": len(self.jobs), "completed": len(self.completed),
            "external": external, "wip": len(self.jobs) - len(self.completed) - external,
            "products": {product: sum(j.product == product for j in self.completed) for product in ROUTES},
            "queues": {name: len(station.waiting) for name, station in self.stations.items()},
            "machines": {m.name: {"state": m.state, "product": m.current_job.product if m.current_job else None,
                                  "job_id": m.current_job.job_id if m.current_job else None} for m in self.machines},
        }

    def _monitor(self):
        while True:
            self.samples.append(self.snapshot())
            yield self.env.timeout(self.config.sample_interval)

    def run(self):
        self.env.run(until=self.config.horizon)
        self.samples.append(self.snapshot())
        return collect_result(self)


def run_simulation(config: SimulationConfig | None = None, seed: int = 42, *, schedule=None):
    if type(seed) is not int:
        raise ValueError("seed 必须为整数")
    return Simulation(config or SimulationConfig(), seed, schedule).run()
