"""Independent accounting, complete raw traces, immutable receipts, generic t inference."""
import gzip
import hashlib
import json
import math
import os
import statistics
import time
from pathlib import Path
from adapter import ControlledSimulation, Policy
from soft_procedure.config import ROUTES, SimulationConfig

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'outputs/contribution_loop_20261022'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    os.replace(temp, path)


def audit(result):
    h = result['config']['horizon']
    prices = result['config']['product_prices']
    jobs = result['jobs']
    ids = [j['job_id'] for j in jobs]
    assert len(ids) == len(set(ids))
    products = {}
    for product in ROUTES:
        subset = [j for j in jobs if j['product'] == product]
        complete = [j for j in subset if j['completion_time'] is not None]
        external = [j for j in subset if j['admitted_at'] is None]
        unfinished = [j for j in subset if j['completion_time'] is None]
        products[product] = {'arrived': len(subset), 'completed': len(complete),
            'external': len(external), 'wip': len(unfinished)-len(external),
            'unfinished': len(unfinished), 'unfinished_mean_age': statistics.mean([h-j['arrival_time'] for j in unfinished]) if unfinished else None,
            'unfinished_max_age': max([h-j['arrival_time'] for j in unfinished], default=0)}
    for j in jobs:
        assert 0 <= j['arrival_time'] < h
        route = ROUTES[j['product']]
        for i, op in enumerate(j['operations']):
            assert op['station'] == route[i][0] and op['operation_index'] == i
            assert j['arrival_time'] <= op['queue_entered_at'] < h
            times = [op[k] for k in ['queue_entered_at','start','processing_start','processed_at','transferred_at'] if op[k] is not None]
            assert times == sorted(times) and all(t < h for t in times)
            if i:
                assert j['operations'][i-1]['processed_at'] <= op['queue_entered_at']
                assert j['operations'][i-1]['transferred_at'] == op['queue_entered_at']
        if j['completion_time'] is not None:
            assert len(j['operations']) == len(route)
            assert j['operations'][-1]['transferred_at'] == j['completion_time'] < h
    processing = setup = blocked = 0.0
    for machine in result['machines']:
        intervals = machine['intervals']
        assert intervals[0]['time'] == 0 and intervals[-1]['end'] == h
        assert all(abs(a['end']-b['time']) < 1e-9 for a,b in zip(intervals, intervals[1:]))
        assert abs(sum(x['end']-x['time'] for x in intervals)-h)<1e-7
        processing += sum(x['end']-x['time'] for x in intervals if x['state']=='processing')
        setup += sum(x['end']-x['time'] for x in intervals if x['state']=='setup')
        blocked += sum(x['end']-x['time'] for x in intervals if x['state']=='blocked')
        operations = sorted([(op['start'], op, j) for j in jobs for op in j['operations'] if op.get('machine')==machine['name']],key=lambda x:x[0])
        for (_, a, j), (start, b, k) in zip(operations, operations[1:]):
            assert a['transferred_at'] is not None and a['transferred_at'] <= start
    revenue = sum(prices[p]*v['completed'] for p,v in products.items())
    pc, sc = processing/60*100, setup/60*100
    contribution = revenue-pc-sc
    assert math.isclose(contribution, result['summary']['operating_contribution'],abs_tol=1e-7)
    assert sum(p['arrived'] for p in products.values()) == result['summary']['arrived']
    assert all(p['arrived']==p['completed']+p['external']+p['wip'] for p in products.values())
    return {'operating_contribution': contribution, 'revenue': revenue, 'processing_cost': pc,
            'setup_cost': sc, 'completed': sum(p['completed'] for p in products.values()),
            'external': sum(p['external'] for p in products.values()), 'wip': sum(p['wip'] for p in products.values()),
            'blocked_minutes':blocked, 'products': products, 'checks_passed':True}


def run_one(path, seed, raw_path=None):
    start = time.monotonic()
    policy = Policy(path)
    try:
        sim = ControlledSimulation(SimulationConfig(), seed, policy)
        result = sim.run()
        metrics = audit(result)
        assert sim.tokens == metrics['wip'], 'CONWIP token conservation'
        if raw_path:
            raw_path=Path(raw_path);raw_path.parent.mkdir(parents=True,exist_ok=True)
            with gzip.open(raw_path, 'xt', encoding='utf8') as f:
                json.dump(result, f, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        return {**metrics,'seconds':time.monotonic()-start,'decisions':policy.calls,
                'action_trace_sha256':policy.digest.hexdigest(),
                'raw_sha256':sha(raw_path) if raw_path else None}, result
    finally:
        policy.close()
