"""One-shot generic SMORE and SMORE+tactile test evaluation."""
import pandas as pd
from common import *
from recommender import metrics
from tune_tactile_reranker import dense_features,run_config,base_state

def gain10(r):
    r=np.asarray(r);return np.where((r>0)&(r<=10),1/np.log2(r+1),0.)

def paired_ci(delta):
    values,counts=np.unique(np.asarray(delta),return_counts=True);rng=np.random.default_rng(SEED)
    means=rng.multinomial(int(counts.sum()),counts/counts.sum(),size=1000)@values/counts.sum()
    return {'mean':float(np.mean(delta)),'ci95_low':float(np.percentile(means,2.5)),'ci95_high':float(np.percentile(means,97.5)),'replicates':1000,'seed':SEED}

def main():
    lock=load_json(ART/'selection_lock.json')
    if (ART/'multimodal_recommendation_results.json').exists():
        raise RuntimeError('multimodal test results already exist; rerun forbidden')
    if lock.get('status')!='test_evaluated_no_retuning_allowed':
        raise RuntimeError('guarded backbone test is not complete')
    if lock.get('multimodal_validation_locked') is not True:
        raise RuntimeError('multimodal validation selection is not locked')
    selection=load_json(ART/'multimodal_selection.json')
    selection_sha=sha(ART/'multimodal_selection.json')
    if selection_sha!=lock.get('multimodal_selection_sha256'):
        raise RuntimeError('SMORE validation selection differs from the pre-test lock')
    if selection['status']=='N/A':
        event('multimodal_test','started',status_detail='N/A')
        save_json(ART/'multimodal_recommendation_results.json',{'status':'N/A','reason':selection['reason']})
        event('multimodal_test','complete',status_detail='N/A');return
    if selection.get('alpha_selected') is not True:
        raise RuntimeError('SMORE tactile alpha is not selected')
    manifest=load_json(ART/'test_smore_candidate_manifest.json')
    expected_manifest={
        'status':'complete','split':'test','model':'smore',
        'k':selection['candidate_k'],
        'selection_lock_sha256':sha(ART/'selection_lock.json'),
        'multimodal_selection_sha256':selection_sha,
        'checkpoint_sha256':lock.get('selected_checkpoint_sha256',{}).get('smore'),
    }
    bad={key:{'expected':value,'actual':manifest.get(key)}
         for key,value in expected_manifest.items() if manifest.get(key)!=value}
    if bad:
        raise RuntimeError(f'SMORE test candidate manifest mismatch: {bad}')
    checkpoint=Path(selection['selected_run']['checkpoint'])
    if not checkpoint.is_file() or sha(checkpoint)!=expected_manifest['checkpoint_sha256']:
        raise RuntimeError('pinned SMORE checkpoint changed')
    for graph_name,expected in lock.get('generic_graph_sha256',{}).items():
        graph=DATA/'smore'/graph_name
        if not graph.is_file() or sha(graph)!=expected:
            raise RuntimeError(f'pinned generic graph changed: {graph_name}')
    for name,expected in lock.get('tactile_input_sha256',{}).items():
        path=ART/name
        if not path.is_file() or sha(path)!=expected:raise RuntimeError(f'pinned tactile input changed: {name}')
    event('multimodal_test','started')
    values,available,cats,categories=dense_features();cols=list(range(14)) if selection['tactile_classes']==14 else [CLASSES.index(x) for x in RELIABLE]
    _,ranks,support=run_config('test',selection['profile_method']=='rating_ge_4',cols,values,available,cats,categories,[selection['alpha']],'test_smore')
    proposed=ranks[selection['alpha']];targets,base,_=base_state('test','test_smore');history=targets.train_history_length.to_numpy();inside=base<=selection['candidate_k']
    result={'status':'complete_no_post_test_tuning','model':'SMORE','candidate_k':selection['candidate_k'],'alpha':selection['alpha'],'profile_method':selection['profile_method'],'tactile_classes':selection['tactile_classes'],
            'generic_multimodal':{'all':metrics(base),'history_ge_3':metrics(base[history>=3]),'history_ge_5':metrics(base[history>=5])},
            'generic_multimodal_plus_tactile':{'all':metrics(proposed),'history_ge_3':metrics(proposed[history>=3]),'history_ge_5':metrics(proposed[history>=5])},
            'conditional_target_in_candidate':{'users':int(inside.sum()),'generic_multimodal':metrics(base[inside]),'plus_tactile':metrics(proposed[inside])},
            'rank_movement':{'improved':int((proposed<base).sum()),'unchanged':int((proposed==base).sum()),'worsened':int((proposed>base).sum()),'entered_top10':int(((base>10)&(proposed<=10)).sum()),'left_top10':int(((base<=10)&(proposed>10)).sum())},
            'bootstrap':{'ndcg_at_10':paired_ci(gain10(proposed)-gain10(base)),'hr_at_10':paired_ci((proposed<=10).astype(float)-(base<=10).astype(float))}}
    recall_path=ART/'candidate_recall.csv';old=pd.read_csv(recall_path);old=old[~((old.split=='test')&(old.model=='smore'))]
    mmrec=pd.DataFrame([{'split':'test','model':'smore','k':k,'recall':metrics(base)[f'recall_at_{k}'],'status':'complete'} for k in (100,300,500,1000,3000)])
    tmp=recall_path.with_suffix(recall_path.suffix+'.tmp');pd.concat([old,mmrec],ignore_index=True).to_csv(tmp,index=False);os.replace(tmp,recall_path)
    per_path=ART/'multimodal_per_user_results.parquet';tmp=per_path.with_suffix(per_path.suffix+'.tmp')
    pd.DataFrame({'row_index':np.arange(len(base)),'uid':targets.uid,'generic_multimodal_rank':base,'multimodal_tactile_rank':proposed,'tactile_history_support':support}).to_parquet(tmp,index=False);os.replace(tmp,per_path)
    # Extend the shared predeclared cold-start table without redefining any
    # cohort from test outcomes.
    cold=load_json(ART/'cold_start_results.json')
    strong_per=pd.read_parquet(ART/'per_user_results.parquet')
    masks={'train_count_0':strong_per.target_train_count.to_numpy()==0,
           'train_count_le_5':strong_per.target_train_count.to_numpy()<=5,
           'train_count_le_10':strong_per.target_train_count.to_numpy()<=10,
           'outside_v3_tactile_training_family':strong_per.outside_v3_tactile_training_family.to_numpy(dtype=bool)}
    for name,mask in masks.items():
        cold[name]['generic_multimodal']=metrics(base[mask]);cold[name]['multimodal_plus_tactile']=metrics(proposed[mask])
    save_json(ART/'cold_start_results.json',cold)
    # Publish the summary only after every dependent artifact is durable.
    save_json(ART/'multimodal_recommendation_results.json',result)
    event('multimodal_test','complete',delta_ndcg_at_10=result['bootstrap']['ndcg_at_10']['mean'])

if __name__=='__main__':main()
