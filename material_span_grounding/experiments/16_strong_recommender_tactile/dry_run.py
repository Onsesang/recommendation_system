"""100 real training users / 1000 catalog items; no dry-run metric enters selection."""
import torch
from common import *
from recommender import RecData,new_model,setup,metrics

def main():
    device=setup();d=RecData();c=load_json(ROOT/'configs/backbones.json')
    uids=d.train_uids[:100];small=d.train[d.train.uid.isin(uids)].copy()
    item_ids=np.unique(small.iid)[:1000]
    if len(item_ids)<1000:
        fill=np.setdiff1d(np.arange(d.nitems),item_ids)[:1000-len(item_ids)]
        item_ids=np.sort(np.concatenate([item_ids,fill]))
    small=small[small.iid.isin(item_ids)].copy()
    small['iid']=np.searchsorted(item_ids,small.iid)
    d.train=small;d.nitems=1000;d.train_uids=uids
    c['dim']=16;results={}
    for name in ('bpr','lightgcn','sasrec'):
        m=new_model(name,d,c).to(device);opt=torch.optim.Adam(m.parameters(),lr=.001)
        if name=='sasrec':
            seq=torch.tensor([[0,1,2,3]]*100,device=device);pos=torch.tensor([[0,2,3,4]]*100,device=device);neg=torch.tensor([[0,5,6,7]]*100,device=device)
            loss=m.loss(seq,pos,neg)
        else:
            batch=small.head(100);u=torch.tensor(batch.local_uid.to_numpy(),device=device);p=torch.tensor(batch.iid.to_numpy(),device=device);n=(p+1)%1000
            loss=m.loss(u,p,n)
        assert torch.isfinite(loss);loss.backward();opt.step()
        if name=='sasrec':scores=m(seq)[:,-1]@m.item.weight[1:].T
        else:
            ue,ie=m.representations();scores=ue@ie.T
        assert scores.shape==(100,1000);assert torch.isfinite(scores).all()
        results[name]={'forward_backward_finite':True,'score_shape':list(scores.shape),'loss':float(loss.detach())}
    results['metric_smoke']=metrics([1,2,4,20]);results['status']='recommender_dry_run_passed_pending_image_pilot'
    save_json(ART/'dry_run.json',results);event('recommender_dry_run','complete',users=100,items=1000,models=list(results)[:3])

if __name__=='__main__':main()
