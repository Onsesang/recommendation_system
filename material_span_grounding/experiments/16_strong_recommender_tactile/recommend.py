"""Inference service for full-catalog strong and explicit-tactile recommendation."""
import pandas as pd
import torch
from scipy.stats import rankdata
from common import *
from recommender import RecData,Scorer,new_model,setup

class RecommendationService:
    def __init__(self):
        self.lock=load_json(ART/'selection_lock.json');self.device=setup();self.d=RecData();self.config=load_json(ROOT/'configs/backbones.json')
        self.metadata=pd.read_parquet(DATA/'item_metadata.parquet').sort_values('iid').reset_index(drop=True)
        self.users=pd.read_parquet(DATA/'users.parquet').set_index('user_id').uid
        name=self.lock['strong_backbone'];self.strong_name=name;self.strong=self._load(name,self.lock['selected_runs'].get(name))
        self.strong_scorer=Scorer(name,self.strong,self.d,self.d.histories('test'),self.device)
        self.tactile=np.zeros((self.d.nitems,len(CLASSES)),dtype=np.float32);self.tactile_available=np.zeros(self.d.nitems,dtype=bool)
        profiles=pd.read_parquet(ART/'product_tactile_profiles.parquet')
        ids=profiles.iid.to_numpy();self.tactile[ids]=profiles[CLASSES].to_numpy(dtype=np.float32);self.tactile_available[ids]=True
        self.smore=None;self.smore_scorer=None
        selection_path=ART/'multimodal_selection.json'
        if selection_path.exists():
            selection=load_json(selection_path)
            if selection.get('status')=='validation_locked':
                self.smore=self._load('smore',selection['selected_run']);self.smore_scorer=Scorer('smore',self.smore,self.d,self.d.histories('test'),self.device)

    def _load(self,name,record):
        if name=='popularity':return None
        checkpoint=torch.load(record['checkpoint'],map_location=self.device,weights_only=False)
        model=new_model(name,self.d,self.config).to(self.device);model.load_state_dict(checkpoint['state_dict'],strict=True);model.eval();return model

    def _uid(self,user_id):
        if not user_id:return None
        try:return int(self.users.loc[user_id])
        except KeyError:return None

    def _base(self,scorer,uid,category):
        if uid is not None and scorer.usable(uid):raw=scorer.scores(np.array([uid],dtype=np.int32))[0].float().cpu().numpy()
        else:
            raw=self.d.catalog.train_count.to_numpy(dtype=np.float32).copy()
            if uid is not None:raw[np.asarray(scorer.hist.get(uid,[]),dtype=np.int64)]=-np.inf
        allowed=np.isfinite(raw)
        if category:allowed&=self.metadata.category.to_numpy()==category
        ids=np.flatnonzero(allowed);k=min(int(self.lock['candidate_k']),len(ids))
        order=np.lexsort((self.metadata.parent_asin.to_numpy()[ids],-raw[ids]))[:k]
        return ids[order],raw[ids[order]]

    def recommend(self,user_id=None,category=None,desired=None,top_k=10,alpha=None,system='strong'):
        desired=list(desired or []);unknown=set(desired)-set(CLASSES)
        if unknown:raise ValueError(f'unknown tactile classes: {sorted(unknown)}')
        scorer=self.smore_scorer if system=='multimodal' and self.smore_scorer is not None else self.strong_scorer
        uid=self._uid(user_id);candidate,base_raw=self._base(scorer,uid,category)
        base_norm=(rankdata(base_raw,method='average')-1)/max(len(candidate)-1,1)
        tactile_match=np.full(len(candidate),np.nan,dtype=np.float32);final=base_norm.copy()
        if desired:
            cols=[CLASSES.index(x) for x in desired];valid=self.tactile_available[candidate]
            tactile_match[valid]=self.tactile[candidate[valid]][:,cols].mean(1)
            if valid.any():
                tactile_norm=np.full(len(candidate),.5,dtype=np.float32)
                tactile_norm[valid]=(rankdata(tactile_match[valid],method='average')-1)/max(valid.sum()-1,1)
                a=float(self.lock.get('alpha',0) if alpha is None else alpha)
                final[valid]=base_norm[valid]+a*(tactile_norm[valid]-base_norm[valid])
        order=np.lexsort((self.metadata.parent_asin.to_numpy()[candidate],-final))[:top_k]
        rows=[]
        for rank,j in enumerate(order,1):
            iid=int(candidate[j]);m=self.metadata.iloc[iid]
            probs={name:float(self.tactile[iid,CLASSES.index(name)]) for name in desired} if self.tactile_available[iid] else {}
            rows.append({'rank':rank,'iid':iid,'parent_asin':m.parent_asin,'title':m.title,'category':m.category,'image_url':m.image_url,
                         'base_raw_score':float(base_raw[j]),'base_rank_percentile':float(base_norm[j]),'tactile_match':None if np.isnan(tactile_match[j]) else float(tactile_match[j]),
                         'final_score':float(final[j]),'tactile_available':bool(self.tactile_available[iid]),'selected_tactile_probabilities':probs})
        return {'requested_user_id':user_id,'resolved_uid':uid,'fallback':'train popularity' if uid is None or not scorer.usable(uid) else None,
                'system':'SMORE' if scorer is self.smore_scorer else self.strong_name,'category_filter':category,'desired_tactile':desired,'candidate_k':len(candidate),'results':rows}

def main():
    import argparse,json
    p=argparse.ArgumentParser();p.add_argument('--user-id');p.add_argument('--category');p.add_argument('--tactile',nargs='*',default=[]);p.add_argument('--top-k',type=int,choices=[5,10],default=10);p.add_argument('--alpha',type=float);p.add_argument('--system',choices=['strong','multimodal'],default='strong');args=p.parse_args()
    print(json.dumps(RecommendationService().recommend(args.user_id,args.category,args.tactile,args.top_k,args.alpha,args.system),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
