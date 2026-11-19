"""Trusted adapter. Original source/machine/randomness/accounting stay untouched."""
import hashlib
import json
import os
import selectors
import subprocess
import time
from pathlib import Path

import simpy
from soft_procedure.config import ROUTES, STATIONS, SimulationConfig
from soft_procedure.model.simulation import Simulation
from soft_procedure.model.station import Station
from soft_procedure.model.machine import Machine
from soft_procedure.model.source import Source, arrival_schedule
from soft_procedure.randomness import processing_duration, stream

HERE = Path(__file__).resolve().parent


class Policy:
    def __init__(self, path):
        self.started = time.monotonic()
        self.calls = 0
        self.digest = hashlib.sha256()
        self.process = subprocess.Popen(['/usr/bin/python3', '-I', str(HERE/'policy_worker.py'), str(path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, close_fds=True, env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        if self.read(3) != {'ready': True}:
            raise RuntimeError('candidate sandbox not ready')

    def read(self, seconds=1.1):
        if not self.selector.select(seconds):
            self.process.kill()
            raise TimeoutError('candidate response timeout')
        line = self.process.stdout.readline(1048577)
        if not line or len(line) > 1048576:
            raise RuntimeError('candidate exited or response too large')
        value = json.loads(line)
        if 'error' in value:
            raise RuntimeError(value['error'])
        return value

    def decide(self, observation):
        if time.monotonic() - self.started > 300:
            raise TimeoutError('path wall budget exceeded')
        request = json.dumps(observation, separators=(',', ':'), allow_nan=False)
        self.process.stdin.write(request+'\n')
        self.process.stdin.flush()
        response = self.read()
        self.calls += 1
        self.digest.update(request.encode())
        self.digest.update(json.dumps(response, sort_keys=True).encode())
        action = response['action']
        if not isinstance(action, dict):
            raise ValueError('action must be object')
        if set(action) == {'wait'}:
            delay = action['wait']
            if type(delay) not in (int, float) or not 0 < delay <= 15:
                raise ValueError('invalid delay')
        elif set(action) == {'job'}:
            if type(action['job']) is not int or action['job'] not in {j['id'] for j in observation['jobs']}:
                raise ValueError('illegal job handle')
        else:
            raise ValueError('invalid action fields')
        return action

    def close(self):
        self.selector.close()
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill(); self.process.wait()


class ControlledStation(Station):
    def __init__(self, sim, name):
        super().__init__(sim.env, name, sim.config)
        self.sim = sim
        self.retry_pending = False
        self.busy_dispatch = False

    def observe(self, job, request=0):
        route = ROUTES[job.product][job.operation_index:]
        remaining = sum(x[1] for x in route)
        return {'id': job.job_id, 'product': job.product, 'internal': job.admitted_at is not None,
                'request': request, 'queue_entered': job.queue_entered_at,
                'wait': self.env.now - (job.queue_entered_at if job.queue_entered_at is not None else job.arrival_time),
                'remaining_mean': remaining, 'current_mean': route[0][1],
                'price': self.config.product_prices[job.product],
                'margin': self.config.product_prices[job.product] - remaining * (100/60)}

    def decision(self, kind, jobs, machine=None):
        return self.sim.policy.decide({'kind': kind, 'time': self.env.now,
            'remaining': self.config.horizon-self.env.now, 'station': self.name,
            'wip': self.sim.tokens, 'last_product': machine.last_product if machine else None,
            'jobs': [self.observe(j, i) for i,j in enumerate(jobs)]})

    def retry(self, delay):
        if self.retry_pending:
            return
        self.retry_pending = True
        def wake():
            yield self.env.timeout(delay)
            self.retry_pending = False
            self._dispatch()
        self.env.process(wake())

    def _dispatch(self):
        if self.busy_dispatch:
            return
        self.busy_dispatch = True
        try:
            while True:
                while self.pending and len(self.waiting) < self.capacity:
                    # Admission only queries when a physical slot is available.
                    action = self.decision('admit', [j for j,e in self.pending])
                    if 'wait' in action:
                        self.retry(action['wait']); break
                    index = next(i for i,(j,e) in enumerate(self.pending) if j.job_id == action['job'])
                    job, admitted = self.pending[index]
                    del self.pending[index]
                    job.queue_entered_at = float(self.env.now)
                    if job.admitted_at is None:
                        job.admitted_at = float(self.env.now)
                        self.sim.tokens += 1
                    job.location = self.name
                    job.operations.append({'station': self.name, 'operation_index': job.operation_index,
                        'queue_entered_at': float(self.env.now), 'start': None, 'processing_start': None,
                        'processed_at': None, 'transferred_at': None})
                    self.waiting.append(job)
                    self._record_queue()
                    admitted.succeed(job)
                if not self.waiting or not self.idle_machines:
                    break
                machine, assigned = self.idle_machines[0]
                action = self.decision('dispatch', self.waiting, machine)
                if 'wait' in action:
                    self.retry(action['wait']); break
                job = next(j for j in self.waiting if j.job_id == action['job'])
                self.idle_machines.popleft()
                self.waiting.remove(job)
                self._record_queue()
                self.wait_times.append(float(self.env.now - job.queue_entered_at))
                job.location = machine.name
                job.operations[-1]['start'] = float(self.env.now)
                assigned.succeed(job)
        finally:
            self.busy_dispatch = False


class ControlledSimulation(Simulation):
    def __init__(self, config, seed, policy, schedule=None):
        self.config, self.seed = config.validate(), seed
        self.env = simpy.Environment()
        self.policy, self.tokens = policy, 0
        self.jobs, self.completed, self.samples = [], [], []
        self.stations = {name: ControlledStation(self, name) for name in STATIONS}
        self.machines = []
        for name, station in self.stations.items():
            for index in range(config.machine_counts[name]):
                machine_name = f'{name}-{index+1}'
                machine = Machine(self.env, machine_name, station, config,
                    lambda job: processing_duration(config, seed, job),
                    lambda job: self.env.process(self._transfer(job)),
                    failure_rng=stream(seed, 'failure', machine_name),
                    repair_rng=stream(seed, 'repair', machine_name))
                self.machines.append(machine)
                station.machines.append(machine)
        self.source = Source(self.env, self.stations, arrival_schedule(config, seed) if schedule is None else schedule, self.jobs)
        self.env.process(self._monitor())

    def _transfer(self, job):
        yield from super()._transfer(job)
        if job.completion_time is not None:
            self.tokens -= 1
            # Wake deferred release after completion, without advancing model time.
            # FIFO baseline has no deferred release so its event order is unchanged.
            for station in self.stations.values():
                if station.retry_pending:
                    station._dispatch()
