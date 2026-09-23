"""Family-held-out explicit tactile retrieval, separate from next-item RQ2."""
import pandas as pd
from scipy.stats import rankdata
from common import *

SOURCE=PROJECT/'experiments/14_same_category_evaluation/artifacts/fixed_model_predictions.npz'
TARGETS=PROJECT/'experiments/12_class_multilabel_fashionclip_ft/artifacts/product_class_targets.npz'
PRODUCTS=PROJECT/'tactile_coldstart_qwen_v2_full/data/product_master_full_pool.json'
QUERIES=[[x] for x in RELIABLE]+load_json(ROOT/'configs/protocol.json')['tactile_query_pairs']
AUDIT_ROOT=PROJECT/'experiments/15_human_audit'

def human_audit_status():
    """Describe live audit completion without treating partial rows as gold."""
    manifest=load_json(AUDIT_ROOT/'artifacts/audit_manifest.json')
    annotation_path=AUDIT_ROOT/'annotations/human_audit.csv'
    completed=0
    if annotation_path.exists():
        annotations=pd.read_csv(annotation_path,dtype=str,keep_default_na=False)
        completed=int(annotations.completed.str.lower().eq('true').sum()) if 'completed' in annotations else 0
    cached=load_json(AUDIT_ROOT/'artifacts/human_audit_results.json')
    total=int(manifest.get('total_items',len(manifest.get('items',[]))))
    return {'status':'complete' if completed==total else ('not_started' if completed==0 else 'incomplete_not_integrated'),
            'completed_rows':completed,'total_rows':total,'cached_result_status':cached.get('status'),
            'cached_completed_rows':cached.get('completed_items'),'cached_result_stale':cached.get('completed_items')!=completed,
            'quantitative_human_gold_integrated':False,
            'reason':'audit is incomplete and annotation author provenance is not recorded in the artifact; AI judgments are never treated as human labels',
            'annotation_sha256':sha(annotation_path) if annotation_path.exists() else None}

def ranking_metrics(rel,order):
    rel=np.asarray(rel);ordered=rel[order];binary=(ordered>=1).astype(float);total=binary.sum();out={}
    for k in (5,10):
        gains=(2**ordered[:k]-1)/np.log2(np.arange(2,min(k,len(ordered))+2))
        ideal=np.sort(rel)[::-1];ideal_gain=(2**ideal[:k]-1)/np.log2(np.arange(2,min(k,len(ideal))+2))
        out[f'ndcg_at_{k}']=float(gains.sum()/ideal_gain.sum()) if ideal_gain.sum() else None
        out[f'precision_at_{k}']=float(binary[:k].sum()/k)
    out['recall_at_10']=float(binary[:10].sum()/total) if total else None
    pos=np.flatnonzero(binary);out['average_precision']=float(np.mean([(j+1)/(p+1) for j,p in enumerate(pos)])) if len(pos) else None
    out['items']=len(rel);out['positives']=int(total);return out

def split_data(split):
    pred=np.load(SOURCE,allow_pickle=True);target=np.load(TARGETS,allow_pickle=True);classes=target['classes'].tolist();allids=target['product_ids'].astype(str)
    ids=pred[f'{split}_product_ids'].astype(str);loc=pd.Index(allids).get_indexer(ids);assert (loc>=0).all()
    probs=pred[f'{split}_last2_probabilities'];values=target['values'][loc];mask=target['mask'][loc].astype(bool)
    products={x['product_id']:x for x in load_json(PRODUCTS)};catalog=pd.read_parquet(DATA/'catalog.parquet').set_index('parent_asin')
    pop=np.array([catalog.train_count.get(products[x]['parent_asin'],0) for x in ids],dtype=float)
    cats=np.array([products[x]['category'] for x in ids]);families=np.array([products[x]['product_family_id'] for x in ids])
    return ids,classes,probs,values,mask,pop,cats,families

def evaluate(split,selected=None):
    ids,classes,probs,values,mask,pop,cats,families=split_data(split);rows=[];cells=[];chosen={}
    for query in QUERIES:
        cols=[classes.index(x) for x in query];known=mask[:,cols].all(1);idx=np.flatnonzero(known)
        rel=(values[idx][:,cols]>=.5).sum(1).astype(float);tactile=probs[idx][:,cols].mean(1);base=pop[idx]
        bp=(rankdata(base,method='average')-1)/max(len(idx)-1,1);tp=(rankdata(tactile,method='average')-1)/max(len(idx)-1,1)
        name='+'.join(query);alphas=load_json(ROOT/'configs/protocol.json')['alpha_grid']
        if selected is None:
            scores=[]
            for a in alphas:
                order=np.lexsort((ids[idx],-(bp+a*(tp-bp))));m=ranking_metrics(rel,order);scores.append((m['ndcg_at_10'] or -1,-a,a))
            a=max(scores)[2];chosen[name]=a
        else:a=selected[name]
        for method,score in [('non_tactile_popularity',bp),('last2_tactile',tp),('selected_fusion',bp+a*(tp-bp))]:
            order=np.lexsort((ids[idx],-score));rows.append({'split':split,'query':name,'query_size':len(query),'method':method,'alpha':a if method=='selected_fusion' else (1 if method=='last2_tactile' else 0),**ranking_metrics(rel,order)})
        for cat in np.unique(cats[idx]):
            ci=idx[cats[idx]==cat]
            if len(ci)<10:continue
            cr=(values[ci][:,cols]>=.5).sum(1).astype(float);b=pop[ci];t=probs[ci][:,cols].mean(1)
            for method,score in [('non_tactile_popularity',b),('last2_tactile',t)]:
                order=np.lexsort((ids[ci],-score));cells.append({'split':split,'query':name,'category':cat,'method':method,**ranking_metrics(cr,order)})
    return rows,cells,chosen

def family_bootstrap(selected):
    """Paired family-level CI for Last2 minus non-tactile NDCG@10."""
    ids,classes,probs,values,mask,pop,cats,families=split_data('test');rng=np.random.default_rng(SEED);per_query=[]
    for query in QUERIES:
        cols=[classes.index(x) for x in query];idx=np.flatnonzero(mask[:,cols].all(1));rel=(values[idx][:,cols]>=.5).sum(1).astype(float)
        fam=families[idx];unique=np.unique(fam);groups={f:np.flatnonzero(fam==f) for f in unique};delta=[]
        for _ in range(1000):
            sampled=rng.choice(unique,size=len(unique),replace=True);take=np.concatenate([groups[f] for f in sampled])
            b=np.lexsort((ids[idx][take],-pop[idx][take]));t=np.lexsort((ids[idx][take],-probs[idx][take][:,cols].mean(1)))
            bm=ranking_metrics(rel[take],b)['ndcg_at_10'];tm=ranking_metrics(rel[take],t)['ndcg_at_10'];delta.append((tm or 0)-(bm or 0))
        per_query.append(delta)
    mean=np.asarray(per_query).mean(0)
    return {'unit':'product family within each query; query deltas macro-averaged','replicates':1000,'seed':SEED,
            'mean_delta_ndcg_at_10':float(mean.mean()),'ci95_low':float(np.percentile(mean,2.5)),'ci95_high':float(np.percentile(mean,97.5))}

def main():
    event('explicit_tactile','started');dev,devcells,selected=evaluate('development');test,testcells,_=evaluate('test',selected)
    for path,frame in ((ART/'explicit_tactile_per_query.csv',pd.DataFrame(dev+test)),
                       (ART/'explicit_tactile_same_category.csv',pd.DataFrame(devcells+testcells))):
        tmp=path.with_suffix(path.suffix+'.tmp');frame.to_csv(tmp,index=False);os.replace(tmp,path)
    testdf=pd.DataFrame(test);summary={}
    for method,g in testdf.groupby('method'):
        summary[method]={'queries':len(g),'mean_ndcg_at_10':float(g.ndcg_at_10.mean()),'mean_precision_at_10':float(g.precision_at_10.mean())}
    result={'status':'complete_exploratory_family_heldout','development_selected_alpha_per_query':selected,'test_summary':summary,'family_bootstrap_last2_minus_non_tactile':family_bootstrap(selected),
      'ground_truth':'existing v3 observed pseudo-labels only; mask=0 excluded, never negative','positive_rule':'target_probability >= 0.5',
      'base_limitation':'query benchmark has no user IDs; non-tactile baseline is train popularity, not personalized strong scores',
      'prediction_source':str(SOURCE),'prediction_sha256':sha(SOURCE),'new_last2_inference_for_this_benchmark':False,
      'prior_test_inspection':'Experiment 14 already inspected this same v3 test; treat as exploratory replication, not fresh confirmatory test',
      'human_audit':human_audit_status()}
    save_json(ART/'tactile_recommendation_results.json',result);event('explicit_tactile','complete',**summary.get('last2_tactile',{}))

if __name__=='__main__':main()
