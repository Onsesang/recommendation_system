"""Freeze development decisions, then and only then unlock the test split."""
import pandas as pd
import torch
from common import *
from recommender import RecData,new_model,evaluate,setup

MODELS=['popularity','bpr','lightgcn','sasrec','esasrec']

def completed_runs(name):
    if name=='popularity':
        p=ART/'popularity_validation.json'
        return [{'name':name,'lr':None,'best_epoch':0,'validation':load_json(p)}] if p.exists() else []
    return [load_json(p) for p in sorted((ART/'checkpoints').glob(f'{name}_lr*.complete.json'))]

def flatten(name,run,status='complete',reason=''):
    m=run['validation'] if name=='popularity' else run['validation']
    row={'model':name,'status':status,'reason':reason,'learning_rate':run.get('lr'),'best_epoch':run.get('best_epoch')}
    for cohort,values in m.items():
        if isinstance(values,dict):
            for key,val in values.items():row[f'{cohort}.{key}']=val
    return row

def main():
    assert not (ART/'selection_lock.json').exists(),'selection already locked; do not retune after test unlock'
    rows=[];selected={}
    for name in MODELS:
        runs=completed_runs(name)
        if not runs:
            rows.append({'model':name,'status':'N/A','reason':'required validation run not complete'});continue
        run=max(runs,key=lambda x:(x['validation']['all_official_targets']['ndcg_at_10'],x['validation']['all_official_targets']['hr_at_10'],x['validation']['all_official_targets']['mrr_at_10'],-(x.get('lr') or 0)))
        selected[name]=run;rows.append(flatten(name,run))
    assert set(selected)==set(MODELS),f'missing models: {set(MODELS)-set(selected)}'
    table=pd.DataFrame(rows).sort_values('model');table.to_csv(ART/'backbone_validation_results.csv',index=False)
    recalls=[]
    for row in rows:
        for k in (100,300,500,1000,3000):
            recalls.append({'split':'validation','model':row['model'],'k':k,'recall':row.get(f'all_official_targets.recall_at_{k}'),'status':row['status']})
    pd.DataFrame(recalls).to_csv(ART/'candidate_recall.csv',index=False)
    order={name:j for j,name in enumerate(MODELS)}
    winner=max(selected,key=lambda name:(selected[name]['validation']['all_official_targets']['ndcg_at_10'],selected[name]['validation']['all_official_targets']['hr_at_10'],selected[name]['validation']['all_official_targets']['mrr_at_10'],-order[name]))
    vm=selected[winner]['validation']['all_official_targets'];candidate_k=3000
    for k in (100,300,500,1000,3000):
        if vm[f'recall_at_{k}']>=.80:candidate_k=k;break
    lock={'status':'locked_before_any_new_test_evaluation','protocol_sha256':sha(ROOT/'configs/protocol.json'),'strong_backbone':winner,
          'selected_runs':selected,'candidate_k':candidate_k,'candidate_rule_satisfied':vm[f'recall_at_{candidate_k}']>=.80,
          'validation_recall_at_selected_k':vm[f'recall_at_{candidate_k}'],'alpha_not_yet_selected':True,
          'test_tuning_forbidden':True,'eSASRec_provenance':{'upstream':'vendor/transformer_benchmark',
          'adaptation':'LiGR+SwiGLU and 64-negative sampled-softmax; local adapter because upstream RecTools 0.13 pins numpy<2 while validated environment has numpy 2.2.6'},
          'SMORE_status':'pending generic feature expansion; official source vendored'}
    save_json(ART/'selection_lock.json',lock);event('backbone_selection','complete',strong_backbone=winner,candidate_k=candidate_k,recall=lock['validation_recall_at_selected_k'])

if __name__=='__main__':main()
