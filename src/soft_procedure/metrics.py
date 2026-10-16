"""时间积分指标与原始记录；未完成工件不冒充已完成的周期样本。"""
from dataclasses import asdict
from statistics import mean

from .config import PRODUCT_MIX


def average(values):
    values = list(values)
    return mean(values) if values else None


def collect_result(sim):
    horizon = sim.config.horizon
    machines = [{
        "name": m.name, "station": m.station.name, "state_times": m.state_times(),
        "processed": m.processed_count, "sent": m.sent_count,
        "setups": m.setup_count, "failures": m.failure_count,
        "intervals": m.intervals(horizon),
    } for m in sim.machines]
    stations = []
    for name, station in sim.stations.items():
        states = {s: sum(m.state_times()[s] for m in station.machines) / (len(station.machines) * horizon)
                  for s in sim.machines[0].STATES}
        stations.append({
            "name": name, "machine_count": len(station.machines), "states": states,
            "mean_queue": station.mean_queue(horizon), "max_queue": station.max_queue,
            "mean_wait": average(station.wait_times), "dispatched": len(station.wait_times),
            "waiting_at_end": len(station.waiting),
            "censored_wait_mean": average(horizon - j.queue_entered_at for j in station.waiting),
            "setup_count": sum(m.setup_count for m in station.machines),
            "failure_count": sum(m.failure_count for m in station.machines),
        })
    last = sim.samples[-1]
    total_time = len(machines) * horizon
    counts = {s: sum(m["state_times"][s] for m in machines) / total_time for s in sim.machines[0].STATES}
    conservation_error = len(sim.jobs) - len(sim.completed) - last["wip"] - last["external"]
    # 独立占位检查，避免只验证由减法定义的 WIP。
    physical_wip = sum(len(s.waiting) for s in sim.stations.values()) + sum(m.current_job is not None for m in sim.machines)
    assert physical_wip == last["wip"], "在制品占位不守恒"
    assert all(s.max_queue <= s.capacity for s in sim.stations.values()), "缓冲区越界"
    assert all(abs(sum(m["state_times"].values()) - horizon) < 1e-7 for m in machines), "状态时间不守恒"
    return {
        "seed": sim.seed, "config": sim.config.to_dict(),
        "summary": {
            "arrived": len(sim.jobs), "completed": len(sim.completed),
            "wip": last["wip"], "external": last["external"],
            "throughput_per_hour": len(sim.completed) / horizon * 60,
            "mean_cycle_time": average(j.completion_time - j.arrival_time for j in sim.completed),
            "mean_flow_time": average(j.completion_time - j.admitted_at for j in sim.completed),
            "mean_release_wait": average(j.admitted_at - j.arrival_time for j in sim.jobs if j.admitted_at is not None),
            "processing_utilization": counts["processing"], "setup_share": counts["setup"],
            "repair_share": counts["repair"], "blocked_share": counts["blocked"],
            "setup_count": sum(m.setup_count for m in sim.machines),
            "failure_count": sum(m.failure_count for m in sim.machines),
        },
        "products": {p: {"arrived": sum(j.product == p for j in sim.jobs),
                         "completed": sum(j.product == p for j in sim.completed), "mix": ratio}
                     for p, ratio in PRODUCT_MIX.items()},
        "stations": stations, "machines": machines, "samples": sim.samples,
        "jobs": [asdict(j) for j in sim.jobs],
        "queue_logs": {n: s.queue_log for n, s in sim.stations.items()},
        "checks": {"conservation_error": conservation_error, "physical_wip": physical_wip,
                   "buffer_capacity_respected": True, "state_time_conserved": True},
    }
