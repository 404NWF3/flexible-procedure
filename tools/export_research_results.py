"""Validate and export the completed ten-year research campaign."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import mean

from soft_procedure.experiments import estimate


def csv_file(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('campaign',type=Path)
    args=parser.parse_args()
    p=args.campaign
    d=json.loads((p/'research.json').read_text())
    assert d['status']=='complete','Campaign has not finished'
    previous='0'*64
    for line in (p/'ledger.jsonl').read_text().splitlines():
        e=json.loads(line);actual=e.pop('hash')
        assert e['previous']==previous
        assert hashlib.sha256(json.dumps(e,sort_keys=True,ensure_ascii=False).encode()).hexdigest()==actual
        previous=actual
    assert previous==d['ledger_head']
    rs=[r for r in d['runs'] if r['stage']=='confirmation']
    frozen=json.loads((p/'frozen_finalists.json').read_text())
    assert {(r['design'],r['seed']) for r in rs}=={(id,s) for id in frozen for s in d['protocol']['confirmation_seeds']}
    for r in rs:
        s=r['summary']
        assert r['horizon']==1_200_000
        assert s['arrived']==s['completed']+s['external']+s['wip']
        assert sum(v['completed'] for v in r['products'].values())==s['completed']
        assert sum(v['arrived'] for v in r['products'].values())==s['arrived']
        assert abs(s['net']-(s['revenue']-s['operating_cost']-s['capex']))<1e-6
        assert abs(s['capital_allocated']-s['capex'])<1e-6
        assert s['unrecovered_principal']==0
        for v in r['products'].values():assert v['arrived']==v['completed']+v['unfinished']
        for st in r['stations']:assert abs(sum(st['states'].values())-1)<1e-9
        if frozen[r['design']]['regime']=='none':assert not r['purchases']
        if frozen[r['design']]['regime']=='upfront':assert all(v['time']==0 for v in r['purchases'])
        if frozen[r['design']]['regime']=='dynamic':assert all(v['time']>0 for v in r['purchases'])
    summaries=[];products=[];states=[];times=[];buy=[]
    for id,design in frozen.items():
        group=[r for r in rs if r['design']==id]
        row={'design':id,'regime':design['regime'],'n':len(group)}
        for metric in ('revenue','operating_cost','capex','net','tv','arrived','completed','external','wip','mean_cycle_time','unrecovered_principal'):
            stat=estimate([r['summary'][metric] for r in group])
            row[metric]=stat['mean'];row[metric+'_ci95_half_width']=stat['ci95']
        row['machine_counts']='/'.join(str(mean(r['summary']['machine_counts'][n] for r in group)) for n in ('M1','M2','M3','M4','M5'))
        summaries.append(row)
        for prod in ('P1','P2','P3','P4'):
            q=mean(r['products'][prod]['completed'] for r in group)
            a=mean(r['products'][prod]['arrived'] for r in group)
            products.append({'design':id,'product':prod,'completed_mean':q,
                'completed_ci95_half_width':estimate([r['products'][prod]['completed'] for r in group])['ci95'],
                'output_share':q/row['completed'],'arrived_mean':a,'arrival_share':a/row['arrived'],
                'completion_rate':q/a,'unfinished_mean':a-q,
                'unfinished_max_age_working_days':max(r['products'][prod]['unfinished_max_age'] for r in group)/480})
        for i,n in enumerate(('M1','M2','M3','M4','M5')):
            states.append({'design':id,'station':n,
                **{k:mean(r['stations'][i]['states'][k] for r in group) for k in ('processing','setup','repair','blocked','idle')},
                'mean_queue':mean(r['stations'][i]['mean_queue'] for r in group),
                'mean_wait_minutes':mean(r['stations'][i]['mean_wait'] or 0 for r in group)})
        for r in group:
            for t in r['timeline']:
                times.append({'design':id,'seed':r['seed'],'year':t['time']/120000,
                              **{k:t[k] for k in ('completed','external','revenue','operating_cost','capex','capital_allocated','net')}})
            for b in r['purchases']:buy.append({'design':id,'seed':r['seed'],**b})
    csv_file(p/'ten_year_summary.csv',summaries)
    csv_file(p/'ten_year_products.csv',products)
    csv_file(p/'ten_year_stations.csv',states)
    csv_file(p/'yearly_records.csv',times)
    if buy:csv_file(p/'purchases.csv',buy)
    csv_file(p/'regularization_choices.csv',d['selected'])
    comparisons=[]
    for a,b in [('N03','N02'),('V1m','N03'),('D00','V1m')]:
        ga={r['seed']:r for r in rs if r['design']==a}
        gb={r['seed']:r for r in rs if r['design']==b}
        if ga.keys()==gb.keys() and ga:
            stat=estimate([ga[s]['summary']['net']-gb[s]['summary']['net'] for s in sorted(ga)])
            comparisons.append({'contrast':a+' minus '+b,**stat})
    csv_file(p/'paired_net_differences.csv',comparisons)
    print('PASS: full horizon, frozen design/seed matrix, hash chain, product/physical accounting, full capital repayment and purchase regime restrictions')
    print(json.dumps({'summaries':summaries,'products':products,'selected':d['selected'],'paired':comparisons},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
