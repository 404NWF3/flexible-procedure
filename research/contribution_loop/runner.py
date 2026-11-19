"""One bounded research campaign. Validation and confirmation run without feedback."""
import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import secrets
import statistics
import sys
from pathlib import Path
from scipy.stats import t
from evaluator import ROOT, OUT, atomic_json, sha, run_one

HERE=Path(__file__).resolve().parent
SEARCH=ROOT/'search_workspace'
STATE=OUT/'state.json'
LEDGER=OUT/'evaluator/ledger/events.jsonl'
SITE=Path('/workspace/sites/contribution-loop-20261022/dist')


def now():return dt.datetime.now(dt.timezone.utc).isoformat()


def load():return json.loads(STATE.read_text())


def event(s, kind, **values):
    row={'at':now(),'kind':kind,**values,'previous_sha256':s.get('last_event_sha256','0'*64)}
    digest=hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    row['sha256']=digest
    with LEDGER.open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
    s['last_event_sha256']=digest
    s.setdefault('events',[]).append(row)
    s['updated_at']=row['at']


def publish(s):
    atomic_json(STATE,s)
    public={k:v for k,v in s.items() if k not in ['private_banks']}
    atomic_json(SITE/'progress.json',public)
    (SITE/'progress.js').write_text('window.INITIAL_PROGRESS='+json.dumps(public,ensure_ascii=False,allow_nan=False)+';\n')


def fingerprint():
    paths=list((ROOT/'src/soft_procedure').rglob('*.py'))+list(HERE.glob('*.py'))+[OUT/'loop_contract.json']
    return {str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)}


def verify(s):
    for p,digest in s['freeze']['files'].items():
        if sha(ROOT/p)!=digest:raise RuntimeError('frozen evaluator changed: '+p)
    for c in s['candidates']:
        if sha(ROOT/c['source'])!=c['bundle_sha256']:raise RuntimeError('frozen candidate changed: '+c['id'])


def stats(values):
    n=len(values);avg=statistics.mean(values);sd=statistics.stdev(values) if n>1 else 0
    half=float(t.ppf(.975,n-1))*sd/(n**.5) if n>1 else None
    return {'n':n,'mean':avg,'sd':sd,'ci95':None if half is None else [avg-half,avg+half]}


def aggregate(rows):
    result={k:stats([r[k] for r in rows]) for k in ['operating_contribution','revenue','processing_cost','setup_cost','completed','external','wip','blocked_minutes']}
    result['products']={p:{k:statistics.mean([r['products'][p][k] for r in rows]) for k in ['arrived','completed','external','wip','unfinished','unfinished_max_age']} for p in ['P1','P2','P3','P4']}
    return result


def register(s, item, reference=False):
    cid=item['id']
    if any(c['id']==cid for c in s['candidates']):raise ValueError('duplicate id')
    if not reference and sum(not c.get('reference') for c in s['candidates'])>=24:raise ValueError('candidate budget exhausted')
    params=item['parameters']
    path=SEARCH/'candidates'/cid/'policy.py';path.parent.mkdir(parents=True,exist_ok=False)
    source=(HERE/'policy_template.py').read_text().replace('P = {}','P = '+repr(params),1)
    path.write_text(source)
    record={**item,'reference':reference,'source':str(path.relative_to(ROOT)), 'bundle_sha256':sha(path),
        'registered_at':now(),'status':'registered','stages':{},'interface_version':'seccomp-json-v1',
        'training_provenance':'deterministic analytical rules; no external training data',
        'randomization_rule':'deterministic; candidate has no environment seed access',
        'contract_id':'soft-procedure-contribution-loop-v1', 'contract_sha256':sha(OUT/'loop_contract.json'),
        'dependency_lock':s['freeze']['sha256'],'resource_limits':s['resource_limits']}
    atomic_json(path.parent/'submission.json',record)
    s['candidates'].append(record)
    event(s,'registered',candidate=cid,hypothesis=item['hypothesis'],parents=item.get('parents',[]))
    publish(s)
    return record


def work(path,seed,raw):
    try:
        row,_=run_one(path,seed,raw)
        return {'valid':True,**row}
    except Exception as e:
        return {'valid':False,'error':type(e).__name__+': '+str(e)}


def stage(s,c,phase,seeds):
    verify(s)
    if phase in c['stages']:raise ValueError('stage already attempted; no automatic replay')
    c['status']='running';s['phase']=phase;s['active_candidate']=c['id']
    c['stages'][phase]={'status':'running','expected_runs':len(seeds),'rows':[],'started_at':now()}
    event(s,'stage_started',candidate=c['id'],stage=phase,runs=len(seeds));publish(s)
    results={}
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
        tasks={pool.submit(work,ROOT/c['source'],seed,OUT/f'evaluator/raw/{phase}/{c["id"]}/{i:03d}.json.gz'):i for i,seed in enumerate(seeds)}
        for future in concurrent.futures.as_completed(tasks):
            i=tasks[future];row=future.result();row['replication']=i
            results[i]=row
            c['stages'][phase]['rows']=[results[j] for j in sorted(results)]
            s['run_count'][phase]=s['run_count'].get(phase,0)+1
            event(s,'replication_finished',candidate=c['id'],stage=phase,replication=i,valid=row['valid'],contribution=row.get('operating_contribution'),error=row.get('error'))
            # Sealed stages retain receipts privately until terminal disposition.
            atomic_json(STATE,s)
            if phase in ['smoke','development']:publish(s)
    rows=[results[i] for i in range(len(seeds))]
    valid=all(r['valid'] for r in rows)
    st=c['stages'][phase]
    st.update(status='complete' if valid else 'invalid',finished_at=now())
    if valid:st['summary']=aggregate(rows)
    c['status']='complete' if valid else 'invalid'
    if valid and phase=='development':
        base=next(x for x in s['candidates'] if x['id']=='fifo')
        strong=next((x for x in s['candidates'] if x['id']=='same_family'),None)
        for other in [base,strong]:
            if other and 'development' in other['stages'] and other['stages']['development']['status']=='complete':
                ds=[a['operating_contribution']-b['operating_contribution'] for a,b in zip(rows,other['stages']['development']['rows'])]
                st.setdefault('paired',{})[other['id']]=stats(ds)
    event(s,'stage_finished',candidate=c['id'],stage=phase,valid=valid,mean=st.get('summary',{}).get('operating_contribution',{}).get('mean'))
    atomic_json(OUT/f'evaluator/receipts/{phase}-{c["id"]}.json',{'candidate':c['id'],'bundle_sha256':c['bundle_sha256'],'phase':phase,**st})
    atomic_json(STATE,s)
    if phase in ['smoke','development']:
        publish(s)
        print(json.dumps({'candidate':c['id'],'stage':phase,'valid':valid,'mean':st.get('summary',{}).get('operating_contribution',{}).get('mean')},ensure_ascii=False),flush=True)
    return valid


def init():
    if STATE.exists():raise ValueError('campaign already exists')
    replay=json.loads((OUT/'evaluator/reference_replay.json').read_text())
    boundary=json.loads((OUT/'evaluator/boundary_tests.json').read_text())
    assert boundary['passed'] and len(replay)==6 and all(r['exact_trajectory_replay'] for r in replay)
    assert '\nOK\n' in (OUT/'evaluator/original-tests-network.log').read_text()
    frozen=fingerprint();digest=hashlib.sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest()
    private=OUT/'evaluator/private';private.mkdir(mode=0o700,exist_ok=True)
    banks={};used=set(range(42,52))|set(range(1000,1030))|set(range(2000,6000))
    for phase,n in [('validation',50),('confirmation',100)]:
        bank=[]
        while len(bank)<n:
            value=secrets.randbits(63)
            if value not in used:bank.append(value);used.add(value)
        banks[phase]=bank
    atomic_json(private/'seeds.json',banks);os.chmod(private/'seeds.json',0o600)
    seed_commitments={k:hashlib.sha256(json.dumps(v,separators=(',',':')).encode()).hexdigest() for k,v in banks.items()}
    s={'schema_version':1,'campaign_id':'contribution-loop-20261022-01','campaign_index':1,
       'objective':'每 2400 工作分钟经营贡献最大化','started_at':now(),'updated_at':now(),
       'phase':'ready','status':'running','active_candidate':None,'candidates':[],'events':[],
       'run_count':{},'budgets':{'candidates':24,'smoke':72,'development':780,'validation':250,'confirmation':300},
       'resource_limits':{'decision_cpu_ms':250,'decision_wall_ms':1000,'path_cpu_s':120,'path_wall_s':300,'memory_mib':2048},
       'freeze':{'sha256':digest,'files':frozen},'seed_commitments':seed_commitments,
       'gates':{'reference_replay':'6 条完整轨迹逐字段一致','original_tests':'38/38 通过','boundary_tests':'5/5 通过','os_boundary':'seccomp allowlist + isolated process; no files/network/other processes'},
       'limitations':['空系统起步的40小时窗口；长期收益未验证','经营贡献不是完整净利润','无合同保供门槛；分产品交付与积压完整披露','本轮开放固定机器顺序下的派工、准入排序、全线CONWIP与截止放行；未实现联合多机匹配和在线学习']}
    atomic_json(OUT/'evaluator/ready_receipt.json',{'ready':True,'at':now(),'interface_version':'seccomp-json-v1','evaluator_sha256':digest,'seed_commitments':seed_commitments,'checks':s['gates'],'limitations':s['limitations']})
    atomic_json(OUT/'evaluator/alpha_ledger.json',{'research_line':'soft-procedure-contribution','campaign_index':1,'alpha_total':.05,'alpha_reserved':.025,'spent_on_confirmation':False,'reset_after_rebaseline':False})
    event(s,'ready',message='基准、计量与OS隔离检查通过；可信评测层已冻结')
    publish(s)
    for cid,params in [('fifo',{}),('same_family',{'dispatch':'family'})]:
        c=register(s,{'id':cid,'label':'FIFO 对照' if cid=='fifo' else '同类优先对照','parents':[], 'hypothesis':'冻结参考策略','mechanism':'reference','parameters':params,'expected_tradeoffs':'保留原参考策略行为'},reference=True)
        stage(s,c,'development',list(range(1000,1030)))
    s['phase']='development';s['active_candidate']=None;publish(s)


def batch(path):
    s=load();verify(s)
    if s.get('sealed'):raise ValueError('campaign is sealed')
    for item in json.loads(Path(path).read_text()):
        c=register(s,item)
        if stage(s,c,'smoke',[42,43,44]):stage(s,c,'development',list(range(1000,1030)))
    s['active_candidate']=None;publish(s)


def seal():
    s=load();verify(s)
    if s.get('sealed'):raise ValueError('already sealed')
    eligible=[c for c in s['candidates'] if not c['reference'] and c['stages'].get('development',{}).get('status')=='complete']
    eligible.sort(key=lambda c:(-c['stages']['development']['summary']['operating_contribution']['mean'],c['id']))
    selected=eligible[:3];refs=[c for c in s['candidates'] if c['reference']]
    s['sealed']=True;s['phase']='validation';s['sealed_at']=now();s['sealed_candidates']=[c['id'] for c in selected]
    event(s,'sealed',candidates=s['sealed_candidates'],message='候选一次性冻结；封闭阶段不向搜索过程回传结果')
    publish(s)
    banks=json.loads((OUT/'evaluator/private/seeds.json').read_text())
    for c in refs+selected:stage(s,c,'validation',banks['validation'])
    valid=[c for c in refs+selected if c['stages']['validation']['status']=='complete']
    tie=lambda c:0 if c['id']=='same_family' else 1 if c['id']=='fifo' else 2
    winner=min(valid,key=lambda c:(-c['stages']['validation']['summary']['operating_contribution']['mean'],tie(c),c['id']))
    participants=refs+([] if winner['reference'] else [winner])
    s['winner']=winner['id'];s['phase']='confirmation'
    contrasts=[c for c in refs if c['id']!=winner['id']]
    alpha=.025/len(contrasts)
    quantile=float(t.ppf(1-alpha,99))
    atomic_json(OUT/'evaluator/confirmation_preregistration.json',{'winner':winner['id'],'source_sha256':winner['bundle_sha256'],'comparisons':[c['id'] for c in contrasts],'alpha_campaign':.025,'alpha_per_comparison':alpha,'quantile':quantile,'n':100,'seed_commitment':s['seed_commitments']['confirmation'],'at':now()})
    for c in participants:stage(s,c,'confirmation',banks['confirmation'])
    final={};valid_final=all(c['stages']['confirmation']['status']=='complete' for c in participants)
    if valid_final:
        for other in contrasts:
            a=winner['stages']['confirmation']['rows'];b=other['stages']['confirmation']['rows']
            ds=[x['operating_contribution']-y['operating_contribution'] for x,y in zip(a,b)]
            st=stats(ds);st['formal_lower']=st['mean']-quantile*st['sd']/10;st['alpha']=alpha
            st['decomposition']={k:statistics.mean([x[k]-y[k] for x,y in zip(a,b)]) for k in ['revenue','processing_cost','setup_cost']}
            final[other['id']]=st
    s['final_comparisons']=final
    s['outcome']=('invalid_candidate' if not valid_final else 'no_new_gain' if winner['reference'] else 'confirmed_finite_horizon_gain' if all(v['formal_lower']>0 for v in final.values()) else 'insufficient_evidence')
    s['status']='completed';s['phase']='completed';s['active_candidate']=None;s['finished_at']=now()
    event(s,'campaign_finished',outcome=s['outcome'],winner=winner['id'],message='已到一次最终确认终点，停止搜索；未自动开启新周期')
    atomic_json(OUT/'evaluator/alpha_ledger.json',{'research_line':'soft-procedure-contribution','campaign_index':1,'alpha_total':.05,'alpha_reserved':.025,'spent_on_confirmation':True,'reset_after_rebaseline':False})
    publish(s)
    print(json.dumps({'outcome':s['outcome'],'winner':s['winner'],'comparisons':final},ensure_ascii=False),flush=True)


if __name__=='__main__':
    command=sys.argv[1]
    if command=='init':init()
    elif command=='batch':batch(sys.argv[2])
    elif command=='seal':seal()
    else:raise ValueError(command)
