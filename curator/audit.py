"""Recompute the old four-arm results from mounted original artifacts; no paid requests."""
import argparse
import hashlib
import zipfile
from collections import Counter
from pathlib import Path
from .core import loads,dumps,ExperimentError

def audit(paths):
    arms={};hashes={}
    for path in map(Path,paths):
        with zipfile.ZipFile(path) as z:
            if sum(x.file_size for x in z.infolist())>20_000_000:raise ExperimentError("oversized_archive")
            plan=loads(z.read('plan.json').decode());rows=[loads(x) for x in z.read('jev/results.jsonl').decode().splitlines() if x]
            cases=[loads(x) for x in z.read('cases.jsonl').decode().splitlines() if x]
        variant=plan['variant']
        if variant in arms:raise ExperimentError('duplicate_arm')
        if len(rows)!=90 or {x['case_id'] for x in rows}!={x['case_id'] for x in cases}:raise ExperimentError('old_case_set_mismatch')
        correct=lambda r:r['status']=='ok' and all(r['answers'].get(k,{}).get('choice') in g for k,g in r['gold'].items())
        hi=[r for r in rows if r['status']=='ok' and all(a.get('pmax',0)>=.9 for a in r['answers'].values())]
        arms[variant]={'n':len(rows),'correct':sum(map(correct,rows)),'groups':len({r['group_id'] for r in rows}),
                       'high_pmax_n':len(hi),'high_pmax_errors':sum(not correct(r) for r in hi),
                       'by_language':{l:sum(correct(r) for r in rows if r['language']==l) for l in ('zh','en','mixed')},
                       'critical_errors':[r['case_id'] for r in rows if r.get('critical') and not correct(r)],
                       'input_tokens':sum(r['usage']['input_tokens'] for r in rows),
                       'estimated_cost_usd':sum(r['cost_usd'] for r in rows),
                       'predictions':{r['case_id']:{k:a['choice'] for k,a in r['answers'].items()} for r in rows},
                       'model_versions':sorted({r['response_model'] for r in rows})}
        hashes[variant]=hashlib.sha256(path.read_bytes()).hexdigest()
    if set(arms)!={'base','reverse_options','injection','distractor'}:raise ExperimentError('four_arms_required')
    for k,a in arms.items():
        a['flips_vs_base']=[cid for cid,p in a['predictions'].items() if p!=arms['base']['predictions'][cid]]
    for a in arms.values():a.pop('predictions')
    return {'source_commit':'a75039b887a99ee6f1bb964ce3bfc561879669cd','archive_sha256':hashes,'arms':arms,
            'total_observations':sum(a['n'] for a in arms.values()),'original_groups_not_360':30,
            'high_pmax_observations':sum(a['high_pmax_n'] for a in arms.values()),
            'estimated_cost_usd':sum(a['estimated_cost_usd'] for a in arms.values()),
            'limits':['One run per arm; identical-input repeat control absent.','Synthetic author-provisional labels, paired languages and variants.','No long-context or downstream task success evidence.','High-probability zero-error observations are correlated, not independent reliability trials.']}

def main():
    p=argparse.ArgumentParser();p.add_argument('archives',nargs=4);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.out.exists():raise ExperimentError('output_exists')
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(dumps(audit(a.archives)),encoding='utf-8')
if __name__=='__main__':main()
