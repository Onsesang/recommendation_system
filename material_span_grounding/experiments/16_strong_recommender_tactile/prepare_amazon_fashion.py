"""Full official split, no tactile intersection; temporal checks before training."""
import pandas as pd
import pyarrow.ipc as ipc
from common import *

def main():
    event('prepare_data','started')
    DATA.mkdir(parents=True,exist_ok=True)
    old=PROJECT/'experiments/16_recommendation_reranking'
    config=load_json(old/'configs/recommendation_config.json')['official_dataset']
    frames=[]; hashes={}
    for split in ('train','validation','test'):
        path=old/config['files'][split]
        hashes[split]=sha(path)
        assert hashes[split]==config['expected_sha256'][split],split
        df=pd.read_csv(path)
        assert df[['user_id','parent_asin','rating','timestamp']].notna().all().all()
        df['split']=split
        frames.append(df)
    events=pd.concat(frames,ignore_index=True)
    assert not events.duplicated(['user_id','parent_asin']).any()
    users=np.sort(events.user_id.unique()); items=np.sort(events.parent_asin.unique())
    events['uid']=pd.Index(users).get_indexer(events.user_id).astype('int32')
    events['iid']=pd.Index(items).get_indexer(events.parent_asin).astype('int32')
    events=events.sort_values(['uid','timestamp','iid'],kind='stable')
    counts={s:np.bincount(events.loc[events.split==s,'uid'],minlength=len(users)) for s in ('train','validation','test')}
    assert np.max(counts['validation'])==1 and np.max(counts['test'])==1
    bounds=events.groupby(['uid','split']).timestamp.agg(['min','max']).unstack()
    checks={}
    for a,b in [('train','validation'),('validation','test'),('train','test')]:
        mask=bounds['max'][a].notna() & bounds['min'][b].notna()
        checks[f'{a}_before_{b}']=bool((bounds['max'][a][mask]<=bounds['min'][b][mask]).all())
        assert checks[f'{a}_before_{b}']
    train_counts=np.bincount(events.loc[events.split=='train','iid'],minlength=len(items)).astype('int32')
    catalog=pd.DataFrame({'iid':np.arange(len(items),dtype='int32'),'parent_asin':items,'train_count':train_counts})
    catalog.to_parquet(DATA/'catalog.parquet',index=False)
    pd.DataFrame({'uid':np.arange(len(users),dtype='int32'),'user_id':users}).to_parquet(DATA/'users.parquet',index=False)
    events.to_parquet(DATA/'events.parquet',index=False)
    for split in ('validation','test'):
        target=events[events.split==split].copy()
        target['train_history_length']=counts['train'][target.uid]
        target['history_length']=(counts['train']+(counts['validation'] if split=='test' else 0))[target.uid]
        target['target_train_count']=train_counts[target.iid]
        target.to_parquet(DATA/f'{split}_targets.parquet',index=False)
    raw_count=0; raw_users=set(); raw_items=set(); verified=0; maps=[]
    for path in sorted((WORKSPACE/'yoojeong/amazon_reviews_all/review_Amazon_Fashion/full').glob('*.arrow')):
        reader=ipc.open_stream(str(path))
        for batch in reader:
            b=batch.select(['asin','parent_asin','user_id','verified_purchase']).to_pandas()
            raw_count+=len(b); raw_users.update(b.user_id);raw_items.update(b.parent_asin);verified+=int(b.verified_purchase.sum())
            maps.append(b[['asin','parent_asin']].drop_duplicates())
    mapping=pd.concat(maps,ignore_index=True).drop_duplicates()
    mapping.to_parquet(DATA/'child_parent_mapping.parquet',index=False)
    v3=pd.read_json(PROJECT/'experiments/12_class_multilabel_fashionclip_ft/artifacts/product_class_targets.jsonl',lines=True)
    idcol='asin' if 'asin' in v3 else 'product_id'
    mids=mapping[mapping.asin.isin(v3[idcol])]
    mapping_report={'source':'explicit raw review asin,parent_asin fields; no fuzzy matching','tactile_products':int(v3[idcol].nunique()),
                    'mapped_child_asins':int(mids.asin.nunique()),'unmapped_child_asins':int(v3[idcol].nunique()-mids.asin.nunique()),
                    'one_to_many_child_asins':int((mids.groupby('asin').parent_asin.nunique()>1).sum()),
                    'many_to_one_parents':int((mids.groupby('parent_asin').asin.nunique()>1).sum()),'mapped_parents':int(mids.parent_asin.nunique())}
    save_json(ART/'item_mapping_report.json',mapping_report)
    stats={'raw':{'reviews':raw_count,'users':len(raw_users),'items':len(raw_items),'verified_purchase_true':verified},
           'processed':{'interactions':len(events),'users':len(users),'items':len(items),'train_items':int((train_counts>0).sum())},
           'official_split':config,'verified_split_hashes':hashes,'history_all_interactions':distribution(sum(counts.values())),
           'split_event_counts':{s:int(c.sum()) for s,c in counts.items()},
           'split_event_counts_per_all_users':{s:distribution(c) for s,c in counts.items()},
           'evaluation_histories':{},'checks':checks,'catalog_intersection_with_tactile':False,
           'interaction_semantics':'review/rating event, not inferred click or purchase; official split deduplicates user-parent pairs'}
    for split in ('validation','test'):
        t=pd.read_parquet(DATA/f'{split}_targets.parquet')
        stats['evaluation_histories'][split]={'available_history':distribution(t.history_length),'train_history':distribution(t.train_history_length),
                                            'target_train_count_zero':int((t.target_train_count==0).sum())}
    save_json(ART/'amazon_fashion_statistics.json',stats)
    event('prepare_data','complete',**stats['processed'],evaluation_histories=stats['evaluation_histories'])

if __name__=='__main__': main()
