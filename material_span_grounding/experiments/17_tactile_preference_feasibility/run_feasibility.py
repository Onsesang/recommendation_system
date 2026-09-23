"""Read-only scan of the full local raw review corpus; writes only experiment 17."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
OUT = ROOT / 'artifacts'


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def counts(values):
    return {'units': len(values), 'mean': float(values.mean()), 'median': float(values.median()),
            'p90': float(values.quantile(.9)), 'p99': float(values.quantile(.99)),
            'at_least': {str(k): int((values >= k).sum()) for k in [2,3,5,10]}}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    source = PROJECT / 'tactile_coldstart_qwen_v2_full/src/tactile_coldstart/full_pool.py'
    # Reuse the existing lexical screen verbatim, without importing its project dependencies.
    import ast, re
    tree = ast.parse(source.read_text())
    assignment = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'AXIS_PATTERNS' for t in n.targets))
    scope = {'re': re}
    exec(compile(ast.Module(body=[assignment], type_ignores=[]), str(source), 'exec'), scope)
    patterns = scope['AXIS_PATTERNS']
    combined = '|'.join(p.pattern for p in patterns.values())
    rawdir = PROJECT.parent / 'yoojeong/amazon_reviews_all/review_Amazon_Fashion/full'
    chunks, lexical = [], []
    columns = ['user_id','asin','parent_asin','timestamp','rating','verified_purchase']
    rows = 0
    raw_hashes = {}
    for path in sorted(rawdir.glob('*.arrow')):
        raw_hashes[str(path)] = sha(path)
        with pa.memory_map(str(path), 'r') as f:
            for batch in pa.ipc.open_stream(f):
                table = pa.Table.from_batches([batch])
                chunks.append(table.select(columns))
                hit = pc.fill_null(pc.match_substring_regex(table['text'], combined, ignore_case=True), False)
                lexical.append(table.filter(hit).select(columns + ['text','title']))
                rows += len(table)
                if rows % 250000 == 0:
                    print(f'scanned={rows}', flush=True)
    events = pa.concat_tables(chunks).to_pandas()
    lex = pa.concat_tables(lexical).to_pandas()
    del chunks, lexical
    events['raw_row'] = range(len(events))
    official = pd.concat([pd.read_csv(PROJECT/f'experiments/16_recommendation_reranking/source_data/Amazon_Fashion.{file}.csv').assign(official_split=split)
                          for split,file in [('train','train'),('validation','valid'),('test','test')]], ignore_index=True)
    keys = ['user_id','parent_asin','timestamp']
    assert not official.duplicated(keys).any()
    lex = lex.drop_duplicates(keys, keep='first').merge(official[keys+['official_split']], on=keys, how='left', validate='one_to_one')
    lex['event_id'] = [hashlib.sha256(f'{u}|{p}|{t}'.encode()).hexdigest()[:24] for u,p,t in lex[keys].itertuples(index=False, name=None)]
    lex['axis_hints'] = [json.dumps([k for k,p in patterns.items() if p.search(text)]) for text in lex.text]
    lex.to_parquet(OUT/'lexical_reviews.parquet', index=False)
    products = pd.read_parquet(PROJECT/'experiments/16_recommendation_reranking/artifacts/product_tactile_profiles.parquet')
    catalog = set(products.item_id)
    eligible = official[official.parent_asin.isin(catalog)]
    cohorts = []
    stat = {}
    first_seen = events.groupby('parent_asin').timestamp.min()
    product_first = products.item_id.map(first_seen)
    for split, history_splits in [('validation',['train']),('test',['train','validation'])]:
        targets = eligible[eligible.official_split == split].copy()
        history = official[official.official_split.isin(history_splits)]
        ehistory = history[history.parent_asin.isin(catalog)]
        targets = targets[targets.user_id.isin(ehistory.user_id)]
        past = lex[lex.official_split.isin(history_splits)]
        for name, frame in [('all_history_count',history),('eligible_history_count',ehistory),('past_lexical_reviews_all_items',past),('past_lexical_reviews_eligible_items',past[past.parent_asin.isin(catalog)])]:
            targets[name] = targets.user_id.map(frame.groupby('user_id').size()).fillna(0).astype(int)
        future_keys = set(lex[lex.official_split == split].set_index(keys).index)
        targets['future_lexical'] = [tuple(x) in future_keys for x in targets[keys].itertuples(index=False, name=None)]
        past_axes={}
        for u,hints in past[['user_id','axis_hints']].itertuples(index=False,name=None):
            past_axes.setdefault(u,set()).update(json.loads(hints))
        future_axes={tuple(row[:3]):set(json.loads(row[3])) for row in lex[lex.official_split==split][keys+['axis_hints']].itertuples(index=False,name=None)}
        targets['past_future_shared_axis']=[bool(past_axes.get(u,set()) & future_axes.get((u,p,t),set())) for u,p,t in targets[keys].itertuples(index=False,name=None)]
        maxpast = history.groupby('user_id').timestamp.max()
        targets['latest_history_timestamp'] = targets.user_id.map(maxpast)
        targets['strict_time_ok'] = targets.latest_history_timestamp < targets.timestamp
        targets = targets.merge(products[['item_id','category','v3_family_split']],left_on='parent_asin',right_on='item_id')
        hsets = ehistory.groupby('user_id').parent_asin.agg(set).to_dict()
        sizes = []
        for row in targets.itertuples():
            # First review is only a conservative proxy for product availability, never an actual launch date.
            available = set(products.loc[(products.category == row.category) & (product_first < row.timestamp), 'item_id'])
            sizes.append(len(available - hsets.get(row.user_id,set())))
        targets['same_category_unseen_first_review_proxy'] = sizes
        both = targets.future_lexical & (targets.past_lexical_reviews_all_items > 0) & targets.strict_time_ok
        eligible_both = targets.future_lexical & (targets.past_lexical_reviews_eligible_items > 0) & targets.strict_time_ok
        stat[split] = {'cohort_users':len(targets),'future_lexical':int(targets.future_lexical.sum()),
            'past_and_future_lexical_all_history':int(both.sum()), 'past_and_future_lexical_eligible_history':int(eligible_both.sum()),
            'past_at_least_2_and_future':int((both & (targets.past_lexical_reviews_all_items >= 2)).sum()),
            'shared_lexical_axis_past_future':int((both & targets.past_future_shared_axis).sum()),
            'non_strict_timestamp_cases':int((~targets.strict_time_ok).sum()),
            'same_category_candidates_proxy':{str(k):int((targets.same_category_unseen_first_review_proxy>=k).sum()) for k in [20,30,50]},
            'joint_lexical_and_same_category_50':int((both & (targets.same_category_unseen_first_review_proxy>=50)).sum()),
            'joint_lexical_v3_test_family':int((both & (targets.v3_family_split=='test')).sum())}
        cohorts.append(targets)
    pd.concat(cohorts).to_parquet(OUT/'cohort_events.parquet',index=False)
    event_pairs = events.drop_duplicates(['user_id','parent_asin'])
    matched = events.merge(official[keys],on=keys,how='inner')
    report = {'status':'complete_lexical_feasibility_not_preference_ground_truth', 'raw_reviews':len(events),
        'raw_users':events.user_id.nunique(), 'raw_items':events.parent_asin.nunique(),
        'raw_user_review_density':counts(events.groupby('user_id').size()),
        'unique_user_parent_density':counts(event_pairs.groupby('user_id').size()),
        'official_user_density':counts(official.groupby('user_id').size()),
        'raw_item_review_density':counts(events.groupby('parent_asin').size()),
        'timestamp_min':int(events.timestamp.min()), 'timestamp_max':int(events.timestamp.max()),
        'official_events':len(official), 'raw_to_official_unique_events_matched':len(matched.drop_duplicates(keys)),
        'lexical_unique_events':len(lex), 'lexical_user_density':counts(lex.groupby('user_id').size()),
        'official_lexical_by_split':lex.official_split.value_counts(dropna=False).rename(index={None:'unmatched'}).to_dict(),
        'cohorts':stat, 'lexical_patterns':{k:p.pattern for k,p in patterns.items()},
        'limitations':['Lexical screen is not semantic property or like/dislike annotation; no measured recall.',
                      'Counts using full histories allow items outside the tactile image catalog.',
                      'First review timestamp is a catalog availability proxy, not product release date.',
                      'Same-category counts are diagnostic, not an oracle filter for general recommendation.',
                      'Official leave-last-out is user-relative, not a globally chronological model-training split.'],
        'source_hashes':raw_hashes}
    (OUT/'feasibility_results.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,default=int))
    print(json.dumps({k:report[k] for k in ['raw_reviews','raw_users','lexical_unique_events','lexical_user_density','cohorts']},indent=2))


if __name__ == '__main__':
    main()
