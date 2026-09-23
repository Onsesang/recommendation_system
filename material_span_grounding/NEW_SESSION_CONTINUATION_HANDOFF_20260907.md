# New-session continuation handoff (2026-09-07)

이 문서는 긴 Codex 대화를 종료하고 새 대화에서 실험을 정확히 이어가기 위한 상태 고정 문서다. 아래의 `새 세션 시작 프롬프트`를 새 대화 첫 메시지로 붙여 넣고, 이 파일을 함께 언급하면 된다.

## 새 세션 시작 프롬프트

```text
/home/user/onsesang/material_span_grounding/NEW_SESSION_CONTINUATION_HANDOFF_20260907.md 를 먼저 처음부터 끝까지 읽고, 그 문서에 기록된 실제 파일 상태를 다시 검증한 뒤 미완료된 experiments/16_strong_recommender_tactile 실험을 중단 지점부터 끝까지 이어서 수행해줘.

완료된 Experiment 17~19와 이미 완료된 backbone 학습은 다시 실행하지 말고, 기존 산출물을 보존해. 현재 미완료 지점은 Amazon Fashion 전체 catalog의 Last2/generic FashionCLIP feature chunk 추출 후반부다. 세 개 shard로 resume하고, 모두 정상 종료한 뒤 finalize-only 및 나머지 validation/test/보고 단계를 프로토콜 순서대로 수행해. 각 단계의 상태와 산출물을 검증하고 실패하면 원인을 진단해 안전하게 resume해.

단계 완료·재시도·최종 완료를 Discord로 알려줘. Webhook URL은 비밀이므로 저장 파일이나 로그에 쓰지 말고, 이 새 세션에서 내가 다시 제공하거나 DISCORD_WEBHOOK_URL 환경변수로 전달할게. 최종 Notion용 Markdown과 핵심 결과/한계까지 생성해줘.
```

## 1. 현재 사용자의 목표

Amazon Reviews 2023 `Amazon_Fashion` 전체 catalog에서 강한 추천 backbone과 generic multimodal baseline을 구축하고, 기존 `fashionclip_last2.pt`의 14차원 tactile probability를 추가했을 때 일반 next-item 추천과 명시적 tactile query 성능이 어떻게 달라지는지 끝까지 평가한다.

핵심 원칙:

- raw dataset, 기존 v3 split/checkpoint/prediction을 수정하지 않는다.
- Last2를 재학습하거나 Qwen grounding을 다시 실행하지 않는다.
- backbone, candidate K, tactile alpha/profile/class ablation은 validation에서만 선택하고 test는 한 번만 연다.
- 전체 catalog에 이미지가 없는 상품도 추천 후보에서 제거하지 않는다. tactile feature가 없으면 adjustment를 neutral로 둔다.
- human audit은 현재 생략 상태를 유지하고, AI 검토를 human gold로 표현하지 않는다.
- 최종 결과는 Notion-ready Markdown과 machine-readable artifact로 모두 남긴다.

## 2. 중요한 경로

- Project root: `/home/user/onsesang/material_span_grounding`
- 현재 미완료 실험: `experiments/16_strong_recommender_tactile`
- 실행 Python: `/home/user/onsesang/miniconda3/envs/texture/bin/python`
- Project rules: `AGENTS.md`
- 기존 공식 Last2 checkpoint: `experiments/12_class_multilabel_fashionclip_ft/models/fashionclip_last2.pt`
- 전체 재현 순서: `experiments/16_strong_recommender_tactile/reproduce.sh`
- 최종 예정 보고서: `experiments/16_strong_recommender_tactile/notion/STRONG_RECOMMENDER_TACTILE_RESULTS.md`

`reproduce.sh`는 전체 순서를 확인하는 기준으로 사용하되, 처음부터 무작정 다시 실행하지 않는다. 완료된 대규모 backbone 학습을 재수행할 필요가 없다.

## 3. 2026-09-07 19:21 KST 실제 실행 상태

- 실행 중인 Experiment 16 프로세스: **없음**
- GPU: NVIDIA A100 80GB PCIe, 점검 시 14 MiB 사용 / 81,142 MiB free / utilization 0%
- Filesystem: 약 745 GiB free
- 이전 PTY 세션은 종료되어 더 이상 attach할 수 없다.
- 산출물은 보존되어 있어 처음부터 다시 추출할 필요는 없다.

### 전체 이미지/feature expansion 상태

`item_metadata.parquet` 기준:

- 전체 recommendation catalog: 825,869 item
- Main image URL eligible: 825,868 item
- 예상 chunk: 826개
- 현재 profile parquet: 807개
- 현재 generic feature NPZ: 807개
- 현재 download-status parquet: 807개
- 완전히 미생성된 chunk: 19개
- 진행률(파일 기준): 807 / 826 = **97.70%**
- 손상된 parquet/download 파일: 점검 결과 0개

완전히 미생성된 chunk index는 다음과 같다.

```text
802, 805, 808, 809, 811, 812, 813, 814, 815, 816,
817, 818, 819, 820, 821, 822, 823, 824, 825
```

기존 807개 중 23개 profile은 1~6개의 이미지 다운로드 실패 때문에 URL eligible row 수보다 작다. 이는 corruption이 아니다. Resume 실행은 이 23개를 한 번 더 시도하고, 영구 실패가 남아도 모든 item의 download-status coverage가 존재하면 `--finalize-only`가 정상적으로 성공하도록 구현되어 있다.

### “전체 이미지/Last2 추출이 이미 됐다”는 말의 구분

기존 v3 실험의 8,498개 tactile 학습/평가 상품에 대한 Last2 prediction은 이미 완료되어 있다. 지금 미완료인 것은 새 강한 추천 실험을 위해 **Amazon Fashion 825,868개 URL-eligible 전체 catalog**로 inference와 generic FashionCLIP feature를 확장하는 단계다. 둘은 서로 다른 범위이며 기존 8,498개 결과를 다시 학습하는 작업이 아니다.

## 4. Experiment 16에서 이미 완료된 단계

- 환경 및 입력 hash 점검
- Amazon Fashion 전체 raw review 처리와 official leave-last-out split
- item metadata와 child ASIN → parent ASIN mapping
- 1,000-image pilot
- Popularity, BPR, LightGCN, SASRec, eSASRec validation training
- validation-only strong backbone 선택
- strong validation candidate 생성
- explicit tactile-query exploratory evaluation
- 코드 unit test 9개 통과

고정된 validation 결과:

- 선택 strong backbone: `sasrec`
- SASRec validation NDCG@10: `0.004692826694992827`
- 선택 candidate K: `3000`
- validation Recall@3000: `0.10915261465200163`
- 사전 규칙 Recall >= 0.80: 미충족
- test tuning forbidden: `true`
- selection lock 상태: `locked_before_any_new_test_evaluation`

다른 validation NDCG@10:

| Backbone | NDCG@10 |
|---|---:|
| Popularity | 0.0045831732 |
| BPR | 0.0042348294 |
| LightGCN | 0.0045305348 |
| SASRec | 0.0046928267 |
| eSASRec | 0.0046335099 |

이 수치는 전체 281,395 validation target에 대한 값이고 대규모 zero-history cohort를 포함한다. 절대값이 낮으며 retrieval bottleneck이 해소됐다고 주장하면 안 된다.

이미 완료된 별도 explicit tactile-query 결과:

| Method | Mean NDCG@10 | Mean Precision@10 |
|---|---:|---:|
| Non-tactile popularity | 0.475245 | 0.56875 |
| Last2 tactile | 0.765099 | 0.83125 |
| Dev-selected fusion | 0.783492 | 0.85000 |

Last2 − non-tactile family bootstrap mean delta NDCG@10은 `0.295028`, 95% CI `[0.203259, 0.391518]`이다. 그러나 이 benchmark는 기존 Experiment 14 test를 이미 관찰했고 user ID가 없으며 pseudo-label 기반이므로 exploratory replication이다.

## 5. 아직 없는 핵심 산출물

다음 파일은 2026-09-07 19:21 KST 점검 시 없었으며, Experiment 16은 아직 완료가 아니다.

- `artifacts/tactile_coverage.json`
- `artifacts/product_tactile_profiles.parquet`
- `artifacts/generic_feature_report.json`
- `artifacts/multimodal_selection.json`
- `artifacts/backbone_test_results.csv`
- `artifacts/general_recommendation_results.json`
- `artifacts/multimodal_recommendation_results.json`
- `artifacts/sanity_checks.json`
- `notion/STRONG_RECOMMENDER_TACTILE_RESULTS.md`

## 6. 안전한 재개 순서

먼저 현재 process/chunk/artifact 상태를 재검증한다. 상태가 이 문서보다 진전되어 있으면 더 최신 파일 상태를 우선한다.

### Phase A — 남은 전체 이미지/feature chunk resume

동일 GPU에서 shard 3개를 병렬로 실행한다. 각 shard는 `chunk_index % 3`으로 배타적으로 파일을 담당하므로 같은 chunk를 동시에 덮어쓰지 않는다.

```bash
cd /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile
PY=/home/user/onsesang/miniconda3/envs/texture/bin/python

$PY build_tactile_profiles.py --shard-index 0 --num-shards 3
$PY build_tactile_profiles.py --shard-index 1 --num-shards 3
$PY build_tactile_profiles.py --shard-index 2 --num-shards 3
```

Codex에서는 세 장기 명령을 각각 별도 PTY/background session으로 실행하고 모두 종료될 때까지 주기적으로 확인한다. 기존 complete chunk는 skip된다. 한 shard가 실패하면 성공 shard를 다시 돌리지 말고 실패 shard만 같은 인자로 resume한다.

세 shard가 모두 exit 0이고 826개 download-status chunk가 확인된 뒤:

```bash
$PY build_tactile_profiles.py --finalize-only
```

`tactile_coverage.json`과 `product_tactile_profiles.parquet` 생성, download coverage 825,868/825,868, 값 범위/NaN을 검증한다. inference success가 825,868보다 작은 것은 영구 이미지 실패가 있으면 정상이다.

### Phase B — strong tactile validation 선택

```bash
$PY tune_tactile_reranker.py --model-key strong
```

`alpha_search.csv`, validation reranked ranks, selection lock의 `alpha_selected=true`를 검증한다. Test를 보지 않고 alpha/profile/class count가 선택되어야 한다.

### Phase C — generic FashionCLIP + SMORE validation

```bash
$PY build_generic_features.py
$PY train_multimodal.py
```

- Generic baseline은 fine-tune하지 않은 FashionCLIP image/text feature다.
- Last2 probability를 generic baseline 입력으로 섞지 않는다.
- Dense all-pairs modality graph 대신 문서화된 deterministic FAISS IVF sparse kNN adapter를 쓴다.
- SMORE가 재현 가능한 이유로 실패하면 `multimodal_selection.json`에 N/A 사유를 보존한다. 오류를 숨기거나 test 결과로 모델을 선택하지 않는다.

SMORE validation이 `validation_locked`이면:

```bash
$PY generate_candidates.py --split validation --model-key smore
$PY tune_tactile_reranker.py --model-key smore
```

N/A이면 해당 분기만 건너뛰고 selection lock의 multimodal validation 상태가 닫혔는지 확인한다.

### Phase D — one-shot test 및 최종 평가

다음 순서를 바꾸지 않는다.

```bash
$PY evaluate_backbones_test.py
$PY generate_candidates.py --split test --model-key strong
$PY evaluate_general_rec.py
```

SMORE가 validation에서 잠겼다면:

```bash
$PY generate_candidates.py --split test --model-key smore
```

그 뒤 공통 마무리:

```bash
$PY evaluate_multimodal_test.py
$PY evaluate_tactile_rec.py
$PY sanity_checks.py
$PY make_report.py
$PY -m unittest test_pipeline.py
```

`evaluate_backbones_test.py`는 one-shot guard가 있으므로 `backbone_test_results.csv`가 이미 생긴 뒤에는 재실행하지 않는다. 부분 실패 시 해당 stage의 idempotency/guard와 기존 artifact를 먼저 확인한다.

## 7. 완료 판정

다음 조건을 모두 만족해야 완료라고 보고한다.

- 전체 URL-eligible download-status coverage가 825,868/825,868
- Last2 full-catalog profile 및 generic FashionCLIP feature report 생성
- strong tactile alpha가 validation에서 잠김
- SMORE validation 결과 또는 명확한 reproducible N/A 사유가 잠김
- one-shot backbone test와 strong/general evaluation 완료
- 가능한 경우 multimodal 및 multimodal+tactile test 완료
- `sanity_checks.json` status가 pass
- `test_pipeline.py` 전체 통과
- `notion/STRONG_RECOMMENDER_TACTILE_RESULTS.md` 생성
- raw/protected inputs hash 불변 확인
- 최종 Discord 알림 전송

최종 보고에서는 일반 next-item 결과와 explicit tactile-query 결과를 분리하고, bootstrap CI, candidate recall, zero-history 비율, tactile coverage, human audit 생략을 함께 적는다.

## 8. 완료된 Experiment 17–19 상태

이들은 현재 미완료 Experiment 16보다 나중 번호지만 이미 별도 실행이 끝났다. 재실행하지 않는다.

- Experiment 17: `complete_lexical_feasibility_not_preference_ground_truth`
- Experiment 18: `model_pilot_complete_human_validation_pending`; AI preliminary audit은 human gold가 아님
- Experiment 19: `complete_exploratory_human_audit_skipped`
- Experiment 19 최종 전달 문서: `experiments/19_explicit_preference_exploratory/notion/GPT_FULL_EXPERIMENT_PROCESS_RESULTS_EVALUATION.md`

Experiment 19의 핵심 test 결과:

- Category baseline NDCG@10: 0.050544
- Category + explicit tactile preference NDCG@10: 0.050652
- Delta: +0.00010725
- Paired bootstrap 95% CI: [-0.00044850, +0.00074556]

0을 포함하므로 이 평가에서 확실한 추가 개선을 확인하지 못했다. 이 결과를 Experiment 16의 아직 미완료인 full-catalog strong recommender 결과와 혼동하지 않는다.

## 9. Discord와 비밀정보

Discord webhook URL은 credential이다. 이 handoff에는 의도적으로 저장하지 않았다. 새 세션에서 사용자가 다시 제공하거나 `DISCORD_WEBHOOK_URL` 환경변수로 전달해야 한다.

- webhook 값을 source, Markdown, JSON, shell history용 스크립트, Git에 기록하지 않는다.
- 전송 로그에는 HTTP status와 단계명만 남기고 URL을 출력하지 않는다.
- 알림 시점: resume 시작, 각 phase 완료, 재시도/실패, 최종 완료.

## 10. 새 세션 첫 검증 체크리스트

1. `AGENTS.md` 전체 읽기.
2. 이 handoff 전체 읽기.
3. GPU/disk/process 확인.
4. `feature_chunks`의 expected 826 대비 parquet/NPZ/download file 수와 corruption 확인.
5. `selection_lock.json` 상태 확인.
6. 완료 파일이 새로 생겼는지 확인해 최신 stage부터 재개.
7. Discord credential을 파일에 기록하지 않고 전달받기.
8. Phase A부터 끝까지 진행하고 결과를 과장 없이 문서화.

## 11. 2026-09-07 22:39 KST 사용자 요청 중단 상태 — 이 절이 위의 오래된 진행 상태를 대체함

사용자가 실행 중단을 요청했다. 요청을 처리하는 동안 진행 중이던 Strong test candidate 생성은 다음 stage를 시작하기 전에 자체적으로 정상 종료했다. 완성 산출물을 삭제하거나 되돌리지 않았고, 그 뒤의 평가는 시작하지 않았다.

### 안전 중단 확인

- 실행 중인 `generate_candidates.py`, `evaluate_*.py`, `tune_tactile_reranker.py`, `train_multimodal.py` 프로세스: 0
- 실행 중이던 보조 감사 작업: 모두 interrupt
- GPU experiment compute process: 0
- `artifacts` 아래 `.tmp`/`.partial`: 0
- selection lock status: `test_evaluated_no_retuning_allowed`
- test가 이미 열렸으므로 이후 validation 학습·선택·alpha tuning은 절대 다시 실행하지 않는다.
- `evaluate_backbones_test.py`도 재실행하지 않는다.

### 이번 세션에서 완료된 핵심 단계

- tactile catalog: 825,869 items, URL eligible 825,868, profiles 825,840, HTTP failure 28 + no-URL 1
- generic FashionCLIP/SMORE graph와 SMORE LR validation 2종 완료
- SMORE selected LR 0.001, epoch 10, validation NDCG@10 `0.004143728769545105`
- tactile percentile의 protocol 불일치(stable ordinal tie)를 평균 동점 순위로 수정하고 unit regression test 추가
- Strong alpha search를 수정 정의로 validation-only 재검산: alpha 0 / all_history / 14 classes 유지, NDCG@10 `0.004692826694992827`
- SMORE tactile alpha search: alpha 0 / all_history / 14 classes, NDCG@10 `0.004143728769545105`
- backbone one-shot test 정확히 1회 완료 및 독립 전수 감사 PASS
  - 5개 모델 각각 2,035,490행
  - Strong SASRec test NDCG@10 `0.00578731812221174`
  - result SHA256 `204f69ac76e5f9373587df0aec0e0c5bf8298688c1121f46f76de6db9182cce5`
- Strong SASRec test candidate 생성 정상 완료
  - `artifacts/test_candidate_manifest.json`: complete
  - supported 281,395 / no-history 1,754,095 / chunks 2,199 / K 3,000
  - first `000000000_000000127.npz`, last `000281344_000281394.npz`
  - 생성 완료 이벤트 시각: 2026-09-07T13:38:56Z

### 중단 시점의 미완료 작업

- Strong test candidate 2,199 chunks의 독립 전수 감사는 시작 직전에 사용자 요청으로 중단했다. manifest/파일 수/연속 first-last/임시 파일 부재까지만 확인했다.
- `evaluate_general_rec.py`는 아직 시작하지 않았다.
- SMORE test candidate 생성과 전수 감사는 아직 시작하지 않았다.
- `evaluate_multimodal_test.py`, `evaluate_tactile_rec.py`, `sanity_checks.py`, `make_report.py`, 최종 unit test와 raw/protected 최종 hash 검증은 아직 남아 있다.
- 따라서 Experiment 16은 아직 최종 완료가 아니다.

### 다음 세션의 정확한 재개 순서

1. 이 문서와 `AGENTS.md`를 읽고 관련 프로세스가 0인지 확인한다.
2. `selection_lock.json`이 `test_evaluated_no_retuning_allowed`인지, backbone result SHA와 pin된 protocol/checkpoint/tactile/graph hash가 맞는지 확인한다.
3. **`generate_candidates.py --split test --model-key strong`을 재실행하지 말고**, 기존 2,199 chunks와 no-history parquet를 전수 검증한다. UID/target 정렬, finite score, iid 범위, 행별 후보 중복, history 누출, score+iid tie-break, target-in-K iff base-rank<=K, assembled base rank==`sasrec_test_per_user.parquet`를 확인한다.
4. 위 감사가 PASS일 때만 `$PY evaluate_general_rec.py`를 1회 실행한다. Strong alpha가 0이므로 모든 test rank가 동일하고 movement/paired bootstrap delta/CI가 정확히 0이어야 한다.
5. `$PY generate_candidates.py --split test --model-key smore`를 실행하고 expected 2,199 chunks를 같은 방식으로 전수 감사한다.
6. `$PY evaluate_multimodal_test.py`, `$PY evaluate_tactile_rec.py`, `$PY sanity_checks.py`, `$PY make_report.py`, `$PY -m unittest test_pipeline.py` 순으로 마무리한다.
7. raw Arrow 2개와 protected 72개 hash를 마지막으로 재검증하고 최종 Discord 알림을 보낸다.

이번 세션의 코드 보강에는 test 데이터 read 전 in-progress lock 전환, 중단 복구, atomic publish, 재실행 guard, selected checkpoint/tactile/graph hash pinning, `train_history_length` cohort 정정, v3 family cold-start mask 정정(`families.train`)과 강화된 23개 sanity check가 포함된다. 현재 unit test는 11/11 PASS다. Webhook credential은 이 문서나 산출물에 저장하지 않았다.
