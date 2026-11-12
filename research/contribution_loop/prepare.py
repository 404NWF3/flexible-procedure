import json
from pathlib import Path
from evaluator import ROOT, OUT, atomic_json, sha, run_one
from soft_procedure.config import SimulationConfig
from soft_procedure.model.simulation import run_simulation

HERE=Path(__file__).resolve().parent
TEMPLATE=(HERE/'policy_template.py').read_text()
references=OUT/'evaluator/references'
references.mkdir(parents=True,exist_ok=True)
for name,params in [('fifo',{}),('same_family',{'dispatch':'family'})]:
    path=references/(name+'.py')
    path.write_text(TEMPLATE.replace('P = {}', 'P = '+repr(params), 1))

if __name__=='__main__':
    checks=[]
    for name in ['fifo','same_family']:
        for seed in [42,43,44]:
            row,new=run_one(references/(name+'.py'),seed,OUT/f'evaluator/preflight/{name}-{seed}.json.gz')
            old=run_simulation(SimulationConfig(policy_name=name),seed)
            # Exact reference trajectories, not just aggregate similarity.
            for k in ['summary','jobs','machines','stations','samples','queue_logs']:
                assert old[k]==new[k], (name,seed,k)
            checks.append({'policy':name,'seed':seed,'seconds':row['seconds'],'contribution':row['operating_contribution'],'exact_trajectory_replay':True})
            print(json.dumps(checks[-1]),flush=True)
    atomic_json(OUT/'evaluator/reference_replay.json',checks)
