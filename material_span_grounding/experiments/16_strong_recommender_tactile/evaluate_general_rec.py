"""Final RQ2 test analysis after every development decision is locked."""
import pandas as pd
from common import *
from recommender import metrics
from tune_tactile_reranker import dense_features,run_config,base_state

def gain10(r):
    r=np.asarray(r);return np.where((r>0)&(r<=10),1/np.log2(r+1),0.)

def paired_ci(delta):
    values,counts=np.unique(np.asarray(delta),return_counts=True);rng=np.random.default_rng(SEED)
    draws=rng.multinomial(int(counts.sum()),counts/counts.sum(),size=1000);means=draws@values/counts.sum()
    return {'mean':float(np.mean(delta)),'ci95_low':float(np.percentile(means,2.5)),'ci95_high':float(np.percentile(means,97.5)),
            'replicates':1000,'seed':SEED,'implementation':'exact paired nonparametric bootstrap via multinomial counts of observed paired deltas'}

def cohort(ranks,mask):return metrics(np.asarray(ranks)[mask])

def main():
    lock=load_json(ART/'selection_lock.json')
    if (ART/'general_recommendation_results.json').exists():
        raise RuntimeError('general test results already exist; rerun forbidden')
    if lock.get('status')!='test_evaluated_no_retuning_allowed':
        raise RuntimeError('guarded backbone test is not complete')
    if lock.get('alpha_selected') is not True or lock.get('multimodal_validation_locked') is not True:
        raise RuntimeError('validation selections are not fully locked')
    if load_json(ART/'test_candidate_manifest.json').get('status')!='complete':
        raise RuntimeError('strong test candidate manifest is incomplete')
    for name,expected in lock.get('tactile_input_sha256',{}).items():
        path=ART/name
        if not path.is_file() or sha(path)!=expected:raise RuntimeError(f'pinned tactile input changed: {name}')
    event('general_test','started')
    values,available,cats,categories=dense_features();cols=list(range(14)) if lock['tactile_classes']==14 else [CLASSES.index(x) for x in RELIABLE]
    rows,ranks,support=run_config('test',lock['profile_method']=='rating_ge_4',cols,values,available,cats,categories,[lock['alpha']])
    proposed=ranks[lock['alpha']];targets,base,_=base_state('test');k=lock['candidate_k'];history=targets.train_history_length.to_numpy();inside=base<=k
    result={'status':'complete_no_post_test_tuning','strong_backbone':lock['strong_backbone'],'candidate_k':k,'alpha':lock['alpha'],'profile_method':lock['profile_method'],'tactile_classes':lock['tactile_classes'],
      'strong':{'all':metrics(base),'history_ge_3':cohort(base,history>=3),'history_ge_5':cohort(base,history>=5)},
      'strong_plus_tactile':{'all':metrics(proposed),'history_ge_3':cohort(proposed,history>=3),'history_ge_5':cohort(proposed,history>=5)},
      'conditional_target_in_candidate':{'users':int(inside.sum()),'strong':metrics(base[inside]),'strong_plus_tactile':metrics(proposed[inside]),'mean_base_rank':float(base[inside].mean()) if inside.any() else None,'mean_reranked_rank':float(proposed[inside].mean()) if inside.any() else None},
      'rank_movement':{'improved':int((proposed<base).sum()),'unchanged':int((proposed==base).sum()),'worsened':int((proposed>base).sum()),'entered_top10':int(((base>10)&(proposed<=10)).sum()),'left_top10':int(((base<=10)&(proposed>10)).sum())},
      'bootstrap':{'ndcg_at_10':paired_ci(gain10(proposed)-gain10(base)),'hr_at_10':paired_ci((proposed<=10).astype(float)-(base<=10).astype(float))},
      'tactile_history_interpretation':'image-derived historical mean is a noisy proxy, not proof every prior attribute was preferred',
      'ground_truth_limitation':'held-out next Amazon review/rating interaction, not direct tactile satisfaction'}
    cohorts={'0':support==0,'1':support==1,'2':support==2,'3_to_4':(support>=3)&(support<5),'5_plus':support>=5}
    result['support_cohorts']={name:{'users':int(m.sum()),'strong_ndcg_at_10':metrics(base[m])['ndcg_at_10'] if m.any() else None,'proposed_ndcg_at_10':metrics(proposed[m])['ndcg_at_10'] if m.any() else None} for name,m in cohorts.items()}
    per=targets[['uid','user_id','iid','parent_asin','rating','timestamp','train_history_length','history_length','target_train_count']].copy()
    per['strong_rank']=base;per['strong_tactile_rank']=proposed;per['tactile_history_support']=support;per['target_in_candidate']=inside;per['ndcg10_delta']=gain10(proposed)-gain10(base)
    cold={}
    for name,m in {'train_count_0':per.target_train_count==0,'train_count_le_5':per.target_train_count<=5,'train_count_le_10':per.target_train_count<=10}.items():
        cold[name]={'definition':'train interaction count only','support':int(m.sum()),'strong':metrics(base[m]),'strong_plus_tactile':metrics(proposed[m])}
    old=load_json(PROJECT/'tactile_coldstart_qwen_v2_full/data/product_master_full_pool.json');trained=set()
    split=set(load_json(PROJECT/'tactile_coldstart_qwen_v2_full/manifests/family_split_20260901.json')['families']['train'])
    # The frozen v3 protocol splits product families. Map every child product in
    # a train family to its Amazon parent so variant aliases are not mislabelled
    # as tactile cold-start items.
    for product in old:
        family=product.get('product_family_id') or product.get('family_id') or product.get('product_id')
        if family in split:
            trained.add(product['parent_asin'])
    outside=~per.parent_asin.isin(trained);per['outside_v3_tactile_training_family']=outside
    cold['outside_v3_tactile_training_family']={'definition':'parent ASIN absent from fixed v3 train families','support':int(outside.sum()),'strong':metrics(base[outside]),'strong_plus_tactile':metrics(proposed[outside])}
    per_path=ART/'per_user_results.parquet';tmp=per_path.with_suffix(per_path.suffix+'.tmp')
    per.to_parquet(tmp,index=False);os.replace(tmp,per_path)
    save_json(ART/'cold_start_results.json',cold)
    meta=pd.read_parquet(DATA/'item_metadata.parquet').set_index('iid');delta=per.ndcg10_delta.to_numpy()
    ordering={'improvement':np.lexsort((per.uid,-delta)),'median':np.lexsort((per.uid,np.abs(delta-np.median(delta)))),'failure':np.lexsort((per.uid,delta))}
    qualitative={}
    for name,order in ordering.items():
        chosen=[]
        for j in order:
            if name=='improvement' and delta[j]<=0:continue
            if name=='failure' and delta[j]>=0:continue
            row=per.iloc[j];item=meta.loc[row.iid]
            chosen.append({'user_id':row.user_id,'parent_asin':row.parent_asin,'title':item.title,'category':item.category,'strong_rank':int(row.strong_rank),'strong_tactile_rank':int(row.strong_tactile_rank),'ndcg10_delta':float(row.ndcg10_delta),'tactile_history_support':int(row.tactile_history_support)})
            if len(chosen)==3:break
        qualitative[name]=chosen
    save_json(ART/'qualitative_examples.json',{'selection':'deterministic largest gain / nearest median / largest loss; uid tie-break; not manually cherry-picked',**qualitative})
    # Publish the summary only after every dependent artifact is durable.
    save_json(ART/'general_recommendation_results.json',result)
    event('general_test','complete',delta_ndcg10=result['bootstrap']['ndcg_at_10']['mean'],ci=result['bootstrap']['ndcg_at_10'])

if __name__=='__main__':main()
