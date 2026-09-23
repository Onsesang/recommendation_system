# 촉감 선호 — AI 예비 audit

**AI 검토 64/64 완료. 사람 검증은 대기 중이다. 이 결과를 human gold label이나 정확도로 사용하지 않는다.**

## 방법과 독립성

Codex read contexts and made these decisions before opening item-level Qwen annotations in this audit turn. Prior conversation included aggregate counts and two schema-rejection sample IDs. This is not a preregistered blinded human audit.

Codex가 각 focal occurrence의 원문 문맥을 읽고 property/class/state/attitude/scope/condition과 한국어 근거를 작성했다. Qwen의 개별 답안을 읽기 전에 decisions.json과 ai_annotations.jsonl의 SHA-256을 잠갔다. 이후 두 AI 결과를 비교했다. 원문 인용은 단순 substring뿐 아니라 실제 선택된 focal occurrence의 위치까지 포함하는지 검증했다.

Audit holdout에 대한 AI 검토도 열람되었으므로 이 표본으로 후속 prompt를 개선한다면 이를 미사용 개발 holdout이라고 주장할 수 없다. 사람이 AI 결과를 보지 않고 판정하는 독립 검토는 계속 가능하다. 최종 확증 평가가 필요하면 새로운 표본을 따로 확보한다.

## 비교 결과 — 정확도가 아닌 AI 간 일치

| 묶음 | 비교 가능 Qwen | class 일치 | state 일치 | attitude 일치 | 세 항목 모두 일치 |
|---|---:|---:|---:|---:|---:|
| all | 62 | 50/62 | 48/62 | 33/62 | 23/62 |
| development | 32 | 26/32 | 25/32 | 16/32 | 13/32 |
| audit_holdout | 30 | 24/30 | 23/30 | 17/30 | 10/30 |

AI attitude: {"dislike": 7, "like": 20, "unknown": 36, "mixed": 1}
AI property state: {"present": 47, "absent": 2, "uncertain": 6, "not_tactile": 9}

## 반복되는 검토 쟁점

- crisp: 직물 외에도 날씨, 흰색, 무늬 선명도를 가리킨다.
- stretching/floppy/rough: 귀 당김, 단추 부착 불량, 지퍼 작동을 소재 속성으로 오인하기 쉽다.
- thin elastic band: 밴드의 폭과 소재 두께를 구별할 근거가 부족할 수 있다.
- nice/comfortable/general love: 국소적인 속성 평가인지 전반적 상품 칭찬인지 경계가 불명확하다. AI의 엄격한 해석 역시 사람 검증 대상이다.
- not too thick, less flexible, hypothetical softer: 강도 부정·비교·가정을 속성 부재로 단순화하면 안 된다.
- 타인의 착용 경험과 날씨·활동 조건: reviewer의 영구적인 전역 선호로 자동 전환하지 않는다.

## 사람 audit을 위한 사용법

기존 app.py는 이 폴더를 읽지 않으므로 모델 답안 없이 원문을 보고 판정할 수 있다. human_annotation_template.csv와 annotations/는 변경하지 않았다. 처음에는 AI 비교표를 보지 않고 64개를 모두 독립 판정한 뒤, 판정을 고정하고 불일치 사례를 검토하는 순서를 권한다. 불일치 항목만 검사하면 두 모델이 함께 틀린 사례를 놓친다.

사람 판정이 도착하기 전까지 AI 라벨로 학습하거나 추천 weight를 바꾸지 않았다. 반복 오류를 개선하기 위한 가설을 만들 수 있지만, 성능 향상이나 추출 정확도가 검증된 것은 아니다.

## 파일

- decisions.json: Codex가 직접 작성한 64개 판정 및 근거
- ai_annotations.jsonl: sample ID, 원문 evidence offset, reviewer_type=AI 포함
- locked_manifest.json: Qwen 비교 전 판정 hash와 보존 대상 입력 hash
- qwen_comparison.csv: 전체 표본의 AI 비교
- disagreement_candidates.csv: 세 핵심 필드 중 하나라도 다른 비교 가능 표본
- ai_audit_results.json: 집계 및 한계

재현: `python ai_audit/run_ai_audit.py materialize` 다음 `python ai_audit/run_ai_audit.py compare`. 기존 판정 lock 이후 입력 판정 변경은 허용하지 않으며, 변경이 필요하면 새 버전으로 수행한다.
