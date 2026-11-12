"""Compact, causal research runner retaining the original physical semantics.

The trusted engine owns randomness. Policies see frozen current observations,
never seeds, event queues, future arrivals, required work or failure lifetimes.
Detailed event logs are replaced by online counters for ten-year experiments.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
import time

import simpy

from .config import PRODUCT_MIX, ROUTES, STATIONS, SimulationConfig
from .randomness import processing_duration, stream


@dataclass(slots=True)
class Work:
    job_id: int
    product: str
    arrival_time: float
    operation_index: int = 0
    admitted_at: float | None = None
    queue_entered_at: float = 0.0


@dataclass(frozen=True, slots=True)
class JobView:
    id: int
    product: str
    request: int
    internal: bool
    queue_entered: float
    wait: float
    remaining_mean: float
    current_mean: float
    price: float


@dataclass(frozen=True, slots=True)
class DecisionView:
    now: float
    remaining: float
    station: str
    last_product: str | None
    completed: tuple[int, ...]
    arrived: tuple[int, ...]


@dataclass(frozen=True)
class Design:
    id: str
    parent: str | None = None
    regime: str = "none"
    rule: str = "family"
    admission: str = "internal"
    fairness: float = 0.0
    counts: tuple[int, ...] = (2, 1, 2, 1, 2)
    review_minutes: float = 2400.0
    buy_threshold: float = 0.85
    change: str = ""


class OnlinePolicy:
    """All rule inputs are immutable public/past observations, with no engine reference."""
    def __init__(self, design: Design):
        self.design = design

    def rank(self, j: JobView, o: DecisionView, *, admission: bool):
        d = self.design
        total = sum(o.completed)
        # Public arrival probabilities are available at time zero. No final
        # realized arrival counts enter this online deficit calculation.
        i = int(j.product[1:]) - 1
        target = tuple(PRODUCT_MIX.values())[i]
        deficit = (target * (total + 20) - o.completed[i]) / (target * (total + 20))
        fair_bonus = d.fairness * deficit
        fifo = (j.queue_entered, j.id)
        if admission:
            if d.admission == "fifo":
                return (j.request,)
            if d.admission == "internal":
                return (not j.internal, j.request)
            margin = (j.price - 100 / 60 * j.remaining_mean) / max(1, j.remaining_mean)
            return (not j.internal, -margin - fair_bonus, j.request)
        if d.rule == "fifo":
            return fifo
        if d.rule == "family" and d.fairness == 0:
            return (j.product != o.last_product if o.last_product else False, *fifo)
        setup = 15 if o.last_product and j.product != o.last_product else 0
        if d.rule == "hybrid" and o.station in ("M2", "M3", "M4") and not d.fairness:
            return (j.product != o.last_product if o.last_product else False, *fifo)
        score = (j.price - 100 / 60 * (j.remaining_mean + setup)) / max(1, j.remaining_mean + setup)
        # Fairness has units comparable to marginal value / expected minute.
        # Family preference limits unnecessary setups while permitting deficits
        # to outweigh it, unlike an absolute same-family priority.
        if d.rule == "family":
            score = (2 if j.product == o.last_product else 0)
        return (-score - fair_bonus, *fifo)


class Buffer:
    def __init__(self, sim, name):
        self.sim, self.name = sim, name
        self.waiting, self.idle = [], deque()
        self.pending = {(p, internal): deque() for p in PRODUCT_MIX for internal in (False, True)}
        self.seq = 0
        self.area, self.since, self.old_length = 0.0, 0.0, 0
        self.maximum = self.dispatched = 0
        self.wait_sum = 0.0
        self.machines = []

    def record(self):
        now = self.sim.env.now
        self.area += self.old_length * (now - self.since)
        self.since, self.old_length = now, len(self.waiting)
        self.maximum = max(self.maximum, self.old_length)

    def put(self, job):
        event = self.sim.env.event()
        self.seq += 1
        self.pending[job.product, job.admitted_at is not None].append((job, event, self.seq))
        self.dispatch()
        return event

    def request(self, machine):
        event = self.sim.env.event()
        self.idle.append((machine, event))
        self.dispatch()
        return event

    def view(self, job, request=0):
        route = ROUTES[job.product]
        return JobView(job.job_id, job.product, request, job.admitted_at is not None,
                       job.queue_entered_at, self.sim.env.now - job.queue_entered_at,
                       sum(t for _, t in route[job.operation_index:]),
                       route[job.operation_index][1], self.sim.config.product_prices[job.product])

    def observation(self, last=None):
        return DecisionView(self.sim.env.now, self.sim.project_horizon-self.sim.env.now,
                            self.name, last, tuple(self.sim.completed.values()), tuple(self.sim.arrived.values()))

    def dispatch(self):
        sim = self.sim
        while True:
            while len(self.waiting) < sim.config.buffer_capacity:
                heads = [q[0] for q in self.pending.values() if q]
                if not heads:
                    break
                if sim.design.admission == "fifo":
                    job, event, seq = min(heads, key=lambda row: row[2])
                else:
                    o = self.observation()
                    job, event, seq = min(heads, key=lambda row: sim.policy.rank(self.view(row[0], row[2]), o, admission=True))
                internal = job.admitted_at is not None
                self.pending[job.product, internal].popleft()
                job.queue_entered_at = float(sim.env.now)
                if not internal:
                    job.admitted_at = float(sim.env.now)
                    sim.admitted += 1
                self.waiting.append(job)
                self.record()
                event.succeed(job)
            if not self.waiting or not self.idle:
                break
            machine, assigned = self.idle.popleft()
            if sim.design.rule == "fifo":
                job = min(self.waiting, key=lambda j:(j.queue_entered_at,j.job_id))
            elif sim.design.rule == "family" and not sim.design.fairness:
                job = min(self.waiting, key=lambda j:(j.product != machine.last_product if machine.last_product else False,j.queue_entered_at,j.job_id))
            else:
                o = self.observation(machine.last_product)
                job = min(self.waiting, key=lambda j:sim.policy.rank(self.view(j),o,admission=False))
            self.waiting.remove(job)
            self.record()
            self.dispatched += 1
            self.wait_sum += sim.env.now - job.queue_entered_at
            assigned.succeed(job)


class Unit:
    STATES = ("processing", "setup", "repair", "blocked", "idle")

    def __init__(self, sim, station, index, bought_at=None):
        self.sim, self.station = sim, station
        self.name = f"{station.name}-{index}"
        self.born = float(sim.env.now)
        self.bought_at = bought_at
        self.last_product = self.current_job = None
        self.state, self.since = "idle", self.born
        self.times = dict.fromkeys(self.STATES, 0.0)
        self.setups = self.failures = self.processed = self.sent = 0
        self.failure_rng, self.repair_rng = stream(sim.seed,"failure",self.name), stream(sim.seed,"repair",self.name)
        self.life = self.lifetime()
        self.process = sim.env.process(self.run())

    def lifetime(self):
        if not self.sim.config.failures_enabled:
            return math.inf
        v=0.0
        while v <= 0:
            v=self.failure_rng.expovariate(1/self.sim.config.mtbf)
        return v

    def state_times(self):
        out=self.times.copy()
        out[self.state] += self.sim.env.now-self.since
        return out

    def state_to(self,state):
        if self.state != state:
            self.times[self.state] += self.sim.env.now-self.since
            self.state,self.since=state,float(self.sim.env.now)

    def work(self,duration,phase):
        remaining=float(duration)
        while remaining>0:
            if self.life<=0:
                self.failures+=1
                self.state_to("repair")
                yield self.sim.env.timeout(self.repair_rng.expovariate(1/self.sim.config.mttr))
                self.life=self.lifetime()
            self.state_to(phase)
            step=min(remaining,self.life)
            yield self.sim.env.timeout(step)
            remaining=max(0.0,remaining-step)
            self.life-=step

    def run(self):
        while True:
            self.state_to("idle")
            job=yield self.station.request(self)
            self.current_job=job
            if self.last_product and self.last_product!=job.product and self.sim.config.setup_time>0:
                self.setups+=1
                yield from self.work(self.sim.config.setup_time,"setup")
            self.last_product=job.product
            duration=processing_duration(self.sim.config,self.sim.seed,job)
            yield from self.work(duration,"processing")
            self.processed+=1
            self.state_to("blocked")
            yield self.sim.env.process(self.sim.transfer(job))
            self.sent+=1
            self.current_job=None


class ResearchSimulation:
    def __init__(self, design: Design, seed: int, horizon=1_200_000.0, config=None, project_horizon=None):
        self.config = (config or SimulationConfig(horizon=horizon)).validate()
        self.project_horizon = project_horizon or self.config.horizon
        self.design, self.seed = design, seed
        self.policy = OnlinePolicy(design)
        self.env=simpy.Environment()
        self.arrived=dict.fromkeys(PRODUCT_MIX,0)
        self.completed=dict.fromkeys(PRODUCT_MIX,0)
        self.admitted=0
        self.cycle_sum=0.0
        self.stations={n:Buffer(self,n) for n in STATIONS}
        self.machines=[]
        self.purchases=[]
        self.timeline=[]
        self.serial=0
        for name, count in self.config.machine_counts.items():
            for _ in range(count):
                self.add_machine(name,False)
        if design.regime=="upfront":
            for i,name in enumerate(STATIONS):
                for _ in range(max(0,design.counts[i]-len(self.stations[name].machines))):
                    self.add_machine(name,True)
        self.env.process(self.source())
        self.env.process(self.monitor())
        if design.regime=="dynamic":
            self.env.process(self.invest())

    def add_machine(self,name,purchased):
        station=self.stations[name]
        unit=Unit(self,station,len(station.machines)+1,float(self.env.now) if purchased else None)
        station.machines.append(unit)
        self.machines.append(unit)
        if purchased:
            self.purchases.append({"time":float(self.env.now),"station":name,"machine":unit.name,"cost":self.config.machine_purchase_cost})

    def source(self):
        ar,ba,pr=(stream(self.seed,k) for k in ("arrivals","batches","products"))
        while True:
            interval=ar.expovariate(1/self.config.arrival_mean)
            yield self.env.timeout(interval)
            count=ba.randint(self.config.batch_min,self.config.batch_max)
            for p in pr.choices(list(PRODUCT_MIX),weights=list(PRODUCT_MIX.values()),k=count):
                self.serial+=1
                self.arrived[p]+=1
                self.stations[ROUTES[p][0][0]].put(Work(self.serial,p,float(self.env.now)))

    def transfer(self,job):
        job.operation_index+=1
        if job.operation_index==len(ROUTES[job.product]):
            self.completed[job.product]+=1
            self.cycle_sum += self.env.now-job.arrival_time
        else:
            yield self.stations[ROUTES[job.product][job.operation_index][0]].put(job)

    def snapshot(self):
        times=[u.state_times() for u in self.machines]
        charge=sum(t["processing"]+t["setup"] for t in times)/60*self.config.operating_cost_per_hour
        revenue=sum(self.completed[p]*self.config.product_prices[p] for p in PRODUCT_MIX)
        capex=sum(p["cost"] for p in self.purchases)
        allocated=sum(p["cost"]*(self.env.now-p["time"])/(self.project_horizon-p["time"]) for p in self.purchases)
        return {"time":float(self.env.now),"arrived":self.serial,"completed":sum(self.completed.values()),
                "products":self.completed.copy(),"arrived_products":self.arrived.copy(),
                "external":self.serial-self.admitted,"wip":self.admitted-sum(self.completed.values()),
                "revenue":revenue,"operating_cost":charge,"capex":capex,
                "capital_allocated":allocated,"capital_unallocated":capex-allocated,
                "net":revenue-charge-capex,"period_profit_allocated":revenue-charge-allocated,
                "unrecovered_principal":max(0,capex-revenue+charge),
                "machine_counts":{n:len(s.machines) for n,s in self.stations.items()}}

    def monitor(self):
        while True:
            self.timeline.append(self.snapshot())
            yield self.env.timeout(min(120_000,self.config.horizon))

    def invest(self):
        previous={n:(0.0,0.0) for n in STATIONS}
        interval=self.design.review_minutes
        while True:
            yield self.env.timeout(interval)
            if self.project_horizon-self.env.now < 120_000:
                continue
            for i,(n,s) in enumerate(self.stations.items()):
                active=sum(u.state_times()["processing"]+u.state_times()["setup"] for u in s.machines)
                available=sum(self.env.now-u.born for u in s.machines)
                prev_active,prev_available=previous[n]
                load=(active-prev_active)/max(1,available-prev_available)
                previous[n]=(active,available)
                # Only realized work and current queue heads are used.
                backlog=len(s.waiting)+sum(len(q) for q in s.pending.values())
                if len(s.machines)<self.design.counts[i] and load>=self.design.buy_threshold and backlog>10:
                    self.add_machine(n,True)

    def run(self):
        start=time.monotonic()
        self.env.run(until=self.config.horizon)
        final=self.snapshot()
        self.timeline.append(final)
        unique={}
        stations=[]
        for n,s in self.stations.items():
            for j in s.waiting:
                unique[j.job_id]=j
            for q in s.pending.values():
                for j,_,_ in q:
                    unique[j.job_id]=j
            for u in s.machines:
                if u.current_job is not None:
                    unique[u.current_job.job_id]=u.current_job
            denom=sum(self.config.horizon-u.born for u in s.machines)
            states={k:sum(u.state_times()[k] for u in s.machines)/denom for k in Unit.STATES}
            stations.append({"name":n,"machines":len(s.machines),"states":states,
                             "mean_queue":(s.area+s.old_length*(self.config.horizon-s.since))/self.config.horizon,
                             "max_queue":s.maximum,"mean_wait":s.wait_sum/s.dispatched if s.dispatched else None,
                             "setups":sum(u.setups for u in s.machines),"failures":sum(u.failures for u in s.machines)})
        unfinished={p:{"count":0,"age_sum":0.0,"max_age":0.0} for p in PRODUCT_MIX}
        for j in unique.values():
            item=unfinished[j.product]
            age=self.config.horizon-j.arrival_time
            item["count"]+=1
            item["age_sum"]+=age
            item["max_age"]=max(item["max_age"],age)
        assert self.serial==sum(self.completed.values())+len(unique), "job conservation"
        assert final["external"]==sum(j.admitted_at is None for j in unique.values()), "external conservation"
        assert all(s.maximum<=self.config.buffer_capacity for s in self.stations.values()), "buffer capacity"
        assert all(abs(sum(u.state_times().values())-(self.config.horizon-u.born))<1e-6 for u in self.machines), "state time"
        q=sum(self.completed.values())
        tv=sum(abs(self.completed[p]/q-self.arrived[p]/self.serial) for p in PRODUCT_MIX)/2 if q else 1.0
        products={p:{"arrived":self.arrived[p],"completed":self.completed[p],
                     "output_share":self.completed[p]/q if q else None,
                     "completion_rate":self.completed[p]/self.arrived[p] if self.arrived[p] else None,
                     "unfinished":unfinished[p]["count"],
                     "unfinished_mean_age":unfinished[p]["age_sum"]/unfinished[p]["count"] if unfinished[p]["count"] else None,
                     "unfinished_max_age":unfinished[p]["max_age"]} for p in PRODUCT_MIX}
        return {"design":self.design.id,"seed":self.seed,"horizon":self.config.horizon,
                "summary":{**final,"tv":tv,"mean_cycle_time":self.cycle_sum/q if q else None},
                "products":products,"stations":stations,"timeline":self.timeline,"purchases":self.purchases,
                "checks":{"conservation":True,"buffer_capacity":True,"state_time":True,
                          "full_purchase_cost_deducted":True,"terminal_capital_unallocated":final["capital_unallocated"]},
                "seconds":time.monotonic()-start}
