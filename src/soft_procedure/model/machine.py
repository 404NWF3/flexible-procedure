"""单台机床：取件 → 换模 → 加工（故障后续做）→ 等待交接。"""
import math

import simpy


class Machine:
    STATES = ("processing", "setup", "repair", "blocked", "idle")

    def __init__(self, env, name, station, config, processing_time, transfer, *, failure_rng, repair_rng):
        config.validate()
        self.env, self.name, self.station, self.config = env, name, station, config
        self.processing_time, self.transfer = processing_time, transfer
        self.failure_rng, self.repair_rng = failure_rng, repair_rng
        self.current_job = None
        self.last_product = None
        self.processed_count = self.sent_count = self.setup_count = self.failure_count = 0
        self.state = "idle"
        self._state_since = float(env.now)
        self._times = dict.fromkeys(self.STATES, 0.0)
        self.state_log = [{"time": float(env.now), "state": "idle", "job_id": None, "product": None}]
        self._life_left = self._new_lifetime()
        self.process = env.process(self._run())

    def _run(self):
        while True:
            self._set_state("idle")
            job = yield self.station.request_job(self)
            self.current_job = job
            operation = job.operations[-1]
            operation["machine"] = self.name
            if self.last_product is not None and job.product != self.last_product and self.config.setup_time > 0:
                self.setup_count += 1
                yield from self._work(self.config.setup_time, "setup")
            self.last_product = job.product
            # 一道工序仅抽一次时长，故障后继续剩余工作。
            duration = self.processing_time(job)
            operation["processing_start"] = float(self.env.now)
            operation["required_processing"] = duration
            yield from self._work(duration, "processing")
            operation["processed_at"] = float(self.env.now)
            self.processed_count += 1
            self._set_state("blocked")
            event = self.transfer(job)
            if not isinstance(event, simpy.Event) or event.env is not self.env:
                raise TypeError("transfer(job) 必须返回同一环境中的 SimPy Event")
            yield event
            operation["transferred_at"] = float(self.env.now)
            self.sent_count += 1
            self.current_job = None

    def _work(self, duration, phase):
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("工作时长必须是有限非负数")
        remaining = float(duration)
        while remaining > 0:
            if self._life_left <= 0:
                yield from self._repair()
            self._set_state(phase)
            step = min(remaining, self._life_left)
            yield self.env.timeout(step)
            remaining = max(0.0, remaining - step)
            self._life_left -= step
        # 工作与故障额度恰好同刻结束：先完成，下一段工作开始前维修。

    def _repair(self):
        self.failure_count += 1
        self._set_state("repair")
        yield self.env.timeout(self.repair_rng.expovariate(1.0 / self.config.mttr))
        self._life_left = self._new_lifetime()

    def _new_lifetime(self):
        if not self.config.failures_enabled:
            return math.inf
        value = 0.0
        while value <= 0:
            value = self.failure_rng.expovariate(1.0 / self.config.mtbf)
        return value

    def _set_state(self, state):
        if state == self.state:
            return
        self._times[self.state] += self.env.now - self._state_since
        self.state, self._state_since = state, float(self.env.now)
        self.state_log.append({
            "time": float(self.env.now), "state": state,
            "job_id": self.current_job.job_id if self.current_job else None,
            "product": self.current_job.product if self.current_job else None,
        })

    def state_times(self):
        result = self._times.copy()
        result[self.state] += self.env.now - self._state_since
        return result

    def intervals(self, until):
        return [dict(row, end=(self.state_log[i + 1]["time"] if i + 1 < len(self.state_log) else until))
                for i, row in enumerate(self.state_log)
                if (self.state_log[i + 1]["time"] if i + 1 < len(self.state_log) else until) > row["time"]]
