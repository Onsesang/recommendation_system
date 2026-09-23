"""Validation-only training and selection for the generic SMORE baseline."""
import traceback
import pandas as pd
from common import *
from recommender import RecData,setup,train

def flatten(run):
    row={'model':'smore','status':'complete','learning_rate':run['lr'],'best_epoch':run['best_epoch']}
    for cohort,values in run['validation'].items():
        if isinstance(values,dict):
            for key,value in values.items():row[f'{cohort}.{key}']=value
    return row

def main():
    assert (ART/'generic_feature_report.json').exists(),'generic image/text features must be complete'
    lock=load_json(ART/'selection_lock.json');assert lock['status']=='locked_before_any_new_test_evaluation'
    if (ART/'multimodal_selection.json').exists():
        existing=load_json(ART/'multimodal_selection.json')
        if existing.get('status')=='validation_locked':return
    event('smore_validation','started',upstream='official WSDM 2025 repository with documented scalable graph adapter')
    d=RecData();c=load_json(ROOT/'configs/backbones.json');device=setup();runs=[];errors=[]
    for lr in c['learning_rates']:
        try:runs.append(train('smore',lr,d,c,device))
        except Exception as exc:
            errors.append({'learning_rate':lr,'error_type':type(exc).__name__,'message':str(exc)[:500],'traceback_tail':'\n'.join(traceback.format_exc().splitlines()[-12:])})
            event('smore_validation','failed',learning_rate=lr,error_type=type(exc).__name__)
    if not runs:
        result={'status':'N/A','reason':'all reproducible SMORE runs failed','errors':errors,'upstream':'vendor/SMORE'}
        save_json(ART/'multimodal_selection.json',result)
        pd.DataFrame([{'model':'smore','status':'N/A','reason':result['reason']}]).to_csv(ART/'multimodal_validation_results.csv',index=False)
        lock['SMORE_status']='N/A: all validation runs failed; see multimodal_selection.json';lock['multimodal_validation_locked']=True
        save_json(ART/'selection_lock.json',lock);event('smore_validation','complete',status_detail='N/A');return
    best=max(runs,key=lambda r:(r['validation']['all_official_targets']['ndcg_at_10'],r['validation']['all_official_targets']['hr_at_10'],r['validation']['all_official_targets']['mrr_at_10'],-r['lr']))
    table=pd.DataFrame([flatten(r) for r in runs]);table.to_csv(ART/'multimodal_validation_results.csv',index=False)
    metric=best['validation']['all_official_targets'];candidate_k=3000
    for k in (100,300,500,1000,3000):
        if metric[f'recall_at_{k}']>=.80:candidate_k=k;break
    result={'status':'validation_locked','model':'smore','selected_run':best,'candidate_k':candidate_k,
            'candidate_rule_satisfied':metric[f'recall_at_{candidate_k}']>=.80,'validation_recall_at_selected_k':metric[f'recall_at_{candidate_k}'],
            'alpha_selected':False,'generic_modalities':['unfine-tuned FashionCLIP image','unfine-tuned FashionCLIP metadata text'],
            'tactile_features_used':False,'failed_runs':errors}
    save_json(ART/'multimodal_selection.json',result)
    recall_path=ART/'candidate_recall.csv';old=pd.read_csv(recall_path)
    old=old[~((old.split=='validation')&(old.model=='smore'))]
    mmrec=pd.DataFrame([{'split':'validation','model':'smore','k':k,'recall':metric[f'recall_at_{k}'],'status':'complete'} for k in (100,300,500,1000,3000)])
    pd.concat([old,mmrec],ignore_index=True).to_csv(recall_path,index=False)
    lock['SMORE_status']='validation complete; tactile-free generic multimodal baseline';save_json(ART/'selection_lock.json',lock)
    event('smore_validation','complete',ndcg_at_10=metric['ndcg_at_10'],learning_rate=best['lr'],candidate_k=candidate_k)

if __name__=='__main__':main()
