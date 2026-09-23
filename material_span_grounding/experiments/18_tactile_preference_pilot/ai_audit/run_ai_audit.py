"""Materialize Codex's case-by-case decisions, lock them, then compare to Qwen.

Writes exclusively under ai_audit/. Never imports these decisions into human annotations.
"""
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
PILOT = ROOT.parent
ART = PILOT / 'artifacts'
FIELDS = ['class_id', 'property_state', 'attitude']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def protected_hashes():
    paths = list(ART.glob('*')) + [PILOT/'app.py', PILOT/'pilot.py', PILOT/'human_audit.py']
    if (PILOT/'annotations').exists(): paths += list((PILOT/'annotations').glob('*'))
    return {str(p.relative_to(PILOT)): digest(p) for p in paths if p.is_file()}


def materialize():
    lock = ROOT/'locked_manifest.json'
    if lock.exists():
        prior = json.loads(lock.read_text())
        assert digest(ROOT/'decisions.json') == prior['decisions_sha256'], 'Decisions changed after lock; create a new version instead'
        assert digest(ROOT/'ai_annotations.jsonl') == prior['ai_annotations_sha256']
        print('Existing AI decisions remain locked')
        return
    samples = pd.read_parquet(ART/'pilot_samples.parquet').reset_index(drop=True)
    decisions = json.loads((ROOT/'decisions.json').read_text())
    assert sorted(d[0] for d in decisions) == list(range(len(samples)))
    records = []
    for index, class_id, state, attitude, scope, condition, quote, rationale, flags in decisions:
        row = samples.iloc[index].to_dict()
        assert class_id in ['soft','firm','smooth','rough','non_elastic','elastic','thin','thick','flexible','stiff','warm','cool','spongy','crisp','unmapped']
        assert state in ['present','absent','uncertain','not_tactile']
        assert attitude in ['like','dislike','unknown','mixed']
        focal = int(row['focal_start'])-int(row['context_start'])
        starts = [k for k in range(len(row['context'])) if row['context'].startswith(quote,k)]
        anchors = [k for k in starts if k <= focal and focal+len(row['focal_phrase']) <= k+len(quote)]
        assert anchors, f'Quote must cover exact selected occurrence: index={index}, sample={row["sample_id"]}, focal_offset={focal}'
        annotation = {'property_phrase':row['focal_phrase'],'class_id':class_id,'property_state':state,
                      'attitude':attitude,'scope':scope,'condition':condition,'evidence_quote':quote}
        records.append({'sample_id':row['sample_id'],'sample_index':index,'split_role':row['split_role'],
                        'reviewer_id':'codex_ai_preliminary_20260906','reviewer_type':'AI',
                        'human_verified':False,'annotation':annotation,'rationale_ko':rationale,
                        'uncertainty_flags':flags,'evidence_start_in_review':int(row['context_start'])+anchors[0],
                        'evidence_end_in_review':int(row['context_start'])+anchors[0]+len(quote),
                        'focal_start_in_review':int(row['focal_start']),
                        'human_review_priority':'high' if any(f in flags for f in ['non_tactile','dimension_ambiguity','body_smoothing_ambiguity','hypothetical','degree_negation','weak_attribution','comparative','third_party']) else 'normal'})
    protected = protected_hashes()
    with (ROOT/'ai_annotations.jsonl').open('x') as f:
        for record in records: f.write(json.dumps(record,ensure_ascii=False)+'\n')
    manifest = {'status':'AI_decisions_locked_before_item_level_Qwen_comparison',
                'created_at_utc':datetime.now(timezone.utc).isoformat(), 'reviewer_type':'AI',
                'human_audit_status':'pending_not_performed_by_this_process',
                'blindness_limit':'Codex read contexts and made these decisions before opening item-level Qwen annotations in this audit turn. Prior conversation included aggregate counts and two schema-rejection sample IDs. This is not a preregistered blinded human audit.',
                'decisions_sha256':digest(ROOT/'decisions.json'),'ai_annotations_sha256':digest(ROOT/'ai_annotations.jsonl'),
                'sample_source_sha256':digest(ART/'pilot_samples.parquet'), 'protected_hashes_before':protected,
                'n':len(records), 'prompt_or_ranking_changes':False}
    write_json(lock,manifest)
    print(f'Locked {len(records)} AI annotations. No human annotation written.')


def compare():
    lock=json.loads((ROOT/'locked_manifest.json').read_text())
    assert digest(ROOT/'decisions.json')==lock['decisions_sha256']
    assert digest(ROOT/'ai_annotations.jsonl')==lock['ai_annotations_sha256']
    assert protected_hashes()==lock['protected_hashes_before'], 'Protected inputs changed'
    ai=[json.loads(s) for s in (ROOT/'ai_annotations.jsonl').read_text().splitlines()]
    qwen={r['sample_id']:r for r in [json.loads(s) for s in (ART/'model_annotations.jsonl').read_text().splitlines()]}
    samples=pd.read_parquet(ART/'pilot_samples.parquet').set_index('sample_id')
    rows=[]
    for a in ai:
        q=qwen[a['sample_id']];qa=q.get('annotation');s=samples.loc[a['sample_id']]
        row={'sample_id':a['sample_id'],'sample_index':a['sample_index'],'split_role':a['split_role'],
             'focal_phrase':s.focal_phrase,'context':s.context,'qwen_valid':qa is not None,
             'qwen_validation_error':q.get('validation_error'),'ai_rationale_ko':a['rationale_ko'],
             'ai_flags':';'.join(a['uncertainty_flags']),'human_verified':False}
        for field in FIELDS:
            row[f'ai_{field}']=a['annotation'][field];row[f'qwen_{field}']=qa[field] if qa else None
            row[f'{field}_agrees']=a['annotation'][field]==qa[field] if qa else None
        row['all_three_agree']=all(row[f'{field}_agrees'] for field in FIELDS) if qa else None
        rows.append(row)
    frame=pd.DataFrame(rows)
    frame.to_csv(ROOT/'qwen_comparison.csv',index=False)
    frame[frame.qwen_valid & ~frame.all_three_agree.fillna(False).astype(bool)].to_csv(ROOT/'disagreement_candidates.csv',index=False)
    groups={}
    for role in ['all','development','audit_holdout']:
        f=frame if role=='all' else frame[frame.split_role==role]
        v=f[f.qwen_valid]
        groups[role]={'total':len(f),'valid_qwen':len(v),'qwen_rejected':int((~f.qwen_valid).sum()),
            'agreement':{field:{'same':int(v[f'{field}_agrees'].sum()),'support':len(v),'rate':float(v[f'{field}_agrees'].mean()) if len(v) else None} for field in FIELDS},
            'all_three_same':int(v.all_three_agree.sum()),
            'cross_tabs':{field:pd.crosstab(v[f'ai_{field}'],v[f'qwen_{field}']).to_dict() for field in FIELDS}}
    result={'status':'AI_preliminary_audit_complete_human_audit_still_pending',
            'n':len(ai),'reviewer_type':'AI','human_verified':False,'human_accuracy':None,
            'interpretation':'Agreement of two AI annotations, NOT ground-truth accuracy or human agreement. Both can be wrong.',
            'blindness_limit':lock['blindness_limit'],
            'ai_attitudes':dict(Counter(a['annotation']['attitude'] for a in ai)),
            'ai_property_states':dict(Counter(a['annotation']['property_state'] for a in ai)),
            'ai_flags':dict(Counter(f for a in ai for f in a['uncertainty_flags'])), 'comparison':groups,
            'protected_inputs_unchanged':protected_hashes()==lock['protected_hashes_before']}
    write_json(ROOT/'ai_audit_results.json',result)
    lines=['# 촉감 선호 — AI 예비 audit', '',
      '**AI 검토 64/64 완료. 사람 검증은 대기 중이다. 이 결과를 human gold label이나 정확도로 사용하지 않는다.**', '',
      '## 방법과 독립성', '', result['blindness_limit'], '',
      'Codex가 각 focal occurrence의 원문 문맥을 읽고 property/class/state/attitude/scope/condition과 한국어 근거를 작성했다. Qwen의 개별 답안을 읽기 전에 decisions.json과 ai_annotations.jsonl의 SHA-256을 잠갔다. 이후 두 AI 결과를 비교했다. 원문 인용은 단순 substring뿐 아니라 실제 선택된 focal occurrence의 위치까지 포함하는지 검증했다.', '',
      'Audit holdout에 대한 AI 검토도 열람되었으므로 이 표본으로 후속 prompt를 개선한다면 이를 미사용 개발 holdout이라고 주장할 수 없다. 사람이 AI 결과를 보지 않고 판정하는 독립 검토는 계속 가능하다. 최종 확증 평가가 필요하면 새로운 표본을 따로 확보한다.', '',
      '## 비교 결과 — 정확도가 아닌 AI 간 일치', '',
      '| 묶음 | 비교 가능 Qwen | class 일치 | state 일치 | attitude 일치 | 세 항목 모두 일치 |',
      '|---|---:|---:|---:|---:|---:|']
    for name,g in groups.items():
        cells=[f"{g['agreement'][field]['same']}/{g['valid_qwen']}" for field in FIELDS]
        lines.append(f"| {name} | {g['valid_qwen']} | {' | '.join(cells)} | {g['all_three_same']}/{g['valid_qwen']} |")
    lines += ['',f"AI attitude: {json.dumps(result['ai_attitudes'],ensure_ascii=False)}",f"AI property state: {json.dumps(result['ai_property_states'],ensure_ascii=False)}",'',
      '## 반복되는 검토 쟁점', '',
      '- crisp: 직물 외에도 날씨, 흰색, 무늬 선명도를 가리킨다.',
      '- stretching/floppy/rough: 귀 당김, 단추 부착 불량, 지퍼 작동을 소재 속성으로 오인하기 쉽다.',
      '- thin elastic band: 밴드의 폭과 소재 두께를 구별할 근거가 부족할 수 있다.',
      '- nice/comfortable/general love: 국소적인 속성 평가인지 전반적 상품 칭찬인지 경계가 불명확하다. AI의 엄격한 해석 역시 사람 검증 대상이다.',
      '- not too thick, less flexible, hypothetical softer: 강도 부정·비교·가정을 속성 부재로 단순화하면 안 된다.',
      '- 타인의 착용 경험과 날씨·활동 조건: reviewer의 영구적인 전역 선호로 자동 전환하지 않는다.', '',
      '## 사람 audit을 위한 사용법', '',
      '기존 app.py는 이 폴더를 읽지 않으므로 모델 답안 없이 원문을 보고 판정할 수 있다. human_annotation_template.csv와 annotations/는 변경하지 않았다. 처음에는 AI 비교표를 보지 않고 64개를 모두 독립 판정한 뒤, 판정을 고정하고 불일치 사례를 검토하는 순서를 권한다. 불일치 항목만 검사하면 두 모델이 함께 틀린 사례를 놓친다.', '',
      '사람 판정이 도착하기 전까지 AI 라벨로 학습하거나 추천 weight를 바꾸지 않았다. 반복 오류를 개선하기 위한 가설을 만들 수 있지만, 성능 향상이나 추출 정확도가 검증된 것은 아니다.', '',
      '## 파일', '',
      '- decisions.json: Codex가 직접 작성한 64개 판정 및 근거',
      '- ai_annotations.jsonl: sample ID, 원문 evidence offset, reviewer_type=AI 포함',
      '- locked_manifest.json: Qwen 비교 전 판정 hash와 보존 대상 입력 hash',
      '- qwen_comparison.csv: 전체 표본의 AI 비교',
      '- disagreement_candidates.csv: 세 핵심 필드 중 하나라도 다른 비교 가능 표본',
      '- ai_audit_results.json: 집계 및 한계', '',
      '재현: `python ai_audit/run_ai_audit.py materialize` 다음 `python ai_audit/run_ai_audit.py compare`. 기존 판정 lock 이후 입력 판정 변경은 허용하지 않으며, 변경이 필요하면 새 버전으로 수행한다.']
    (ROOT/'AI_PRELIMINARY_AUDIT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:result[k] for k in ['status','ai_attitudes','ai_property_states','comparison','protected_inputs_unchanged']},ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['materialize','compare']);args=parser.parse_args()
    globals()[args.stage]()
