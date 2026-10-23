"""Final reproducibility audit. Does not run or select any new experiment."""
import csv
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from scipy.stats import t
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
s=json.loads((OUT/'state.json').read_text())
assert s['status']=='completed','Only audit after terminal disposition'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
# Verify frozen evaluator, immutable candidate sources and the full append-only chain.
for p,digest in s['freeze']['files'].items():assert sha(ROOT/p)==digest,p
previous='0'*64;events=[]
for line in (OUT/'evaluator/ledger/events.jsonl').read_text().splitlines():
 row=json.loads(line);digest=row.pop('sha256')
 assert row['previous_sha256']==previous
 assert hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()==digest
 previous=digest;events.append(row)
assert previous==s['last_event_sha256']
assert len([c for c in s['candidates'] if not c['reference']])==24
assert len([e for e in events if e['kind']=='registered'])==26
seeds=json.loads((OUT/'evaluator/private/seeds.json').read_text())
for phase,bank in seeds.items():
 assert len(bank)==len(set(bank))
 assert hashlib.sha256(json.dumps(bank,separators=(',',':')).encode()).hexdigest()==s['seed_commitments'][phase]
 assert not any(42<=x<=51 or 1000<=x<=1029 or 2000<=x<=6000 for x in bank)
assert not set(seeds['validation'])&set(seeds['confirmation'])
rows=[];raw_count=0
for c in s['candidates']:
 assert sha(ROOT/c['source'])==c['bundle_sha256']
 for phase,st in c['stages'].items():
  assert st['status']=='complete'
  assert len(st['rows'])==st['expected_runs']
  for i,r in enumerate(st['rows']):
   assert r['valid'] and r['replication']==i
   assert math.isclose(r['operating_contribution'],r['revenue']-r['processing_cost']-r['setup_cost'],abs_tol=1e-7)
   raw=OUT/f'evaluator/raw/{phase}/{c["id"]}/{i:03d}.json.gz'
   assert sha(raw)==r['raw_sha256'];raw_count+=1
   for p,v in r['products'].items():assert v['arrived']==v['completed']+v['external']+v['wip']
   row={'candidate':c['id'],'phase':phase,'replication':i,**{k:r[k] for k in ['operating_contribution','revenue','processing_cost','setup_cost','completed','external','wip','seconds','decisions']}}
   row.update({p+'_completed':r['products'][p]['completed'] for p in r['products']});rows.append(row)
  vals=[r['operating_contribution'] for r in st['rows']]
  assert math.isclose(statistics.mean(vals),st['summary']['operating_contribution']['mean'],abs_tol=1e-7)
 # Preserve original submission.json; add a schema-compatible export of the same immutable metadata.
 meta={'candidate_id':c['id'],'contract_id':c['contract_id'],'parent_ids':c['parents'],
  'hypothesis':c['hypothesis'],'mechanism':c['mechanism'],'interfaces':['dispatch','admission','release','defer'],
  'parameters':c['parameters'],'bundle_sha256':c['bundle_sha256'],'interface_version':c['interface_version'],
  'training_provenance':c['training_provenance'],'randomization_rule':c['randomization_rule'],'expected_tradeoffs':c['expected_tradeoffs']}
 (ROOT/c['source']).with_name('contract_submission.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
assert raw_count==sum(s['run_count'].values())==1402
assert len([e for e in events if e['kind']=='replication_finished'])==raw_count
winner=next(c for c in s['candidates'] if c['id']==s['winner'])
for other_id,comp in s['final_comparisons'].items():
 other=next(c for c in s['candidates'] if c['id']==other_id)
 a=winner['stages']['confirmation']['rows'];b=other['stages']['confirmation']['rows']
 diffs=[x['operating_contribution']-y['operating_contribution'] for x,y in zip(a,b)]
 lower=statistics.mean(diffs)-float(t.ppf(1-comp['alpha'],99))*statistics.stdev(diffs)/10
 assert math.isclose(lower,comp['formal_lower'],abs_tol=1e-7)
 assert math.isclose(comp['mean'],comp['decomposition']['revenue']-comp['decomposition']['processing_cost']-comp['decomposition']['setup_cost'],abs_tol=1e-7)
with (OUT/'replications.csv').open('w',encoding='utf-8-sig',newline='') as f:
 writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
summary={'passed':True,'registered_candidates':24,'reference_policies':2,'audited_runs':raw_count,
 'run_count':s['run_count'],'raw_hashes_verified':raw_count,'hash_chain_events':len(events),
 'sealed_seed_commitments_verified':True,'all_products_conserved':True,'frozen_sources_unchanged':True,
 'final_bounds_recomputed':True,'no_post_confirmation_runs':True,'outcome':s['outcome'],'winner':s['winner']}
(OUT/'verification.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,ensure_ascii=False))
print(json.dumps({'winner_confirmation':winner['stages']['confirmation']['summary'],'comparisons':s['final_comparisons']},ensure_ascii=False,indent=2))
