"""Bounded autoresearch: register -> screen -> change one capacity -> validate -> freeze -> confirm.

All short runs are explicitly proxies, never reported as ten-year simulations.
Every result is persisted immediately in a hash-chained append-only ledger.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import gc
import json
from pathlib import Path
import platform
import subprocess

from soft_procedure.config import SimulationConfig
from soft_procedure.experiments import estimate
from soft_procedure.research import Design, ResearchSimulation

H=1_200_000
LAMBDAS=(0,10_000_000,30_000_000,100_000_000)


def execute(design,seed,horizon):
    result=ResearchSimulation(Design(**design),seed,horizon=horizon,project_horizon=H).run()
    gc.collect()
    return result


class Campaign:
    def __init__(self,path,site,workers,resume=False):
        self.path,self.site,self.workers=path,site,workers
        if resume:
            saved=json.loads((path/'research.json').read_text())
            keys=set(Design.__dataclass_fields__)
            self.designs={n['id']:{k:v for k,v in n.items() if k in keys} for n in saved['nodes']}
            self.records=saved['runs']
            self.chain=saved['ledger_head']
            self.status='running'
            self.phase=saved['phase']
            self.protocol=saved['protocol']
            amendment={"kind":"executor_recovery","reason":"Python 3.12 ProcessPoolExecutor recycling stalled after 3 tasks per worker. Removed worker recycling; identical model, candidates and seeds; retained all completed runs.","runner_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
            self.event(amendment)
            self.save()
            return
        path.mkdir(parents=True,exist_ok=False)
        self.designs={}
        self.records=[]
        self.chain="0"*64
        self.status="running"
        self.phase="registration"
        root=Path(__file__).resolve().parents[1]
        files=sorted((root/'src').rglob('*.py'))+[Path(__file__).resolve()]
        self.protocol={
            "horizon_minutes":H,"working_days_per_year":250,"hours_per_day":8,
            "lambdas":LAMBDAS,"screen_seeds":[1000],"validation_seeds":[2000,2001],
            "confirmation_seeds":[70001,70002,70003],
            "base_config":SimulationConfig().to_dict(),"python":platform.python_version(),
            "git_commit":subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
            "sources":{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            "accounting":"J = revenue - actual processing/setup operating cost - all new machine purchase cost. Existing 8 machines are sunk. Zero interest, unconstrained funding; all principal recovered by H required.",
            "allocation":"Project-specific straight-line allocation over [purchase_time,H]; zero residual. Allocation is a presentation ledger, never deducted twice from J.",
            "regularizer":"TV = 0.5*sum(abs(completed_share-final_realized_arrival_share)); J_lambda=J-lambda*TV. Zero completions gives TV=1. Final arrivals are evaluation-only.",
            "causality":"Policy receives frozen JobView and DecisionView only. No seed, future arrivals, true required work, remaining failure life or event queue. Dynamic investment uses past active time and current backlog only.",
            "search_budget":"Initial rules/capacities, <=10 single-station capacity neighbors; 30000-minute development proxies; 120000-minute validation proxies; up to 6 finalists, 3 full 1200000-minute confirmation repetitions each. No globally optimal claim.",
            "limitations":["Working-time calendar; no overnight repairs or seasonality.","No debt interest/credit limit, acquisition lead time, demand caps, machine aging or physical replacement.","Prices and operating charges stay at case defaults; no unprovided material/labor/tax costs.","Policies are reviewed fixed rules with typed observations, not adversarial OS-isolated submitted programs.","Short-run proxy selection can miss policies whose merit appears only after long transients."]}
        (path/'protocol.json').write_text(json.dumps(self.protocol,ensure_ascii=False,indent=2))
        self.save()

    def register(self,d):
        if d.id in self.designs:
            assert json.dumps(self.designs[d.id],sort_keys=True)==json.dumps(asdict(d),sort_keys=True)
            return
        self.designs[d.id]=asdict(d)
        self.event({"kind":"register","design":asdict(d)})

    def event(self,payload):
        event={"at":datetime.now(timezone.utc).isoformat(),"previous":self.chain,**payload}
        self.chain=hashlib.sha256(json.dumps(event,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        event['hash']=self.chain
        with (self.path/'ledger.jsonl').open('a') as f:
            f.write(json.dumps(event,ensure_ascii=False)+'\n')

    def metrics(self,design,stage):
        rs=[r for r in self.records if r['design']==design and r['stage']==stage and 'summary' in r]
        if not rs: return None
        net=[r['summary']['net'] for r in rs]
        if stage!='confirmation':
            net=[(r['summary']['revenue']-r['summary']['operating_cost'])*H/r['horizon']-
                 (max(0,sum(self.designs[design]['counts'])-8)*500000 if self.designs[design]['regime']=='dynamic' else r['summary']['capex']) for r in rs]
        return {"n":len(rs),"net":estimate(net),"tv":estimate([r['summary']['tv'] for r in rs]),
                "completed":estimate([r['summary']['completed'] for r in rs]),
                "capex":estimate([r['summary']['capex'] for r in rs])}

    def choose(self,stage,per_regime=1):
        chosen=set()
        for regime in ('none','upfront','dynamic'):
            eligible=[(id,self.metrics(id,stage)) for id,d in self.designs.items() if d['regime']==regime]
            eligible=[(id,m) for id,m in eligible if m]
            for lam in (0,100_000_000):
                ranked=sorted(eligible,key=lambda x:x[1]['net']['mean']-lam*x[1]['tv']['mean'],reverse=True)
                chosen.update(id for id,_ in ranked[:per_regime])
        return sorted(chosen)

    def save(self):
        nodes=[]
        for id,d in self.designs.items():
            phases={s:self.metrics(id,s) for s in ('screen','validation','confirmation')}
            nodes.append({**d,"stages":{k:v for k,v in phases.items() if v}})
        summaries=[]
        for regime in ('none','upfront','dynamic'):
            candidates=[n for n in nodes if n['regime']==regime and 'confirmation' in n['stages']]
            for lam in LAMBDAS:
                if candidates:
                    winner=max(candidates,key=lambda n:n['stages']['confirmation']['net']['mean']-lam*n['stages']['confirmation']['tv']['mean'])
                    summaries.append({"regime":regime,"lambda":lam,"design":winner['id'],"score":winner['stages']['confirmation']['net']['mean']-lam*winner['stages']['confirmation']['tv']['mean']})
        bundle={"title":"柔性产线 · 十年收益实验树","status":self.status,"phase":self.phase,
                "updated_at":datetime.now(timezone.utc).isoformat(),"protocol":self.protocol,
                "ledger_head":self.chain,"nodes":nodes,"runs":self.records,"selected":summaries}
        text=json.dumps(bundle,ensure_ascii=False,indent=2,allow_nan=False)
        tmp=self.path/'research.tmp'
        tmp.write_text(text)
        tmp.replace(self.path/'research.json')
        if self.site:
            self.site.mkdir(parents=True,exist_ok=True)
            temp=self.site/'research.tmp'
            temp.write_text(text)
            temp.replace(self.site/'research.json')

    def run(self,ids,seeds,horizon,stage):
        self.phase=stage
        self.event({"kind":"stage_start","stage":stage,"designs":ids,"seeds":seeds,"horizon":horizon})
        self.save()
        done={(r['design'],r['seed']) for r in self.records if r['stage']==stage}
        with ProcessPoolExecutor(max_workers=self.workers) as pool:
            futures={pool.submit(execute,self.designs[id],seed,horizon):(id,seed) for id in ids for seed in seeds if (id,seed) not in done}
            for f in as_completed(futures):
                id,seed=futures[f]
                try:
                    r=f.result()
                    r['stage']=stage
                    self.records.append(r)
                    (self.path/f'{stage}_{id}_{seed}.json').write_text(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False))
                    self.event({"kind":"run_complete","stage":stage,"design":id,"seed":seed,"net":r['summary']['net'],"tv":r['summary']['tv'],"seconds":r['seconds']})
                    self.save()
                    print(f"{stage} {id} seed={seed} completed={r['summary']['completed']} net={r['summary']['net']:,.0f} TV={r['summary']['tv']:.4f} seconds={r['seconds']:.1f}",flush=True)
                except Exception as exc:
                    self.event({"kind":"run_failed","stage":stage,"design":id,"seed":seed,"error":repr(exc)})
                    self.status='failed'
                    self.save()
                    raise


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--site-dist',type=Path)
    p.add_argument('--workers',type=int,default=3)
    p.add_argument('--resume',action='store_true')
    args=p.parse_args()
    c=Campaign(args.output,args.site_dist,args.workers,args.resume)
    root=Design('N00',rule='fifo',admission='fifo',change='原始 FIFO 与准入规则；固定8台')
    c.register(root)
    for i,(rule,admission,fairness) in enumerate([
        ('family','fifo',0),('family','internal',0),('hybrid','value',0),
        ('family','value',5),('family','value',20),('family','value',100),
        ('hybrid','value',5),('hybrid','value',20),('hybrid','value',100)],1):
        c.register(Design(f'N{i:02}',parent='N00',rule=rule,admission=admission,fairness=fairness,
                          change=f'派工={rule}；准入={admission}；在线产品欠产权重={fairness}'))
    vectors=[(5,6,7,6,7),(5,6,7,7,8),(6,7,8,7,8),(6,7,8,8,9),(7,8,9,9,10)]
    for i,counts in enumerate(vectors):
        for fair in (0,20):
            id=f'U{i:02}F{fair}'
            c.register(Design(id,parent='N02',regime='upfront',counts=counts,fairness=fair,
                              change=f'期初购机至{counts}；欠产权重={fair}'))
    for i,(threshold,review,fair) in enumerate([(0.7,2400,0),(0.85,2400,0),(0.95,2400,0),(0.85,9600,0),(0.7,2400,20),(0.85,2400,20),(0.95,2400,20),(0.85,9600,20)]):
        c.register(Design(f'D{i:02}',parent='N02',regime='dynamic',counts=(7,8,9,9,10),fairness=fair,
                          buy_threshold=threshold,review_minutes=review,
                          change=f'按已观察利用率≥{threshold}、当前积压>10，每{review}分钟复核，每工位每次最多添1台；欠产权重={fair}'))
    c.run(list(c.designs),[1000],30000,'screen')
    upfront=max((id for id,d in c.designs.items() if d['regime']=='upfront'),key=lambda id:c.metrics(id,'screen')['net']['mean'])
    best=Design(**c.designs[upfront])
    neighbors=[]
    for station in range(5):
        for delta in (-1,1):
            counts=list(best.counts)
            counts[station]+=delta
            if counts[station]<(2,1,2,1,2)[station]:continue
            id=f'V{station}{"m" if delta<0 else "p"}'
            c.register(replace(best,id=id,parent=upfront,counts=tuple(counts),change=f'仅修改 M{station+1} 机床数 {delta:+d}'))
            neighbors.append(id)
    c.run(neighbors,[1000],30000,'screen')
    validation=c.choose('screen',per_regime=2)
    c.run(validation,[2000,2001],120000,'validation')
    finalists=c.choose('validation')
    c.event({"kind":"freeze","designs":{id:c.designs[id] for id in finalists},"confirmation_seeds":[70001,70002,70003]})
    (c.path/'frozen_finalists.json').write_text(json.dumps({id:c.designs[id] for id in finalists},ensure_ascii=False,indent=2))
    c.run(finalists,[70001,70002,70003],H,'confirmation')
    c.status='complete'
    c.phase='complete'
    c.event({"kind":"complete","message":"Bounded campaign complete; best tested policies, not a global optimum."})
    c.save()
    print('CAMPAIGN COMPLETE',args.output,flush=True)


if __name__=='__main__':
    main()
