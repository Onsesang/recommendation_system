"""Pure, testable temporal/category-local preference operations."""
from collections import defaultdict

import numpy as np
import pandas as pd

from pipeline import CLASSES


def history_rows(frame, user, split, cutoff, target):
    allowed=['train'] if split=='validation' else ['train','validation']
    return frame[(frame.user_id==user) & frame.official_split.isin(allowed)
                 & (frame.timestamp<cutoff) & (frame.parent_asin!=target)]


def desired_presence(a, config):
    """State-specific local utility, NOT inference of the opposite tactile class."""
    if a['class_id'] not in CLASSES: return None,'unmapped'
    if a['property_state'] not in ['present','absent']: return None,'state_abstain'
    if a['attitude'] not in ['like','dislike']: return None,'attitude_abstain'
    if a['scope'] not in config['allowed_scopes']: return None,'scoped_or_third_party'
    if a['condition'] not in config['allowed_conditions']: return None,'conditional'
    return float((a['property_state']=='present') == (a['attitude']=='like')),None


def build_profile(history, category_map, config):
    # Each review/class contributes at most once, even if multiple lexical occurrences repeat it.
    grouped=defaultdict(list); provenance=defaultdict(list)
    for r in history.to_dict('records'):
        value,reason=desired_presence(r,config)
        category=category_map.get(r['parent_asin'])
        if reason or category is None or category in config['exclude_categories']: continue
        key=(r['event_id'],category,r['class_id'])
        grouped[key].append(value);provenance[key].append(r['sample_id'])
    reviews=defaultdict(list); sources=defaultdict(list)
    for (event,category,cls),values in grouped.items():
        reviews[(category,cls)].append(float(np.mean(values)))
        sources[(category,cls)].extend(provenance[(event,category,cls)])
    return {key:{'desired_presence':float(np.mean(values)),'review_count':len(values),
                 'source_ids':sources[key]} for key,values in reviews.items()}


def match_profile(profile, categories, probabilities, shrinkage=2.0):
    """Signed utility [-.5,.5]; zero adjustment when no category-local evidence."""
    raw=np.zeros(len(categories)); support=np.zeros(len(categories),dtype=np.int32)
    for (category,cls),entry in profile.items():
        want=entry['desired_presence']
        mask=np.asarray(categories)==category
        observed=mask & np.isfinite(probabilities[:,CLASSES.index(cls)])
        reliability=entry['review_count']/(entry['review_count']+shrinkage)
        raw[observed]+=(2*want-1)*(probabilities[observed,CLASSES.index(cls)]-.5)*reliability
        support[observed]+=1
    return np.divide(raw,support,out=np.zeros_like(raw),where=support>0),support


def blend(base,tactile,alpha):
    return (1-alpha)*np.asarray(base)+alpha*np.asarray(tactile)


def percentile(values):
    if len(values)<=1: return np.ones(len(values))
    return (pd.Series(values).rank(method='average').to_numpy()-1)/(len(values)-1)


def target_ranks(scores,positions):
    out=np.full(len(scores),scores.shape[1]+1,dtype=np.int32)
    order=np.arange(scores.shape[1])
    for i,pos in enumerate(positions):
        if pos>=0: out[i]=1+int(np.sum(scores[i]>scores[i,pos]))+int(np.sum((scores[i]==scores[i,pos]) & (order<pos)))
    return out


def metrics(ranks):
    r=np.asarray(ranks)
    if not len(r): return {'n':0,'ndcg_at_10':None,'hr_at_10':None,'mrr_at_10':None}
    return {'n':len(r),'ndcg_at_10':float(np.where(r<=10,1/np.log2(r+1),0).mean()),
            'hr_at_10':float((r<=10).mean()),'mrr_at_10':float(np.where(r<=10,1/r,0).mean())}
