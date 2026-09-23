"""Resume-safe exact full-catalog Top-K candidates for the locked backbone."""
import argparse
import pandas as pd
import torch
from common import *
from recommender import RecData,Scorer,new_model,setup

def load_model(name,record,d,c,device,expected_sha=None):
    if name=='popularity':return None
    if expected_sha is not None and sha(record['checkpoint'])!=expected_sha:
        raise RuntimeError(f'selected checkpoint hash changed: {name}')
    ck=torch.load(record['checkpoint'],map_location=device,weights_only=False)
    model=new_model(name,d,c).to(device);model.load_state_dict(ck['state_dict'],strict=True);return model

def pop_candidates(d,hist,u,k):
    seen=np.asarray(hist.get(int(u),[]),dtype=np.int64)
    head=d.pop_order[:k+len(seen)]
    return head[~np.isin(head,seen,assume_unique=False)][:k].astype(np.int32)

def main():
    p=argparse.ArgumentParser();p.add_argument('--split',choices=['validation','test'],default='validation');p.add_argument('--model-key',choices=['strong','smore'],default='strong');p.add_argument('--batch-size',type=int,default=128);args=p.parse_args()
    lock=load_json(ART/'selection_lock.json')
    if args.split=='test':
        if lock.get('status')!='test_evaluated_no_retuning_allowed':
            raise RuntimeError('run the guarded backbone test before opening test candidates')
        if lock.get('alpha_selected') is not True or lock.get('multimodal_validation_locked') is not True:
            raise RuntimeError('finish all validation decisions before test candidates')
    elif lock.get('status')!='locked_before_any_new_test_evaluation':
        raise RuntimeError('validation candidate generation is forbidden after the test boundary opens')
    if args.model_key=='strong':
        name=lock['strong_backbone'];record=lock['selected_runs'].get(name);k=lock['candidate_k'];prefix=args.split
    else:
        selection=load_json(ART/'multimodal_selection.json')
        if selection.get('status')!='validation_locked':
            raise RuntimeError('SMORE validation selection is not locked')
        if args.split=='test' and sha(ART/'multimodal_selection.json')!=lock.get('multimodal_selection_sha256'):
            raise RuntimeError('SMORE selection hash differs from the pre-test lock')
        name='smore';record=selection['selected_run'];k=selection['candidate_k'];prefix=f'{args.split}_smore'
    manifest_path=ART/f'{prefix}_candidate_manifest.json'
    if manifest_path.exists() and load_json(manifest_path).get('status')=='complete':
        raise RuntimeError(f'{prefix} candidate generation is already complete; rerun forbidden')
    stage=f'{prefix}_candidates';event(stage,'started',model=name,k=k)
    if args.split=='test' and name=='smore':
        for graph_name,expected in lock.get('generic_graph_sha256',{}).items():
            graph=DATA/'smore'/graph_name
            if not graph.is_file() or sha(graph)!=expected:raise RuntimeError(f'pinned generic graph changed: {graph_name}')
    expected_sha=lock.get('selected_checkpoint_sha256',{}).get(name) if args.split=='test' else None
    device=setup();d=RecData();c=load_json(ROOT/'configs/backbones.json');model=load_model(name,record,d,c,device,expected_sha)
    hist=d.histories(args.split);scorer=Scorer(name,model,d,hist,device);targets=pd.read_parquet(DATA/f'{args.split}_targets.parquet')
    # No-history users cannot form a general tactile profile, so their base ranks
    # are evaluated but no redundant K-vector is persisted.
    supported=np.flatnonzero(targets.history_length.to_numpy()>0);folder=ART/f'{prefix}_candidate_chunks';folder.mkdir(parents=True,exist_ok=True)
    done=0;item_ids=torch.arange(d.nitems,device=device)
    for start in range(0,len(supported),args.batch_size):
        idx=supported[start:start+args.batch_size];tag=f'{start:09d}_{start+len(idx)-1:09d}';dest=folder/f'{tag}.npz'
        if dest.exists():done+=len(idx);continue
        batch=targets.iloc[idx];uids=batch.uid.to_numpy();truth=batch.iid.to_numpy()
        candidate=np.empty((len(idx),k),dtype=np.int32);raw=np.empty((len(idx),k),dtype=np.float32);ranks=np.empty(len(idx),dtype=np.int32)
        active=np.array([scorer.usable(u) for u in uids])
        inactive_idx=np.flatnonzero(~active)
        for jj in inactive_idx:
            u=uids[jj];candidate[jj]=pop_candidates(d,hist,u,k);raw[jj]=d.catalog.train_count.to_numpy()[candidate[jj]]
            ranks[jj]=scorer.popularity_rank(u,truth[jj])
        active_idx=np.flatnonzero(active)
        if len(active_idx):
            scores=scorer.scores(uids[active_idx]);t=torch.tensor(truth[active_idx],device=device);ts=scores[torch.arange(len(t),device=device),t]
            # Seen items are deliberately -inf, but NaN/+inf or a non-finite
            # target score would make ranks/top-k silently invalid.
            if torch.isnan(scores).any() or torch.isposinf(scores).any():
                raise FloatingPointError(f'{stage}: non-finite catalog score')
            if not torch.isfinite(ts).all():raise FloatingPointError(f'{stage}: non-finite target score')
            rr=1+(scores>ts[:,None]).sum(-1)+((scores==ts[:,None])&(item_ids[None,:]<t[:,None])).sum(-1)
            # torch.topk does not define which IDs survive a boundary tie. The
            # protocol requires parent-ASIN ascending (iid ascending), so use
            # topk only to discover the score threshold and resolve the exact
            # boundary deterministically.
            probe,probe_ids=torch.topk(scores,k,dim=1,largest=True,sorted=False)
            if not torch.isfinite(probe).all():raise FloatingPointError(f'{stage}: non-finite Top-K score')
            thresholds=probe.min(1).values
            candidate[active_idx]=probe_ids.cpu().numpy().astype('int32')
            raw[active_idx]=probe.float().cpu().numpy()
            all_ties=(scores==thresholds[:,None]).sum(1)
            selected_ties=(probe==thresholds[:,None]).sum(1)
            ambiguous=torch.nonzero(all_ties>selected_ties,as_tuple=False).squeeze(1).cpu().numpy()
            for local in ambiguous:
                jj=active_idx[local]
                greater=torch.nonzero(scores[local]>thresholds[local],as_tuple=False).squeeze(1)
                remaining=k-len(greater)
                tied=torch.nonzero(scores[local]==thresholds[local],as_tuple=False).squeeze(1)[:remaining]
                chosen=torch.cat([greater,tied]);chosen_scores=scores[local,chosen]
                candidate[jj]=chosen.cpu().numpy().astype('int32');raw[jj]=chosen_scores.float().cpu().numpy()
            ranks[active_idx]=rr.cpu().numpy().astype('int32')
        tmp=dest.with_suffix('.tmp')
        with open(tmp,'wb') as f:np.savez_compressed(f,row_index=idx.astype('int32'),uid=uids.astype('int32'),target=truth.astype('int32'),base_rank=ranks,candidate=candidate,base_score=raw)
        os.replace(tmp,dest);done+=len(idx)
        if done%4096<len(idx):event(stage,'progress',done=done,total=len(supported))
    # Save no-history exact ranks compactly for all-user metrics.
    no=np.flatnonzero(targets.history_length.to_numpy()==0)
    # Empty history means the exact filtered popularity rank is the catalog
    # popularity rank; vectorize this large (1.75M-user) cohort.
    nr=d.pop_rank[targets.iid.to_numpy()[no]].astype(np.int32)
    no_path=ART/f'{prefix}_no_history_ranks.parquet';tmp=no_path.with_suffix(no_path.suffix+'.tmp')
    pd.DataFrame({'row_index':no,'uid':targets.uid.iloc[no].to_numpy(),'target':targets.iid.iloc[no].to_numpy(),'base_rank':nr}).to_parquet(tmp,index=False);os.replace(tmp,no_path)
    manifest={'status':'complete','split':args.split,'model':name,'k':k,'supported_users':len(supported),'no_history_users':len(no),
              'chunks':len(list(folder.glob('*.npz'))),'selection_lock_sha256':sha(ART/'selection_lock.json')}
    if record and record.get('checkpoint'):
        manifest['checkpoint_sha256']=sha(record['checkpoint'])
    if args.model_key=='smore':manifest['multimodal_selection_sha256']=sha(ART/'multimodal_selection.json')
    save_json(manifest_path,manifest)
    event(stage,'complete',supported_users=len(supported),no_history_users=len(no),chunks=len(list(folder.glob('*.npz'))))

if __name__=='__main__':main()
