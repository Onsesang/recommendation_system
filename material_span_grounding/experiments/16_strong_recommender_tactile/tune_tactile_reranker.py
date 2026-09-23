"""Validation-only alpha/profile/class ablation on locked candidate sets."""
import argparse
import pandas as pd
import torch
from scipy.stats import rankdata
from common import *
from recommender import RecData,metrics,setup

def category_index_tensor(candidate,categories,device):
    """Return category IDs in the integer dtype required for torch indexing."""
    return torch.as_tensor(categories[candidate],dtype=torch.long,device=device)

def average_tie_percentile(scores,valid):
    """Percentile ranks within valid items, assigning tied values their mean rank."""
    masked=scores.masked_fill(~valid,-torch.inf)
    order=torch.argsort(masked,dim=1,descending=True,stable=True)
    sorted_scores=masked.gather(1,order);width=masked.shape[1]
    pos=torch.arange(width,device=masked.device,dtype=torch.long)[None].expand_as(order)
    starts=torch.ones_like(order,dtype=torch.bool)
    if width>1:starts[:,1:]=sorted_scores[:,1:]!=sorted_scores[:,:-1]
    start=torch.cummax(torch.where(starts,pos,torch.zeros_like(pos)),dim=1).values
    ends=torch.ones_like(order,dtype=torch.bool)
    if width>1:ends[:,:-1]=sorted_scores[:,:-1]!=sorted_scores[:,1:]
    marker=torch.where(ends,pos,torch.full_like(pos,width))
    end=torch.flip(torch.cummin(torch.flip(marker,dims=[1]),dim=1).values,dims=[1])
    average_position=(start+end).to(scores.dtype)/2
    count=valid.sum(1);denominator=(count-1).clamp_min(1).to(scores.dtype)
    sorted_percentile=(count[:,None].to(scores.dtype)-1-average_position)/denominator[:,None]
    sorted_percentile=torch.where(count[:,None]>1,sorted_percentile,torch.full_like(sorted_percentile,.5))
    percentile=torch.empty_like(sorted_percentile);percentile.scatter_(1,order,sorted_percentile)
    return percentile.masked_fill(~valid,.5)

def dense_features():
    catalog=pd.read_parquet(DATA/'item_metadata.parquet',columns=['iid','category'])
    categories=np.sort(catalog.category.unique());catmap={x:j for j,x in enumerate(categories)}
    cats=catalog.category.map(catmap).to_numpy(dtype=np.int16)
    p=pd.read_parquet(ART/'product_tactile_profiles.parquet')
    values=np.zeros((len(catalog),len(CLASSES)),dtype=np.float32);available=np.zeros(len(catalog),dtype=bool)
    values[p.iid.to_numpy()]=p[CLASSES].to_numpy(dtype=np.float32);available[p.iid.to_numpy()]=True
    return values,available,cats,categories

def rated_history(split):
    e=pd.read_parquet(DATA/'events.parquet',columns=['uid','iid','rating','split'])
    e=e[e.split.isin(['train'] if split=='validation' else ['train','validation'])]
    return {int(u):(g.iid.to_numpy(),g.rating.to_numpy()) for u,g in e.groupby('uid',sort=False)}

def user_profiles(uids,hist,values,available,cats,ncat,positive,cols):
    profiles=np.zeros((len(uids),ncat,len(cols)),dtype=np.float32);counts=np.zeros((len(uids),ncat),dtype=np.int16);support=np.zeros(len(uids),dtype=np.int16)
    for j,u in enumerate(uids):
        ids,ratings=hist[int(u)];keep=available[ids] & ((ratings>=4) if positive else True);ids=ids[keep];support[j]=len(ids)
        for cat in np.unique(cats[ids]):
            group=ids[cats[ids]==cat];profiles[j,cat]=values[group][:,cols].mean(0);counts[j,cat]=len(group)
    return profiles,counts,support

def base_state(split,prefix=None):
    prefix=prefix or split
    targets=pd.read_parquet(DATA/f'{split}_targets.parquet');base=np.zeros(len(targets),dtype=np.int32);support=np.zeros(len(targets),dtype=np.int16)
    no=pd.read_parquet(ART/f'{prefix}_no_history_ranks.parquet');base[no.row_index]=no.base_rank
    for p in sorted((ART/f'{prefix}_candidate_chunks').glob('*.npz')):
        x=np.load(p);base[x['row_index']]=x['base_rank']
    assert (base>0).all();return targets,base,support

def run_config(split,positive,cols,values,available,cats,categories,alphas,prefix=None):
    prefix=prefix or split
    device=setup();targets,base,support_all=base_state(split,prefix);allr={a:base.copy() for a in alphas};hist=rated_history(split)
    for p in sorted((ART/f'{prefix}_candidate_chunks').glob('*.npz')):
        x=np.load(p);row=x['row_index'];uids=x['uid'];cand=x['candidate'];target=x['target'];raw=x['base_score']
        up,uc,support=user_profiles(uids,hist,values,available,cats,len(categories),positive,cols);support_all[row]=support
        basepct=((rankdata(raw,axis=1,method='average')-1)/max(cand.shape[1]-1,1)).astype('float32')
        batch=64
        for start in range(0,len(row),batch):
            sl=slice(start,start+batch);ci=torch.tensor(cand[sl],device=device);cc=category_index_tensor(cand[sl],cats,device)
            iv=torch.tensor(values[cand[sl]][:,:,cols],device=device);uv=torch.tensor(up[sl],device=device)
            selected=uv[torch.arange(len(ci),device=device)[:,None],cc]
            valid=torch.tensor(available[cand[sl]],device=device)&(torch.tensor(uc[sl],device=device)[torch.arange(len(ci),device=device)[:,None],cc]>0)
            sim=torch.nn.functional.cosine_similarity(selected,iv,dim=-1)
            tp=average_tie_percentile(sim,valid)
            bp=torch.tensor(basepct[sl],device=device);truth=torch.tensor(target[sl],device=device);where=ci==truth[:,None];inside=where.any(1)
            for alpha in alphas:
                final=torch.where(valid,bp+alpha*(tp-bp),bp);ts=final.masked_fill(~where,-torch.inf).max(1).values
                rr=1+(final>ts[:,None]).sum(1)+((final==ts[:,None])&(ci<truth[:,None])).sum(1)
                changed=inside.nonzero().squeeze(1);out=allr[alpha];out[row[sl][changed.cpu().numpy()]]=rr[changed].cpu().numpy().astype('int32')
    results=[]
    for a in alphas:
        row={'split':split,'profile':'rating_ge_4' if positive else 'all_history','classes':len(cols),'alpha':a,**metrics(allr[a])}
        for k in (1,2,3,5):
            m=support_all>=k;row[f'support_ge_{k}.users']=int(m.sum());row[f'support_ge_{k}.ndcg_at_10']=metrics(allr[a][m])['ndcg_at_10'] if m.any() else None
        results.append(row)
    return results,allr,support_all

def main():
    p=argparse.ArgumentParser();p.add_argument('--model-key',choices=['strong','smore'],default='strong');p.add_argument('--revalidate-existing',action='store_true');args=p.parse_args()
    lock=load_json(ART/'selection_lock.json')
    if lock.get('status')!='locked_before_any_new_test_evaluation':
        raise RuntimeError('validation tuning is forbidden after the test boundary opens')
    prefix='validation' if args.model_key=='strong' else 'validation_smore'
    if args.model_key=='strong':
        if lock.get('alpha_selected') is True and not args.revalidate_existing:raise RuntimeError('strong tactile alpha is already selected')
        if lock.get('alpha_selected') is not True and args.revalidate_existing:raise RuntimeError('no existing strong alpha selection to revalidate')
    else:
        if args.revalidate_existing:raise RuntimeError('--revalidate-existing is only for the pre-test strong correction audit')
        smore=load_json(ART/'multimodal_selection.json')
        if smore.get('status')!='validation_locked':raise RuntimeError('SMORE selection is not validation-locked')
        if smore.get('alpha_selected') is True:raise RuntimeError('SMORE tactile alpha is already selected')
    if load_json(ART/f'{prefix}_candidate_manifest.json').get('status')!='complete':
        raise RuntimeError(f'{prefix} candidate manifest is incomplete')
    stage=('alpha_search_revalidation' if args.revalidate_existing else ('alpha_search' if args.model_key=='strong' else 'smore_alpha_search'));event(stage,'started')
    values,available,cats,categories=dense_features();alphas=load_json(ROOT/'configs/protocol.json')['alpha_grid'];rows=[];stored={}
    for positive in (False,True):
        for names in (CLASSES,RELIABLE):
            cols=[CLASSES.index(x) for x in names];result,ranks,support=run_config('validation',positive,cols,values,available,cats,categories,alphas,prefix);rows+=result
            stored[(result[0]['profile'],len(cols))]=(ranks,support)
            event(stage,'configuration_complete',profile=result[0]['profile'],classes=len(cols),best_ndcg=max(r['ndcg_at_10'] for r in result))
    table=pd.DataFrame(rows);search_path=ART/('alpha_search.csv' if args.model_key=='strong' else 'smore_alpha_search.csv')
    tmp=search_path.with_suffix(search_path.suffix+'.tmp');table.to_csv(tmp,index=False);os.replace(tmp,search_path)
    best=max(rows,key=lambda r:(r['ndcg_at_10'],-r['alpha'],r['classes']==14,r['profile']=='all_history'))
    ranks,support=stored[(best['profile'],best['classes'])];chosen=ranks[best['alpha']]
    reranked_path=ART/('validation_reranked_per_user.parquet' if args.model_key=='strong' else 'validation_smore_reranked_per_user.parquet')
    tmp=reranked_path.with_suffix(reranked_path.suffix+'.tmp')
    pd.DataFrame({'row_index':np.arange(len(chosen)),'base_rank':base_state('validation',prefix)[1],'reranked_rank':chosen,'tactile_history_support':support}).to_parquet(tmp,index=False);os.replace(tmp,reranked_path)
    if args.model_key=='strong':
        lock['alpha_selected']=True;lock['alpha_not_yet_selected']=False;lock['alpha']=best['alpha'];lock['profile_method']=best['profile'];lock['tactile_classes']=best['classes'];lock['alpha_validation_ndcg_at_10']=best['ndcg_at_10'];lock['alpha_search_sha256']=sha(search_path)
        if args.revalidate_existing:
            lock['alpha_revalidated_average_ties']=True
            lock['alpha_revalidation_reason']='corrected tactile within-candidate percentile to protocol-specified average ties before any test evaluation'
        save_json(ART/'selection_lock.json',lock)
    else:
        smore['alpha_selected']=True;smore['alpha']=best['alpha'];smore['profile_method']=best['profile'];smore['tactile_classes']=best['classes'];smore['alpha_validation_ndcg_at_10']=best['ndcg_at_10'];smore['alpha_search_sha256']=sha(search_path)
        save_json(ART/'multimodal_selection.json',smore)
        lock['multimodal_validation_locked']=True;lock['multimodal_alpha']=best['alpha'];lock['multimodal_selection_sha256']=sha(ART/'multimodal_selection.json')
        save_json(ART/'selection_lock.json',lock)
    event(stage,'complete',alpha=best['alpha'],profile=best['profile'],classes=best['classes'],ndcg_at_10=best['ndcg_at_10'])

if __name__=='__main__':main()
