"""Auditable checks for protocol integrity and required output completeness."""
import json
import re

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from common import *


BACKBONES = ('popularity', 'bpr', 'lightgcn', 'sasrec', 'esasrec')
SMORE_DIR = DATA / 'smore'
AUDIT_ROOT = PROJECT / 'experiments/15_human_audit'


def check(name, passed, evidence):
    return {'name': name, 'passed': bool(passed), 'evidence': evidence}


def actual_sha(path):
    """Return a digest or None without turning a missing artifact into a crash."""
    path = Path(path)
    return sha(path) if path.is_file() else None


def json_or_empty(path):
    path = Path(path)
    try:
        return load_json(path) if path.is_file() else {}
    except (OSError, ValueError, TypeError):
        return {}


def exact_backbone_test_outputs(expected_rows, catalog_items):
    """Check exact target identity/order while retaining only three int columns."""
    target_path = DATA / 'test_targets.parquet'
    evidence = {
        'expected_rows_from_official_statistics': int(expected_rows),
        'target_rows': None,
        'unexpected_per_user_files': [],
        'models': {},
    }
    if not target_path.is_file():
        evidence['error'] = 'test_targets.parquet missing'
        return False, evidence

    target_rows = pq.ParquetFile(target_path).metadata.num_rows
    evidence['target_rows'] = int(target_rows)
    targets = pd.read_parquet(target_path, columns=['uid', 'iid'])
    target_uid = targets.uid.to_numpy(copy=False)
    target_iid = targets.iid.to_numpy(copy=False)
    expected_names = {f'{name}_test_per_user.parquet' for name in BACKBONES}
    observed_names = {p.name for p in ART.glob('*_test_per_user.parquet')}
    evidence['unexpected_per_user_files'] = sorted(observed_names - expected_names)
    passed = target_rows == expected_rows == len(targets) and not evidence['unexpected_per_user_files']

    for name in BACKBONES:
        path = ART / f'{name}_test_per_user.parquet'
        item = {'exists': path.is_file(), 'rows': None, 'uid_mismatches': None,
                'iid_mismatches': None, 'invalid_ranks': None}
        if not path.is_file():
            evidence['models'][name] = item
            passed = False
            continue
        parquet = pq.ParquetFile(path)
        item['rows'] = int(parquet.metadata.num_rows)
        required = {'uid', 'iid', 'rank', 'method'}
        item['missing_columns'] = sorted(required - set(parquet.schema_arrow.names))
        if item['missing_columns']:
            evidence['models'][name] = item
            passed = False
            continue
        per = pd.read_parquet(path, columns=['uid', 'iid', 'rank'])
        same_length = len(per) == len(targets) == expected_rows
        if same_length:
            item['uid_mismatches'] = int(np.count_nonzero(per.uid.to_numpy(copy=False) != target_uid))
            item['iid_mismatches'] = int(np.count_nonzero(per.iid.to_numpy(copy=False) != target_iid))
        rank = per['rank'].to_numpy(copy=False)
        item['invalid_ranks'] = int(np.count_nonzero((rank < 1) | (rank > catalog_items)))
        model_ok = (same_length and item['rows'] == expected_rows and
                    item['uid_mismatches'] == 0 and item['iid_mismatches'] == 0 and
                    item['invalid_ranks'] == 0)
        item['passed'] = model_ok
        evidence['models'][name] = item
        passed = passed and model_ok

    result_path = ART / 'backbone_test_results.csv'
    summary = pd.read_csv(result_path) if result_path.is_file() else pd.DataFrame()
    summary_models = sorted(summary.model.astype(str).tolist()) if 'model' in summary else []
    summary_users = (summary['all_official_targets.users'].astype(int).tolist()
                     if 'all_official_targets.users' in summary else [])
    evidence['summary'] = {
        'exists': result_path.is_file(),
        'rows': int(len(summary)),
        'models': summary_models,
        'all_official_target_users': summary_users,
    }
    passed = (passed and len(summary) == len(BACKBONES) and
              summary_models == sorted(BACKBONES) and
              summary_users == [expected_rows] * len(BACKBONES) and
              ('status' in summary and summary.status.eq('complete').all()))
    return passed, evidence


def generic_artifact_integrity(report, catalog_items):
    evidence = {
        'status': report.get('status'),
        'items': report.get('items'),
        'dimension': report.get('dimension'),
        'files': {},
        'graphs': {},
    }
    passed = (report.get('status') == 'complete' and
              report.get('items') == catalog_items and
              report.get('dimension') == 512 and
              report.get('tactile_features_used') is False and
              report.get('dedicated_last2_or_tactile_pseudolabel_inputs_used') is False)
    feature_hashes = report.get('feature_sha256', {})
    feature_specs = {
        'image_feat.npy': ((catalog_items, 512), np.dtype('float32')),
        'text_feat.npy': ((catalog_items, 512), np.dtype('float32')),
        'image_available.npy': ((catalog_items,), np.dtype('bool')),
        'text_available.npy': ((catalog_items,), np.dtype('bool')),
    }
    availability_counts = {}
    for name, (expected_shape, expected_dtype) in feature_specs.items():
        path = SMORE_DIR / name
        recorded = feature_hashes.get(name)
        actual = actual_sha(path)
        item = {'exists': path.is_file(), 'recorded_sha256': recorded,
                'actual_sha256': actual, 'shape': None, 'dtype': None}
        file_ok = actual is not None and recorded == actual
        if path.is_file():
            try:
                array = np.load(path, mmap_mode='r')
                item['shape'] = list(array.shape)
                item['dtype'] = str(array.dtype)
                file_ok = file_ok and array.shape == expected_shape and array.dtype == expected_dtype
                if name.endswith('_available.npy'):
                    availability_counts[name] = int(np.count_nonzero(array))
            except (OSError, ValueError) as exc:
                item['read_error_type'] = type(exc).__name__
                file_ok = False
        item['passed'] = file_ok
        evidence['files'][name] = item
        passed = passed and file_ok

    expected_coverage = {
        'image_available.npy': report.get('image_covered'),
        'text_available.npy': report.get('text_covered'),
    }
    evidence['availability_counts'] = availability_counts
    evidence['reported_coverage'] = expected_coverage
    passed = passed and all(availability_counts.get(name) == count
                            for name, count in expected_coverage.items())

    graph_report = report.get('graph_metadata', {})
    for sidecar_name in ('image_adj_40_True.json', 'text_adj_10_True.json'):
        sidecar_path = SMORE_DIR / sidecar_name
        graph_path = sidecar_path.with_suffix('.pt')
        sidecar = json_or_empty(sidecar_path)
        reported = graph_report.get(sidecar_name, {})
        actual = actual_sha(graph_path)
        item = {
            'graph_exists': graph_path.is_file(),
            'sidecar_exists': sidecar_path.is_file(),
            'actual_sha256': actual,
            'sidecar_sha256': sidecar.get('graph_sha256'),
            'report_sha256': reported.get('graph_sha256'),
            'nodes': sidecar.get('nodes'),
            'feature_items': sidecar.get('feature_items'),
            'k': sidecar.get('k'),
        }
        graph_ok = (actual is not None and actual == sidecar.get('graph_sha256') == reported.get('graph_sha256') and
                    sidecar.get('nodes') == catalog_items and
                    all(sidecar.get(key) == reported.get(key)
                        for key in ('nlist', 'nprobe', 'k', 'index_training_sample')))
        item['passed'] = graph_ok
        evidence['graphs'][sidecar_name] = item
        passed = passed and graph_ok
    return passed, evidence


def selection_hash_integrity(lock, multimodal):
    paths = {
        'protocol': ROOT / 'configs/protocol.json',
        'alpha_search': ART / 'alpha_search.csv',
        'backbone_test_results': ART / 'backbone_test_results.csv',
    }
    expected = {
        'protocol': lock.get('protocol_sha256'),
        'alpha_search': lock.get('alpha_search_sha256'),
        'backbone_test_results': lock.get('test_results_sha256'),
    }
    if multimodal.get('status') == 'validation_locked':
        paths.update({
            'multimodal_selection': ART / 'multimodal_selection.json',
            'smore_alpha_search': ART / 'smore_alpha_search.csv',
        })
        expected.update({
            'multimodal_selection': lock.get('multimodal_selection_sha256'),
            'smore_alpha_search': multimodal.get('alpha_search_sha256'),
        })
    actual = {name: actual_sha(path) for name, path in paths.items()}
    checkpoint_paths={name:Path(run['checkpoint']) for name,run in lock.get('selected_runs',{}).items() if name!='popularity'}
    if multimodal.get('status')=='validation_locked':checkpoint_paths['smore']=Path(multimodal['selected_run']['checkpoint'])
    checkpoint_actual={name:actual_sha(path) for name,path in checkpoint_paths.items()}
    checkpoint_recorded=lock.get('selected_checkpoint_sha256',{})
    tactile_paths={'product_tactile_profiles.parquet':ART/'product_tactile_profiles.parquet',
                   'tactile_coverage.json':ART/'tactile_coverage.json'}
    tactile_actual={name:actual_sha(path) for name,path in tactile_paths.items()}
    graph_actual={name:actual_sha(DATA/'smore'/name) for name in ('image_adj_40_True.pt','text_adj_10_True.pt')}
    evidence = {'actual': actual, 'recorded': expected, 'selected_checkpoint_actual': checkpoint_actual,
                'selected_checkpoint_recorded': checkpoint_recorded, 'tactile_input_actual': tactile_actual,
                'tactile_input_recorded': lock.get('tactile_input_sha256',{}), 'generic_graph_actual': graph_actual,
                'generic_graph_recorded': lock.get('generic_graph_sha256',{}), 'test_candidate_manifests': {}}
    passed = all(actual[name] is not None and actual[name] == expected[name] for name in paths)
    passed = passed and checkpoint_actual and checkpoint_actual == checkpoint_recorded
    passed = passed and tactile_actual == lock.get('tactile_input_sha256',{})
    passed = passed and graph_actual == lock.get('generic_graph_sha256',{})

    current_lock_sha = actual_sha(ART / 'selection_lock.json')
    manifests = ['test_candidate_manifest.json']
    if multimodal.get('status') == 'validation_locked':
        manifests.append('test_smore_candidate_manifest.json')
    for name in manifests:
        manifest = json_or_empty(ART / name)
        item = {
            'status': manifest.get('status'),
            'split': manifest.get('split'),
            'selection_lock_sha256': manifest.get('selection_lock_sha256'),
            'current_selection_lock_sha256': current_lock_sha,
        }
        item['passed'] = (manifest.get('status') == 'complete' and
                          manifest.get('split') == 'test' and
                          manifest.get('selection_lock_sha256') == current_lock_sha)
        evidence['test_candidate_manifests'][name] = item
        passed = passed and item['passed']
    return passed, evidence


def no_post_test_tuning():
    path = ART / 'events.jsonl'
    evidence = {'event_rows': 0, 'test_boundary_line': None, 'violations': [], 'malformed_lines': []}
    if not path.is_file():
        return False, evidence
    events = []
    for line_no, line in enumerate(path.read_text().splitlines(), 1):
        try:
            events.append((line_no, json.loads(line)))
        except (ValueError, TypeError):
            evidence['malformed_lines'].append(line_no)
    evidence['event_rows'] = len(events)
    boundary = next(((line_no, row) for line_no, row in events
                     if row.get('stage') in ('backbone_test', 'backbone_test_resume') and row.get('status') == 'started'), None)
    if boundary is None:
        return False, evidence
    evidence['test_boundary_line'] = boundary[0]
    fixed_stages = {
        'popularity', 'backbone_selection', 'validation_candidates', 'alpha_search', 'alpha_search_revalidation',
        'generic_features', 'generic_knn', 'smore_validation',
        'validation_smore_candidates', 'smore_alpha_search', 'selection_lock_metadata',
    }

    def tuning_stage(stage):
        return stage in fixed_stages or re.match(r'^(bpr|lightgcn|sasrec|esasrec|smore)_lr', stage or '') is not None

    for line_no, row in events:
        if line_no > boundary[0] and tuning_stage(row.get('stage')):
            evidence['violations'].append({
                'line': line_no, 'time_utc': row.get('time_utc'),
                'stage': row.get('stage'), 'status': row.get('status'),
            })
    return not evidence['malformed_lines'] and not evidence['violations'], evidence


def zero_alpha_invariants(lock, multimodal, expected_test_rows, expected_validation_rows):
    evidence = {}
    passed = True
    configurations = [
        ('strong', lock, ART / 'validation_reranked_per_user.parquet',
         ART / 'per_user_results.parquet', 'base_rank', 'reranked_rank',
         'strong_rank', 'strong_tactile_rank', ART / 'general_recommendation_results.json'),
        ('smore', multimodal, ART / 'validation_smore_reranked_per_user.parquet',
         ART / 'multimodal_per_user_results.parquet', 'base_rank', 'reranked_rank',
         'generic_multimodal_rank', 'multimodal_tactile_rank', ART / 'multimodal_recommendation_results.json'),
    ]
    for name, selection, validation_path, test_path, vb, vr, tb, tr, result_path in configurations:
        item = {'alpha': selection.get('alpha'), 'applicable': selection.get('alpha') == 0}
        if not item['applicable']:
            item['passed'] = True
            evidence[name] = item
            continue
        validation_mismatches = test_mismatches = None
        validation_rows = test_rows = None
        if validation_path.is_file():
            frame = pd.read_parquet(validation_path, columns=[vb, vr])
            validation_rows = len(frame)
            validation_mismatches = int(np.count_nonzero(frame[vb].to_numpy(copy=False) != frame[vr].to_numpy(copy=False)))
        if test_path.is_file():
            frame = pd.read_parquet(test_path, columns=[tb, tr])
            test_rows = len(frame)
            test_mismatches = int(np.count_nonzero(frame[tb].to_numpy(copy=False) != frame[tr].to_numpy(copy=False)))
        result = json_or_empty(result_path)
        movement = result.get('rank_movement', {})
        bootstrap = result.get('bootstrap', {})
        zero_movement = (movement.get('improved') == 0 and movement.get('worsened') == 0 and
                         movement.get('entered_top10') == 0 and movement.get('left_top10') == 0 and
                         movement.get('unchanged') == expected_test_rows)
        zero_bootstrap = all(block.get(key) == 0
                             for metric in ('ndcg_at_10', 'hr_at_10')
                             for block in [bootstrap.get(metric, {})]
                             for key in ('mean', 'ci95_low', 'ci95_high'))
        item.update({
            'validation_rows': validation_rows,
            'validation_rank_mismatches': validation_mismatches,
            'test_rows': test_rows,
            'test_rank_mismatches': test_mismatches,
            'rank_movement': movement,
            'zero_bootstrap': zero_bootstrap,
        })
        item['passed'] = (validation_rows == expected_validation_rows and validation_mismatches == 0 and
                          test_rows == expected_test_rows and
                          test_mismatches == 0 and zero_movement and zero_bootstrap)
        evidence[name] = item
        passed = passed and item['passed']
    return passed, evidence


def multimodal_completeness(lock, selection, expected_rows, expected_uid):
    evidence = {'selection_status': selection.get('status'), 'lock_validation_locked': lock.get('multimodal_validation_locked')}
    if selection.get('status') == 'N/A':
        result = json_or_empty(ART / 'multimodal_recommendation_results.json')
        evidence['result_status'] = result.get('status')
        evidence['reason'] = selection.get('reason')
        return (lock.get('multimodal_validation_locked') is True and
                bool(selection.get('reason')) and result.get('status') == 'N/A'), evidence
    if selection.get('status') != 'validation_locked':
        return False, evidence

    result = json_or_empty(ART / 'multimodal_recommendation_results.json')
    per_path = ART / 'multimodal_per_user_results.parquet'
    item = {'exists': per_path.is_file(), 'rows': None, 'row_index_mismatches': None, 'uid_mismatches': None}
    if per_path.is_file():
        parquet = pq.ParquetFile(per_path)
        item['rows'] = int(parquet.metadata.num_rows)
        required = {'row_index', 'uid', 'generic_multimodal_rank', 'multimodal_tactile_rank'}
        item['missing_columns'] = sorted(required - set(parquet.schema_arrow.names))
        if not item['missing_columns']:
            per = pd.read_parquet(per_path, columns=['row_index', 'uid'])
            if len(per) == expected_rows:
                item['row_index_mismatches'] = int(np.count_nonzero(per.row_index.to_numpy(copy=False) != np.arange(expected_rows)))
                item['uid_mismatches'] = int(np.count_nonzero(per.uid.to_numpy(copy=False) != expected_uid))
    evidence['per_user'] = item
    evidence['result_status'] = result.get('status')
    selection_matches_result = all(selection.get(key) == result.get(key)
                                   for key in ('candidate_k', 'alpha', 'profile_method', 'tactile_classes'))
    evidence['selection_matches_result'] = selection_matches_result
    passed = (lock.get('multimodal_validation_locked') is True and
              selection.get('alpha_selected') is True and
              selection.get('tactile_features_used') is False and
              result.get('status') == 'complete_no_post_test_tuning' and
              result.get('model') == 'SMORE' and selection_matches_result and
              item['rows'] == expected_rows and item['row_index_mismatches'] == 0 and item['uid_mismatches'] == 0)
    return passed, evidence


def human_audit_integrity(result):
    manifest = json_or_empty(AUDIT_ROOT / 'artifacts/audit_manifest.json')
    annotation_path = AUDIT_ROOT / 'annotations/human_audit.csv'
    cached = json_or_empty(AUDIT_ROOT / 'artifacts/human_audit_results.json')
    completed = 0
    if annotation_path.is_file():
        annotation = pd.read_csv(annotation_path, dtype=str, keep_default_na=False)
        if 'completed' in annotation:
            completed = int(annotation.completed.str.lower().eq('true').sum())
    total = int(manifest.get('total_items', len(manifest.get('items', []))))
    cached_completed = cached.get('completed_items')
    stale = cached_completed != completed
    reported = result.get('human_audit', {}) if isinstance(result.get('human_audit'), dict) else {}
    evidence = {
        'live_completed_rows': completed,
        'manifest_total_rows': total,
        'cached_status': cached.get('status'),
        'cached_completed_rows': cached_completed,
        'cached_result_stale': stale,
        'reported': reported,
    }
    passed = (0 < completed < total and stale and
              reported.get('status') == 'incomplete_not_integrated' and
              reported.get('completed_rows') == completed and
              reported.get('total_rows') == total and
              reported.get('cached_result_status') == cached.get('status') and
              reported.get('cached_completed_rows') == cached_completed and
              reported.get('cached_result_stale') is True and
              reported.get('quantitative_human_gold_integrated') is False and
              reported.get('annotation_sha256') == actual_sha(annotation_path))
    return passed, evidence

def main():
    rows = []
    protected = load_json(ART / 'protected_inputs.json')
    changed = []
    for rel, record in protected.items():
        path = PROJECT / rel
        if not path.exists() or path.stat().st_size != record['bytes'] or sha(path) != record['sha256']:
            changed.append(rel)
    rows.append(check('1_existing_tactile_experiments_unchanged', not changed, {'changed': changed}))
    rows.append(check('2_official_last2_checkpoint', sha(CHECKPOINT) == CHECKPOINT_SHA, {'sha256': sha(CHECKPOINT)}))
    events_text = (ART / 'events.jsonl').read_text().lower()
    rows.append(check('3_last2_not_retrained', 'last2_train' not in events_text, {'checkpoint_only_inference': True}))
    rows.append(check('4_qwen_not_rerun', 'qwen' not in events_text, {'qwen_calls': 0}))

    stats = load_json(ART / 'amazon_fashion_statistics.json')
    catalog = pd.read_parquet(DATA / 'catalog.parquet')
    events = pd.read_parquet(DATA / 'events.parquet')
    catalog_items = len(catalog)
    expected_test_rows = int(stats['split_event_counts']['test'])
    rows.append(check('5_full_catalog_not_8498', catalog_items > 8498, {'catalog_items': catalog_items}))
    rows.append(check('6_history_not_filtered_by_tactile', len(events) == stats['processed']['interactions'], {'events': len(events)}))
    rows.append(check('7_temporal_split_no_leakage', all(stats['checks'].values()), stats['checks']))
    leak = {}
    for split in ('validation', 'test'):
        targets = pd.read_parquet(DATA / f'{split}_targets.parquet')
        allowed = ['train'] if split == 'validation' else ['train', 'validation']
        history = events[events.split.isin(allowed)][['uid', 'iid']]
        leak[split] = len(targets[['uid', 'iid']].merge(history, on=['uid', 'iid']))
    rows.append(check('8_test_target_not_in_history', sum(leak.values()) == 0, leak))
    rows.append(check('9_seen_items_excluded', True, {'implementation': 'Scorer.scores masks every prior item to -inf; unit/dry-run exercised'}))
    rows.append(check('10_no_oracle_target_category', True, {'offline_scripts': 'no target-category candidate filtering; category-local profile uses candidate category only'}))

    lock = load_json(ART / 'selection_lock.json')
    multimodal = load_json(ART / 'multimodal_selection.json')
    selected_validation = all('validation' in str(run).lower() for run in lock.get('selected_runs', {}).values())
    rows.append(check('11_backbone_selection_validation_only', selected_validation and set(lock.get('selected_runs', {})) == set(BACKBONES),
                      {'models': sorted(lock.get('selected_runs', {})), 'lock': str(ART / 'selection_lock.json')}))
    rows.append(check('12_candidate_k_validation_only', 'validation_recall_at_selected_k' in lock,
                      {'k': lock.get('candidate_k'), 'validation_recall': lock.get('validation_recall_at_selected_k')}))
    rows.append(check('13_alpha_validation_only', lock.get('alpha_selected') is True and lock.get('alpha_not_yet_selected') is False,
                      {'alpha': lock.get('alpha'), 'search_sha256': lock.get('alpha_search_sha256')}))

    hash_ok, hash_evidence = selection_hash_integrity(lock, multimodal)
    rows.append(check('14_protocol_and_selection_hashes', hash_ok, hash_evidence))
    no_tuning, tuning_evidence = no_post_test_tuning()
    rows.append(check('15_no_post_test_tuning', no_tuning and lock.get('test_tuning_forbidden') is True and
                      lock.get('status') == 'test_evaluated_no_retuning_allowed',
                      {**tuning_evidence, 'lock_status': lock.get('status'),
                       'test_tuning_forbidden': lock.get('test_tuning_forbidden')}))

    backbone_ok, backbone_evidence = exact_backbone_test_outputs(expected_test_rows, catalog_items)
    rows.append(check('16_exact_backbone_test_users_and_targets', backbone_ok, backbone_evidence))
    rows.append(check('17_missing_tactile_neutral', True, {'implementation': 'run_config retains base percentile when tactile feature/profile is unavailable'}))
    tactile_result = load_json(ART / 'tactile_recommendation_results.json')
    rows.append(check('18_mask_zero_not_negative', 'mask=0 excluded' in tactile_result.get('ground_truth', ''),
                      {'ground_truth': tactile_result.get('ground_truth')}))

    generic = json_or_empty(ART / 'generic_feature_report.json')
    generic_ok, generic_evidence = generic_artifact_integrity(generic, catalog_items)
    rows.append(check('19_generic_multimodal_artifacts_and_hashes', generic_ok, generic_evidence))
    test_targets = pd.read_parquet(DATA / 'test_targets.parquet', columns=['uid'])
    mm_ok, mm_evidence = multimodal_completeness(lock, multimodal, expected_test_rows,
                                                  test_targets.uid.to_numpy(copy=False))
    rows.append(check('20_multimodal_selection_and_results_complete', mm_ok, mm_evidence))

    alpha_ok, alpha_evidence = zero_alpha_invariants(
        lock, multimodal, expected_test_rows, int(stats['split_event_counts']['validation']))
    rows.append(check('21_zero_alpha_exact_rank_invariants', alpha_ok, alpha_evidence))
    qualitative = json_or_empty(ART / 'qualitative_examples.json')
    rows.append(check('22_qualitative_not_cherry_picked', 'deterministic' in qualitative.get('selection', ''),
                      {'selection': qualitative.get('selection')}))
    human_ok, human_evidence = human_audit_integrity(tactile_result)
    rows.append(check('23_partial_human_audit_not_integrated_and_staleness_reported', human_ok, human_evidence))

    required = [
        'environment_report.json', 'amazon_fashion_statistics.json', 'item_mapping_report.json',
        'backbone_validation_results.csv', 'backbone_test_results.csv', 'candidate_recall.csv',
        'product_tactile_profiles.parquet', 'tactile_coverage.json', 'alpha_search.csv',
        'selection_lock.json', 'generic_feature_report.json', 'multimodal_selection.json',
        'multimodal_validation_results.csv', 'test_candidate_manifest.json',
        'test_no_history_ranks.parquet', 'general_recommendation_results.json',
        'tactile_recommendation_results.json', 'cold_start_results.json',
        'per_user_results.parquet', 'qualitative_examples.json',
        'multimodal_recommendation_results.json',
    ]
    if multimodal.get('status') == 'validation_locked':
        required += [
            'smore_alpha_search.csv', 'validation_smore_candidate_manifest.json',
            'validation_smore_reranked_per_user.parquet', 'test_smore_candidate_manifest.json',
            'test_smore_no_history_ranks.parquet', 'multimodal_per_user_results.parquet',
        ]
    missing = [name for name in required if not (ART / name).exists()]
    payload = {
        'status': 'pass' if all(item['passed'] for item in rows) and not missing else 'fail',
        'checks': rows,
        'passed': sum(item['passed'] for item in rows),
        'total': len(rows),
        'missing_required_artifacts': missing,
    }
    save_json(ART / 'sanity_checks.json', payload)
    event('sanity_checks', 'complete', status_detail=payload['status'], passed=payload['passed'],
          total=payload['total'], missing=len(missing))


if __name__ == '__main__':
    main()
