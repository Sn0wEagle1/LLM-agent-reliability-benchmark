"""Табличные показатели и парные сравнения по сохранённым журналам."""
import argparse
from collections import defaultdict
import csv,json,math,statistics
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def read(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]

def rates(rows):
    grouped=defaultdict(list)
    for row in rows:grouped[row['task']].append(row['success'])
    return {t:statistics.mean(v) for t,v in grouped.items()}

def sign_test(a,b):
    x,y=rates(a),rates(b)
    if set(x)!=set(y):raise ValueError('Наборы задач не совпадают')
    better=sum(x[t]>y[t] for t in x);worse=sum(x[t]<y[t] for t in x)
    n=better+worse
    p=min(1.,2*sum(math.comb(n,i) for i in range(min(better,worse)+1))/2**n) if n else 1.
    return dict(better=better,worse=worse,ties=len(x)-n,p=p)

def prevented(event):
    by=event['detected_by']
    if event['stage']=='answer':return by not in (None,'IS')
    return by in ('data_control','deterministic','restriction','confirmation')

def summary(rows):
    n=len(rows);events=[e for r in rows for e in r['events']]
    blocked=sum(prevented(e) for e in events)
    detected=sum(e['detected_by'] not in (None,'IS') for e in events)
    corrected=sum(r['corrected'] for r in rows)
    return dict(runs=n,successful=sum(r['success'] for r in rows),
        success_pct=100*statistics.mean(r['success'] for r in rows),
        state_pct=100*statistics.mean(r['state_ok'] for r in rows),
        errors=len(events),prevented=blocked,unprevented_mean=(len(events)-blocked)/n,
        detected_pct=100*detected/len(events) if events else 0,
        corrected_pct=100*corrected/detected if detected else None,
        time_s=statistics.mean(r['time_s'] for r in rows),
        llm_calls=statistics.mean(r['llm_calls'] for r in rows))

def calculate(results):
    data={name:read(results/(name+'.jsonl')) for name in
          ('main','q8','ablation','holdout','general_df','extra_seed')}
    report={}
    for series,rows in data.items():
        report[series]={key:summary([r for r in rows if r['config']==key])
                        for key in sorted({r['config'] for r in rows})}
    base=[r for r in data['main'] if r['config']=='base']
    det=[r for r in data['main'] if r['config']=='det_rules2']
    hb=[r for r in data['holdout'] if r['config']=='base']
    report['comparisons']={
        'main_vs_base':{key:sign_test([r for r in data['main'] if r['config']==key],base) for key in report['main']},
        'holdout_vs_base':{key:sign_test([r for r in data['holdout'] if r['config']==key],hb) for key in report['holdout']},
        'general_vs_base':sign_test(data['general_df'],base),
        'general_vs_full_df':sign_test(data['general_df'],det)}
    five=base+data['extra_seed'];grouped=defaultdict(list)
    for row in five:grouped[row['task']].append(row)
    if any(len(v)!=5 or len({r['seed'] for r in v})!=5 for v in grouped.values()):
        raise ValueError('Для базовой конфигурации требуется пять seed на задачу')
    report['five_seeds']={**summary(five),
        'stable_tasks':[t for t,v in grouped.items() if len({r['success'] for r in v})==1],
        'always_successful':sum(all(r['success'] for r in v) for v in grouped.values()),
        'always_failed':sum(not any(r['success'] for r in v) for v in grouped.values())}
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results',type=Path,default=ROOT/'results')
    p.add_argument('--out',type=Path,default=ROOT/'analysis')
    args=p.parse_args();report=calculate(args.results)
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    fields=['series','config',*report['main']['base']]
    with (args.out/'tables.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for series in ('main','q8','ablation','holdout','general_df','extra_seed'):
            for cfg,values in report[series].items():writer.writerow(dict(series=series,config=cfg,**values))
    print(args.out/'summary.json')

if __name__=='__main__':main()
