"""One-shot test evaluation, guarded by immutable validation selection lock."""
import pandas as pd
import torch
from common import *
from recommender import RecData,new_model,evaluate,metrics,setup

MODELS=('popularity','bpr','lightgcn','sasrec','esasrec')
KS=(100,300,500,1000,3000)

def verify_pretest_inputs(lock):
    """Verify every validation decision and immutable feature input before test opens."""
    multimodal=load_json(ART/'multimodal_selection.json')
    pairs={ROOT/'configs/protocol.json':lock.get('protocol_sha256'),
           ART/'alpha_search.csv':lock.get('alpha_search_sha256')}
    if multimodal.get('status')=='validation_locked':
        pairs[ART/'multimodal_selection.json']=lock.get('multimodal_selection_sha256')
        pairs[ART/'smore_alpha_search.csv']=multimodal.get('alpha_search_sha256')
    elif multimodal.get('status')!='N/A':raise RuntimeError('invalid multimodal validation status')
    for path,expected in pairs.items():
        if not path.is_file() or not expected or sha(path)!=expected:
            raise RuntimeError(f'pre-test validation hash mismatch: {path.name}')
    tactile_paths={'product_tactile_profiles.parquet':ART/'product_tactile_profiles.parquet',
                   'tactile_coverage.json':ART/'tactile_coverage.json'}
    tactile_hashes={name:sha(path) for name,path in tactile_paths.items() if path.is_file()}
    if set(tactile_hashes)!=set(tactile_paths):raise RuntimeError('a tactile input is missing')
    graph_hashes={}
    if multimodal.get('status')=='validation_locked':
        generic=load_json(ART/'generic_feature_report.json')
        for sidecar_name,record in generic.get('graph_metadata',{}).items():
            graph=DATA/'smore'/f'{Path(sidecar_name).stem}.pt'
            actual=sha(graph) if graph.is_file() else None
            if actual!=record.get('graph_sha256'):raise RuntimeError(f'generic graph hash mismatch: {graph.name}')
            graph_hashes[graph.name]=actual
        if len(graph_hashes)!=2:raise RuntimeError('generic graph metadata is incomplete')
    return multimodal,tactile_hashes,graph_hashes

def load_selected(name,selection,d,c,device):
    if name=='popularity':return None
    record=selection['selected_runs'][name]
    expected=selection.get('selected_checkpoint_sha256',{}).get(name)
    if expected is not None and sha(record['checkpoint'])!=expected:raise RuntimeError(f'selected checkpoint hash changed: {name}')
    ck=torch.load(record['checkpoint'],map_location=device,weights_only=False)
    model=new_model(name,d,c).to(device);model.load_state_dict(ck['state_dict'],strict=True);return model

def flat(name,result):
    row={'model':name,'status':'complete'}
    for cohort,values in result.items():
        if isinstance(values,dict):
            for key,val in values.items():row[f'{cohort}.{key}']=val
        else:row[cohort]=values
    return row

def result_from_per_user(name,path,targets,d):
    """Recover metrics from an atomically completed per-user rank artifact."""
    per=pd.read_parquet(path,columns=['uid','iid','rank','train_history_length','history_length'])
    if len(per)!=len(targets) or not per.uid.equals(targets.uid) or not per.iid.equals(targets.iid):
        raise RuntimeError(f'invalid test per-user alignment: {path.name}')
    ranks=per['rank'].to_numpy()
    if not ((ranks>=1)&(ranks<=d.nitems)).all():raise RuntimeError(f'invalid ranks: {path.name}')
    result={'all_official_targets':metrics(ranks)}
    for k in (3,5):result[f'train_history_ge_{k}']=metrics(ranks[per.train_history_length.to_numpy()>=k])
    if name=='popularity':personalized=0
    elif name in ('sasrec','esasrec'):personalized=int((per.history_length.to_numpy()>0).sum())
    else:personalized=int(per.uid.isin(d.train_uids).sum())
    result['personalized_users']=personalized
    return result

def recover_completed_test(result_path,lock):
    """Finalize a fully written one-shot result after an interrupted lock update."""
    event('backbone_test_recovery','started')
    table=pd.read_csv(result_path)
    if table.model.tolist()!=list(MODELS) or not (table.status=='complete').all():
        raise RuntimeError('existing backbone test CSV is incomplete; refusing recovery')
    d=RecData()
    targets=pd.read_parquet(DATA/'test_targets.parquet',columns=['uid','iid'])
    calculated={}
    for name in MODELS:
        path=ART/f'{name}_test_per_user.parquet'
        if not path.exists():raise RuntimeError(f'missing test per-user artifact: {path.name}')
        result=result_from_per_user(name,path,targets,d);calculated[name]=result
        expected=flat(name,result);actual=table[table.model==name].iloc[0]
        for key,value in expected.items():
            if key not in table.columns:raise RuntimeError(f'missing test metric column: {key}')
            if isinstance(value,str):ok=actual[key]==value
            else:ok=np.isclose(float(actual[key]),float(value),rtol=0,atol=1e-15)
            if not ok:raise RuntimeError(f'test CSV/per-user metric mismatch: {name} {key}')
    recall=pd.read_csv(ART/'candidate_recall.csv')
    got=recall[(recall.split=='test')&recall.model.isin(MODELS)]
    expected={(name,k) for name in MODELS for k in KS}
    if len(got)!=len(expected) or set(zip(got.model,got.k))!=expected or not (got.status=='complete').all():
        raise RuntimeError('backbone test candidate recall is incomplete; refusing recovery')
    for row in got.itertuples():
        expected_recall=calculated[row.model]['all_official_targets'][f'recall_at_{row.k}']
        if not np.isclose(row.recall,expected_recall,rtol=0,atol=1e-15):
            raise RuntimeError(f'candidate recall/per-user mismatch: {row.model} K={row.k}')
    lock['status']='test_evaluated_no_retuning_allowed'
    lock['test_results_sha256']=sha(result_path)
    save_json(ART/'selection_lock.json',lock)
    event('backbone_test_recovery','complete',models=len(MODELS),users=len(targets))

def main():
    lock=load_json(ART/'selection_lock.json')
    result_path=ART/'backbone_test_results.csv'
    status=lock.get('status')
    if status=='test_evaluated_no_retuning_allowed':
        raise RuntimeError('test results already exist; rerun forbidden')
    if status not in ('locked_before_any_new_test_evaluation','test_evaluation_in_progress_no_retuning'):
        raise RuntimeError('selection lock is not at the pre-test boundary')
    if lock.get('alpha_selected') is not True:
        raise RuntimeError('finish tactile validation selection before opening test')
    if lock.get('multimodal_validation_locked') is not True:
        raise RuntimeError('finish multimodal validation selection before opening test')
    if status=='locked_before_any_new_test_evaluation':
        selection_sha=sha(ART/'selection_lock.json')
        multimodal,tactile_hashes,graph_hashes=verify_pretest_inputs(lock)
        checkpoint_paths={name:Path(lock['selected_runs'][name]['checkpoint']) for name in MODELS if name!='popularity'}
        if multimodal.get('status')=='validation_locked':checkpoint_paths['smore']=Path(multimodal['selected_run']['checkpoint'])
        if not all(path.is_file() for path in checkpoint_paths.values()):raise RuntimeError('a selected checkpoint is missing')
        lock['selected_checkpoint_sha256']={name:sha(path) for name,path in checkpoint_paths.items()}
        lock['tactile_input_sha256']=tactile_hashes;lock['generic_graph_sha256']=graph_hashes
        lock['status']='test_evaluation_in_progress_no_retuning'
        lock['test_started_selection_sha256']=selection_sha
        lock['test_started_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        save_json(ART/'selection_lock.json',lock)
        event('backbone_test','started',selection_sha256=selection_sha)
    else:event('backbone_test_resume','started')
    if result_path.exists():recover_completed_test(result_path,lock);return
    device=setup();d=RecData();c=load_json(ROOT/'configs/backbones.json');rows=[];recalls=[]
    targets=pd.read_parquet(DATA/'test_targets.parquet',columns=['uid','iid'])
    for name in MODELS:
        per_path=ART/f'{name}_test_per_user.parquet';model=None
        if per_path.exists():
            result=result_from_per_user(name,per_path,targets,d)
            event('backbone_test','model_recovered',model=name,**result['all_official_targets'])
        else:
            tmp=per_path.with_suffix(per_path.suffix+'.tmp')
            if tmp.exists():tmp.unlink()
            model=load_selected(name,lock,d,c,device)
            result,_=evaluate(name,model,d,'test',device,c['evaluation_batch_size'],save_to=per_path)
            event('backbone_test','model_complete',model=name,**result['all_official_targets'])
        row=flat(name,result);rows.append(row)
        for k in KS:recalls.append({'split':'test','model':name,'k':k,'recall':row[f'all_official_targets.recall_at_{k}'],'status':'complete'})
        del model
        if device=='cuda':torch.cuda.empty_cache()
    # Candidate recall is idempotently replaceable. Publish the result CSV last;
    # if interruption happens after that point, the verified recovery path above
    # performs only the pending lock transition and never recomputes test ranks.
    recall_path=ART/'candidate_recall.csv';old=pd.read_csv(recall_path)
    old=old[~((old.split=='test')&old.model.isin(MODELS))]
    tmp=recall_path.with_suffix(recall_path.suffix+'.tmp')
    pd.concat([old,pd.DataFrame(recalls)],ignore_index=True).to_csv(tmp,index=False);os.replace(tmp,recall_path)
    tmp=result_path.with_suffix(result_path.suffix+'.tmp');pd.DataFrame(rows).to_csv(tmp,index=False);os.replace(tmp,result_path)
    lock['status']='test_evaluated_no_retuning_allowed';lock['test_results_sha256']=sha(result_path);save_json(ART/'selection_lock.json',lock)
    event('backbone_test','complete',models=len(rows))

if __name__=='__main__':main()
