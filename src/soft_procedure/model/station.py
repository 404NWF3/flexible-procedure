"""有限缓冲与原子派工。pending 中的工件仍在上游机床/线外。"""
from collections import deque

from ..policies import choose


class Station:
    def __init__(self, env, name, config):
        self.env, self.name, self.config = env, name, config
        self.capacity = config.buffer_capacity
        self.waiting = []
        self.pending = deque()
        self.idle_machines = deque()
        self.machines = []
        self.queue_log = [{"time": 0.0, "length": 0}]
        self.wait_times = []
        self.max_queue = 0

    def put(self, job):
        event = self.env.event()
        self.pending.append((job, event))
        self._dispatch()
        return event

    def request_job(self, machine):
        event = self.env.event()
        self.idle_machines.append((machine, event))
        self._dispatch()
        return event

    def _record_queue(self):
        self.max_queue = max(self.max_queue, len(self.waiting))
        row = {"time": float(self.env.now), "length": len(self.waiting)}
        if self.queue_log[-1]["time"] == self.env.now:
            self.queue_log[-1] = row
        else:
            self.queue_log.append(row)

    def _dispatch(self):
        # 所有挑选、移除和预留都在无 yield 的调用中完成，防止重复派工。
        while True:
            while self.pending and len(self.waiting) < self.capacity:
                job, admitted = self.pending.popleft()
                job.queue_entered_at = float(self.env.now)
                if job.admitted_at is None:
                    job.admitted_at = float(self.env.now)
                job.location = self.name
                job.operations.append({
                    "station": self.name, "operation_index": job.operation_index,
                    "queue_entered_at": float(self.env.now), "start": None,
                    "processing_start": None, "processed_at": None, "transferred_at": None,
                })
                self.waiting.append(job)
                self._record_queue()
                admitted.succeed(job)
            if not self.waiting or not self.idle_machines:
                break
            machine, assigned = self.idle_machines.popleft()
            job = choose(self.waiting, machine, self.env.now, self.config.policy_name, self.config.aging_threshold)
            self.waiting.remove(job)
            self._record_queue()
            self.wait_times.append(float(self.env.now - job.queue_entered_at))
            job.location = machine.name
            job.operations[-1]["start"] = float(self.env.now)
            assigned.succeed(job)

    def mean_queue(self, until):
        return sum(row["length"] * ((self.queue_log[i + 1]["time"] if i + 1 < len(self.queue_log) else until) - row["time"])
                   for i, row in enumerate(self.queue_log)) / until
