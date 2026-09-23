"""Frozen validation selection, paired offline comparisons, and explicit limitations."""
import argparse
from collections import Counter

import numpy as np
import pandas as pd

from pipeline import ART,OLD,ROOT,CLASSES,read,write,sha
from preference_core import history_rows,desired_presence,build_profile,match_profile,blend,percentile,target_ranks,metrics


def load():
    products=pd.read_parquet(OLD/'product_tactile_profiles.parquet').sort_values('item_id').reset_index(drop=True)
    cases=pd.read_parquet(OLD/'evaluation_cases.parquet')
    events=pd.read_parquet(OLD/'recommendation_splits.parquet')
    return products,cases,events


def popularity_bundle(split,products,cases,events,k):
    history=events[events.split.isin(['train'] if split=='validation' else ['train','validation'])]
    item_map={p:i for i,p in enumerate(products.item_id)}
    counts=history.item_id.value_counts()
    scores=products.item_id.map(counts).fillna(0).to_numpy(float)
    hist=history.groupby('user_id').item_id.agg(list).to_dict()
    indices=[];base=[];positions=[];full_ranks=[]
    for case in cases.itertuples():
        s=scores.copy();s[[item_map[x] for x in hist.get(case.user_id,[])]]=-np.inf
        order=np.argsort(-s,kind='stable');idx=order[:k]
        assert np.isfinite(s[idx]).all()
        target=item_map[case.target_item]
        pos=np.flatnonzero(idx==target)
        indices.append(idx);base.append(percentile(s[idx]));positions.append(int(pos[0]) if len(pos) else -1)
        full_ranks.append(int(np.flatnonzero(order==target)[0])+1)
    return {'candidate_indices':np.asarray(indices,dtype=np.int32),'base_norm':np.asarray(base,dtype=np.float32),
            'target_positions':np.asarray(positions,dtype=np.int32),'full_ranks':np.asarray(full_ranks,dtype=np.int32)}


def candidates():
    if (ART/'candidate_selection.json').exists():print('Candidate selection already frozen');return
    cfg=read(ART/'config.json')
    products,allcases,events=load()
    cases=allcases[allcases.split=='validation'].sort_values('user_id').reset_index(drop=True)
    pop=popularity_bundle('validation',products,cases,events,cfg['candidate_k'])
    bpr=dict(np.load(OLD/'validation_candidates.npz'))
    candidates_by_name={'bpr':bpr,'popularity':pop}
    diagnostics={name:{'recall_at_300':float((a['target_positions']>=0).mean()),
                       'top10':metrics(target_ranks(a['base_norm'],a['target_positions']))} for name,a in candidates_by_name.items()}
    selected=max(['bpr','popularity'],key=lambda name:diagnostics[name]['recall_at_300'])
    write(ART/'candidate_selection.json',{'selection_split':'validation','criterion':'max Recall@300, ties BPR',
          'selected':selected,'validation_diagnostics':diagnostics,'old_baseline_preserved':True})
    for split in ['validation','test']:
        part=allcases[allcases.split==split].sort_values('user_id').reset_index(drop=True)
        pop=pop if split=='validation' else popularity_bundle(split,products,part,events,cfg['candidate_k'])
        a=pop if selected=='popularity' else dict(np.load(OLD/f'{split}_candidates.npz'))
        category=pd.read_parquet(OLD/'user_category_profiles.parquet')
        catmap={(r.user_id,r.category):r.preference for r in category[category.profile_split==split].itertuples()}
        a['category_norm']=np.asarray([percentile([catmap.get((case.user_id,str(products.iloc[j].category)),0) for j in idx])
                                    for case,idx in zip(part.itertuples(),a['candidate_indices'])],dtype=np.float32)
        a['popularity_full_ranks']=pop['full_ranks']
        np.savez_compressed(ART/f'{split}_candidates.npz',**a)
    write(ART/'evaluation_protocol.json',{
        'frozen_before_preference_comparison':True,'shrinkage_reviews':2.0,'selection_metric':'validation NDCG@10',
        'tie_break':'smaller weight','shuffle_seed':cfg['seed'],'shuffle_unit':'whole user profile permutation including empty profiles',
        'score':'(1-alpha)*category_base_percentile + alpha*mean((2*desired_presence-1)*(item_probability-.5)*n/(n+2))',
        'future_reviews':'Post-selection pseudo-label consistency only, never inference input or human gold.',
        'review_item_ablation':'Only annotated cohort-history reviews, timestamp strictly before each case, allowed history split, exclude evaluated user. Sparse, not a full review-oracle upper bound.',
        'cold_subset':'v3 family test membership only; no image training-family overlap, NOT globally temporal or interaction-cold-start.',
        'same_category':'Profile contributions only from candidate category; target category never selects main candidate set.',
        'candidate_sha256':{s:sha(ART/f'{s}_candidates.npz') for s in ['validation','test']}})
    print(read(ART/'candidate_selection.json'))


def annotations():
    samples=pd.read_parquet(ART/'occurrences.parquet')
    source={r['sample_id']:r for r in samples.to_dict('records')}
    import json
    records=[json.loads(line) for line in (ART/'annotations.jsonl').read_text().splitlines()]
    assert len(records)==len(source) and len({r['sample_id'] for r in records})==len(source),'Inference not complete'
    latest={r['sample_id']:r for r in records}
    if (ART/'repair_annotations.jsonl').exists():
        for line in (ART/'repair_annotations.jsonl').read_text().splitlines():
            r=json.loads(line)
            if latest[r['sample_id']]['annotation'] is None:latest[r['sample_id']]=r
    good=[]
    for sid,r in latest.items():
        if r['annotation'] is not None:
            good.append({**source[sid],**r['annotation']})
    out=pd.DataFrame(good)
    assert len(out)>0
    out.to_parquet(ART/'validated_evidence.parquet',index=False)
    cfg=read(ART/'config.json')
    filters=Counter(desired_presence(r,cfg)[1] or 'explicit_eligible_before_category_and_time' for r in out.to_dict('records'))
    write(ART/'extraction_summary.json',{'attempts':len(latest),'valid_schema_and_anchored_quote':len(good),
          'initial_invalid':sum(r['annotation'] is None for r in records),
          'final_invalid':sum(r['annotation'] is None for r in latest.values()),
          'errors':dict(Counter(r['validation_error'] for r in latest.values() if r['annotation'] is None)),
          'attitudes':out.attitude.value_counts().to_dict(),'states':out.property_state.value_counts().to_dict(),
          'profile_filters':dict(filters),'semantic_accuracy':None,'human_audit':'skipped_by_user'})
    return out


def review_probabilities(evidence,case,indices,products,config):
    allowed=['train'] if case.split=='validation' else ['train','validation']
    pool=evidence[(evidence.timestamp<case.target_timestamp) & evidence.official_split.isin(allowed)
                  & (evidence.user_id!=case.user_id) & evidence.property_state.isin(['present','absent'])
                  & evidence.class_id.isin(CLASSES) & evidence.scope.isin(config['allowed_scopes'])
                  & evidence.condition.isin(config['allowed_conditions'])]
    pool=pool[pool.parent_asin.isin(products.iloc[indices].item_id)]
    result=np.full((len(indices),len(CLASSES)),np.nan)
    if len(pool):
        pool=pool.assign(present=(pool.property_state=='present').astype(float))
        per_review=pool.groupby(['event_id','parent_asin','class_id']).present.mean()
        per_item=per_review.groupby(['parent_asin','class_id']).mean()
        loc={products.iloc[j].item_id:k for k,j in enumerate(indices)}
        for (item,cls),p in per_item.items():result[loc[item],CLASSES.index(cls)]=p
    return result


def components(split,evidence):
    cfg=read(ART/'config.json');protocol=read(ART/'evaluation_protocol.json')
    products,allcases,events=load()
    cases=allcases[allcases.split==split].sort_values('user_id').reset_index(drop=True)
    assert sha(ART/f'{split}_candidates.npz')==protocol['candidate_sha256'][split]
    a=dict(np.load(ART/f'{split}_candidates.npz'))
    category_map=dict(zip(products.item_id,products.category))
    probabilities=products[CLASSES].to_numpy(float);categories=products.category.to_numpy()
    histories=events[events.split.isin(['train'] if split=='validation' else ['train','validation'])].groupby('user_id')
    histmap={u:g for u,g in histories}
    evidence_users={u:g for u,g in evidence.groupby('user_id')}
    profiles=[];like_profiles=[];profile_records=[]
    for case in cases.itertuples():
        eh=evidence_users.get(case.user_id,evidence.iloc[:0])
        h=history_rows(eh,case.user_id,split,case.target_timestamp,case.target_item)
        assert not (h.timestamp>=case.target_timestamp).any() and not (h.parent_asin==case.target_item).any()
        profile=build_profile(h,category_map,cfg);profiles.append(profile)
        like_profiles.append(build_profile(h[h.attitude=='like'],category_map,cfg))
        profile_records.append({'user_id':case.user_id,'split':split,'target_cutoff':int(case.target_timestamp),
            'entries':[{'category':k[0],'class_id':k[1],**v} for k,v in profile.items()]})
    write(ART/f'{split}_user_profiles.json',profile_records)
    permutation=np.random.default_rng(cfg['seed']).permutation(len(profiles))
    shape=a['candidate_indices'].shape
    for name in ['explicit','shuffled','likes_only','history_mean','review_only','hybrid']:
        a[name]=np.zeros(shape,dtype=np.float32)
    a['support']=np.zeros(shape,dtype=np.int16);a['review_support']=np.zeros(shape,dtype=np.int16)
    index_map={v:i for i,v in enumerate(products.item_id)}
    for i,case in enumerate(cases.itertuples()):
        idx=a['candidate_indices'][i]; cats=categories[idx];probs=probabilities[idx]
        profile=profiles[i]
        raw,support=match_profile(profile,cats,probs,protocol['shrinkage_reviews'])
        a['explicit'][i]=raw;a['support'][i]=support
        donor=cases.iloc[permutation[i]].user_id
        donor_history=history_rows(evidence_users.get(donor,evidence.iloc[:0]),donor,split,case.target_timestamp,case.target_item)
        donor_profile=build_profile(donor_history,category_map,cfg)
        a['shuffled'][i]=match_profile(donor_profile,cats,probs,protocol['shrinkage_reviews'])[0]
        a['likes_only'][i]=match_profile(like_profiles[i],cats,probs,protocol['shrinkage_reviews'])[0]
        hist=histmap.get(case.user_id,events.iloc[:0])
        assert not (hist.timestamp>=case.target_timestamp).any() and not (hist.item_id==case.target_item).any()
        assert not set(products.iloc[idx].item_id)&set(hist.item_id)
        mean=probabilities[[index_map[x] for x in hist.item_id]].mean(axis=0)
        den=np.linalg.norm(probs,axis=1)*np.linalg.norm(mean)
        cosine=np.divide(probs@mean,den,out=np.zeros(len(idx)),where=den>0)
        a['history_mean'][i]=percentile(cosine)-.5
        review=review_probabilities(evidence,case,idx,products,cfg)
        a['review_only'][i],a['review_support'][i]=match_profile(profile,cats,review,protocol['shrinkage_reviews'])
        # Review-cold-start family always uses image features, regardless of any annotated reviews.
        review[products.iloc[idx].v3_family_split.to_numpy()=='test']=np.nan
        hybrid=np.where(np.isfinite(review),review,probs)
        a['hybrid'][i]=match_profile(profile,cats,hybrid,protocol['shrinkage_reviews'])[0]
        if i%500==0:print(f'components {split} {i}/{len(cases)}',flush=True)
    np.savez_compressed(ART/f'{split}_components.npz',**a)
    write(ART/f'{split}_coverage.json',{'users':len(cases),'users_with_profile':sum(bool(p) for p in profiles),
          'users_with_candidate_support':int((a['support']>0).any(axis=1).sum()),
          'candidate_support_fraction':float((a['support']>0).mean()),
          'users_with_review_candidate_support':int((a['review_support']>0).any(axis=1).sum()),
          'user_time_checks_passed':True,'seen_item_checks_passed':True,'cross_category_weight':0})
    return a,cases,products,profiles


BRANCHES=['explicit','shuffled','likes_only','history_mean','review_only','hybrid']


def select(a):
    cfg=read(ART/'config.json');rows=[]
    beta=max(cfg['beta_grid'],key=lambda b:metrics(target_ranks((1-b)*a['base_norm']+b*a['category_norm'],a['target_positions']))['ndcg_at_10'])
    base=np.asarray([percentile(r) for r in (1-beta)*a['base_norm']+beta*a['category_norm']])
    alphas={}
    for branch in BRANCHES:
        for alpha in cfg['alpha_grid']:
            m=metrics(target_ranks(blend(base,a[branch],alpha),a['target_positions']))
            rows.append({'branch':branch,'alpha':alpha,**m})
        alphas[branch]=max(cfg['alpha_grid'],key=lambda x:next(r['ndcg_at_10'] for r in rows if r['branch']==branch and r['alpha']==x))
    pd.DataFrame(rows).to_csv(ART/'validation_search.csv',index=False)
    selection={'split':'validation','beta':beta,'alphas':alphas,'metric':'NDCG@10','ties':'smallest weight',
               'config_sha256':sha(ART/'config.json'),'validation_components_sha256':sha(ART/'validation_components.npz')}
    write(ART/'selection.json',selection)
    return selection


def rank_methods(a,selection):
    b=selection['beta'];base=np.asarray([percentile(r) for r in (1-b)*a['base_norm']+b*a['category_norm']])
    scores={'base':a['base_norm'],'category':base}
    scores.update({branch:blend(base,a[branch],alpha) for branch,alpha in selection['alphas'].items()})
    ranks={name:target_ranks(s,a['target_positions']) for name,s in scores.items()}
    ranks['popularity_full_catalog']=a['popularity_full_ranks']
    return ranks,scores


def bootstrap(left,right,cfg):
    if not len(left):return {'n':0,'delta':None,'ci95':None}
    l=np.where(left<=10,1/np.log2(left+1),0);r=np.where(right<=10,1/np.log2(right+1),0);delta=l-r
    rng=np.random.default_rng(cfg['seed'])
    boot=np.asarray([delta[rng.integers(0,len(delta),len(delta))].mean() for _ in range(cfg['bootstrap_replicates'])])
    return {'n':len(left),'delta':float(delta.mean()),'ci95':[float(x) for x in np.quantile(boot,[.025,.975])],
            'unit':'paired user','metric':'NDCG@10','interpretation':'exploratory; no multiple-comparison correction'}


def future_consistency(evidence,cases,profiles,cfg,products):
    # This function never participates in scoring or validation weight selection.
    catmap=dict(zip(products.item_id,products.category));rows=[]
    byuser={u:g for u,g in evidence.groupby('user_id')}
    for case,profile in zip(cases.itertuples(),profiles):
        ev=byuser.get(case.user_id,evidence.iloc[:0])
        target=ev[(ev.parent_asin==case.target_item)&(ev.timestamp==case.target_timestamp)&(ev.official_split==case.split)]
        future=build_profile(target,catmap,cfg)
        for key,v in future.items():
            if key not in profile:continue
            past=profile[key]['desired_presence'];future_value=v['desired_presence']
            rows.append({'user_id':case.user_id,'category':key[0],'class_id':key[1],
                         'past_desired_presence':past,'future_desired_presence':future_value,
                         'past_tie':past==.5,'future_tie':future_value==.5,
                         'agrees':bool((past>.5)==(future_value>.5)) if past!=.5 and future_value!=.5 else None})
    pd.DataFrame(rows).to_csv(ART/'future_review_pseudo_consistency.csv',index=False)
    non_ties=[r for r in rows if r['agrees'] is not None]
    return {'shared_user_category_class_pairs':len(rows),'non_tied_pairs':len(non_ties),
            'users':len({r['user_id'] for r in rows}),'agreement':float(np.mean([r['agrees'] for r in non_ties])) if non_ties else None,
            'meaning':'Same-Qwen historical/future local-opinion consistency only. Not human preference accuracy, recommendation satisfaction, or independent validation.'}


def evaluate():
    evidence=annotations();cfg=read(ART/'config.json')
    a,_,_,_=components('validation',evidence)
    if (ART/'selection.json').exists():
        selection=read(ART/'selection.json')
        assert selection['validation_components_sha256']==sha(ART/'validation_components.npz')
    else:selection=select(a)
    # No test metrics enter select(). The cohort is still exploratory because earlier experiments inspected it.
    a,cases,products,profiles=components('test',evidence)
    ranks,scores=rank_methods(a,selection)
    masks={'all':np.ones(len(cases),bool),'profile_supported':(a['support']>0).any(axis=1),
           'candidate_hit':a['target_positions']>=0,
           'image_training_unseen_family':products.set_index('item_id').loc[cases.target_item].v3_family_split.to_numpy()=='test',
           'review_feature_supported':(a['review_support']>0).any(axis=1)}
    results={name:{method:metrics(r[mask]) for method,r in ranks.items()} for name,mask in masks.items()}
    comparisons={name:{branch+'_minus_category':bootstrap(ranks[branch][mask],ranks['category'][mask],cfg)
                       for branch in BRANCHES} for name,mask in masks.items()}
    peruser=cases.copy()
    for name,r in ranks.items():peruser[name+'_rank']=r
    for name,mask in masks.items():peruser[name]=mask
    peruser.to_csv(ART/'per_user_results.csv',index=False)
    # First five supported users sorted by stable user order; no cherry-picking for wins.
    examples=[]
    for i in np.flatnonzero(masks['profile_supported'])[:5]:
        order=np.argsort(-scores['explicit'][i],kind='stable')[:10]
        entries=[]
        for j in order:
            item=products.iloc[a['candidate_indices'][i,j]]
            entries.append({'item_id':item.item_id,'category':item.category,'image_probabilities':{c:float(item[c]) for c in CLASSES},
                'base_norm':float(a['base_norm'][i,j]),'category_norm':float(a['category_norm'][i,j]),
                'tactile_signed_utility':float(a['explicit'][i,j]),'supported_class_count':int(a['support'][i,j]),
                'final_score':float(scores['explicit'][i,j])})
        examples.append({'user_id':cases.iloc[i].user_id,'top10':entries})
    write(ART/'score_breakdowns.json',examples)
    consistency=future_consistency(evidence,cases,profiles,cfg,products)
    protected=read(ART/'protocol.json')['protected_hashes']
    checks={path:sha(path)==value for path,value in protected.items()}
    assert all(checks.values())
    result={'status':'complete_exploratory_human_audit_skipped','human_gold':False,'human_accuracy':None,
            'candidate_selection':read(ART/'candidate_selection.json'),'selection':selection,
            'test_candidate_recall':float((a['target_positions']>=0).mean()),'metrics':results,'paired_bootstrap':comparisons,
            'coverage':{s:read(ART/f'{s}_coverage.json') for s in ['validation','test']},
            'extraction':read(ART/'extraction_summary.json'),'future_review_pseudo_consistency':consistency,
            'protected_inputs_unchanged':checks,
            'limitations':['No human audit; all extracted labels are model pseudo-labels.',
                'Previously inspected cohort: validation-only weights do not create a new confirmatory test.',
                'User-relative histories are time-filtered; pretrained Last2 and collective recommender data are not globally time-clean.',
                'Fixed eligible catalog is 7,365 of 825,869 items; this is not full-catalog Amazon recommendation.',
                'Review-only features use sparse annotated cohort histories, not a full review upper bound.',
                'Category-local, unconditional garment-level restriction drops conditional and out-of-catalog preferences.',
                'Image-training-unseen family subset is not a claim of interaction or global temporal cold-start.',
                'Future review consistency is not independent satisfaction evaluation.']}
    write(ART/'results.json',result)
    print({k:result[k] for k in ['status','selection','test_candidate_recall','coverage']})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['candidates','evaluate']);args=p.parse_args()
    globals()[args.stage]()
