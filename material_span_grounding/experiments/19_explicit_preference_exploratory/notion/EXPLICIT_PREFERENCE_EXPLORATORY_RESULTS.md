# 명시적 촉감 선호 기반 추천 — 탐색 실험 19

**자동 실험 완료. 사용자 요청으로 human audit은 생략했다. 사람 검증된 선호 정확도·촉감 만족도·확증적 논문 성능으로 해석하지 않는다.**

## 1. 기존 실험과 차이

| 항목 | 실험 16 | 이번 실험 19 |
|---|---|---|
| 사용자 촉감 정보 | 과거 상품 이미지 촉감 벡터 평균 | 과거 리뷰에서 Qwen이 추출한 명시적 like/dislike |
| 추출 단위 | 상품 14차원 | 원문 표현과 위치를 보존한 모든 lexical occurrence |
| 속성 부재 | 상품 확률에 포함 | 상태와 태도를 분리하고 불확실하면 보류 |
| 카테고리 전이 | 전체 history 벡터 | 같은 category만; other·카테고리 미연결은 보류 |
| 조건·부위 | 별도 분리 없음 | 무조건적 whole_garment/unknown만 primary; 나머지 원문 evidence 보존 |
| 후보 생성 | BPR Top-300 | validation Recall@300으로 BPR/인기도 중 선택 |
| 사람 검증 | 없음 | 없음; AI 예비 audit은 기준 검토에만 사용, gold로 사용하지 않음 |

실험16에서는 beta=.15, alpha=0으로 tactile 추가 효과가 없었다. 이번 실험은 후보 생성과 점수식을 함께 변경했으므로 16→19의 개선 전체를 tactile 효과라고 해석하면 안 된다. 이번 실험 내부의 explicit−category가 핵심 비교다.

## 2. 데이터 범위와 처리

- 기존 validation 1,110명 / test 3,283명과 7,365 parent 상품 카탈로그 유지.
- 공식 split에 연결된 해당 평가 사용자들의 키워드 리뷰 3,923개, 사용자 2,083명, 표현 5,865개 전체 추출. 표본 수 제한 없음.
- 원문 2,500,939개 전체에 대한 lexical 조사는 실험17을 재사용했다. 원문 전체를 Qwen으로 추출한 것은 아니며, 키워드 밖 표현의 recall은 측정하지 않았다.
- split별 occurrence: {'train': 2841, 'test': 1557, 'validation': 1467}
- 모델: Qwen/Qwen3-VL-32B-Instruct / revision 0cfaf48183f594c314753d30a4c4974bc75f3ccb / 4-bit NF4 + BF16; text-only 선호 추출.
- 기존 Last2 이미지 확률은 재사용했다. 재학습, 기존 threshold 변경, raw dataset 수정은 하지 않았다.
- 최초 실패와 formatting 재시도를 모두 보존했다. 두 차례 보정 후에도 통과하지 않은 항목은 추정해 채우지 않고 제외했다.

```json
{
  "attempts": 5865,
  "valid_schema_and_anchored_quote": 5540,
  "initial_invalid": 391,
  "final_invalid": 325,
  "errors": {
    "quote_not_anchored_to_focal": 242,
    "enum": 83
  },
  "attitudes": {
    "unknown": 2694,
    "like": 1940,
    "dislike": 902,
    "mixed": 4
  },
  "states": {
    "present": 5055,
    "absent": 403,
    "uncertain": 63,
    "not_tactile": 19
  },
  "profile_filters": {
    "explicit_eligible_before_category_and_time": 2139,
    "attitude_abstain": 2584,
    "unmapped": 105,
    "scoped_or_third_party": 412,
    "conditional": 238,
    "state_abstain": 62
  },
  "semantic_accuracy": null,
  "human_audit": "skipped_by_user"
}
```

## 3. 실험 흐름과 점수

전체 평가 사용자 lexical occurrence → 고정 prompt Qwen 추출 → schema/정확한 원문 위치 검사 → 추천 시점 전 history만 필터 → category/class별 local preference → 고정 후보에서 reranking → validation weight 고정 → test 탐색 보고.

한 리뷰에서 같은 class가 여러 번 언급돼도 리뷰 하나의 가중치를 넘지 않도록 평균한다. 리뷰 간 충돌 역시 평균하며 0.5이면 방향성 없음으로 처리한다. open-vocabulary 원문과 scope/condition은 validated_evidence.parquet에 그대로 남긴다.

desired_presence는 상태와 평가의 조합이다. present+like 또는 absent+dislike는 1, present+dislike 또는 absent+like는 0이다. 이는 같은 class의 확률에 대한 국소적인 matching 방향일 뿐 반대 class를 생성하거나 영구 선호의 정답으로 간주하지 않는다. uncertain/unknown/mixed/not_tactile은 선호로 변환하지 않는다.

`utility = mean((2*desired_presence-1) * (item_probability-.5) * n/(n+2))`

`score = (1-alpha)*category_base_percentile + alpha*utility`

n은 해당 category/class에 대한 고유 리뷰 수다. 지원 evidence가 없으면 utility=0으로 category ranking을 유지한다. other를 제외하며 cross-category transfer는 0이다. 전반적 상품 긍정만으로 모든 촉감을 선호한다고 판단하지 않는다.

likes_only는 local attitude=like인 evidence만으로 별도 프로필을 만든다(부재 상태를 좋아하는 표현도 포함). shuffled는 사용자별 프로필을 교환하되 받는 사용자의 추천 시점보다 앞선 donor evidence만 사용한다. 단일 seed 탐색 대조군이며, 다중 shuffle 유의성 검정이 아니다.

review_only는 이번에 추출한 cohort-history의 상품 리뷰만 사용한다. 추천 시점 이전, 허용된 history split, 평가 사용자 본인 제외 규칙을 적용한다. sparse feature이므로 전체 리뷰 기반 oracle upper bound가 아니다. hybrid는 누락된 review feature를 이미지로 채우며 v3 test-family 상품은 항상 이미지를 사용한다.

## 4. Validation 선택

```json
{
  "selection_split": "validation",
  "criterion": "max Recall@300, ties BPR",
  "selected": "popularity",
  "validation_diagnostics": {
    "bpr": {
      "recall_at_300": 0.13873873873873874,
      "top10": {
        "n": 1110,
        "ndcg_at_10": 0.0055440598492359165,
        "hr_at_10": 0.012612612612612612,
        "mrr_at_10": 0.003462033462033462
      }
    },
    "popularity": {
      "recall_at_300": 0.2126126126126126,
      "top10": {
        "n": 1110,
        "ndcg_at_10": 0.035019880653716716,
        "hr_at_10": 0.06486486486486487,
        "mrr_at_10": 0.025669598169598167
      }
    }
  },
  "old_baseline_preserved": true
}
{
  "split": "validation",
  "beta": 0.05,
  "alphas": {
    "explicit": 0.2,
    "shuffled": 0.5,
    "likes_only": 0.2,
    "history_mean": 0,
    "review_only": 0.1,
    "hybrid": 0.2
  },
  "metric": "NDCG@10",
  "ties": "smallest weight",
  "config_sha256": "3cb0863d520e2159c26d0139d88227196ce013cd0ba86ed69b8a49ed52ab4fb6",
  "validation_components_sha256": "3a2c86e3bbdf0cbfa867f9cfb61dc6601980b0cd924ca754047f8628dc5303be"
}
```

모든 branch의 alpha는 validation NDCG@10으로 따로 선택했다. 동률이면 작은 값을 선택한다. Test 평가 전에 selection.json을 기록했다. 기존 cohort를 앞선 연구에서 이미 열람했으므로 새로운 독립 확증 test라고 부르지 않는다.

## 5. Test 결과

| 방법 | NDCG@10 | HR@10 | MRR@10 |
|---|---:|---:|---:|
| base | 0.046859 | 0.092294 | 0.032755 |
| category | 0.050544 | 0.102955 | 0.034373 |
| explicit | 0.050652 | 0.102955 | 0.034534 |
| shuffled | 0.050299 | 0.102955 | 0.034117 |
| likes_only | 0.050676 | 0.102955 | 0.034555 |
| history_mean | 0.050544 | 0.102955 | 0.034373 |
| review_only | 0.050419 | 0.102650 | 0.034291 |
| hybrid | 0.050277 | 0.102955 | 0.034071 |
| popularity_full_catalog | 0.046859 | 0.092294 | 0.032755 |

Candidate Recall@300: 0.322875

popularity_full_catalog는 전체 카탈로그 기준 참고선이다. 나머지 main 방법은 같은 Top-300 후보를 공유한다. Category나 tactile 점수에 따라 정답 상품을 후보에 강제로 넣지 않았다.

## 6. 표본 지원과 subset

```json
{
  "validation": {
    "users": 1110,
    "users_with_profile": 141,
    "users_with_candidate_support": 141,
    "candidate_support_fraction": 0.024888888888888887,
    "users_with_review_candidate_support": 116,
    "user_time_checks_passed": true,
    "seen_item_checks_passed": true,
    "cross_category_weight": 0
  },
  "test": {
    "users": 3283,
    "users_with_profile": 427,
    "users_with_candidate_support": 415,
    "candidate_support_fraction": 0.024598436389481164,
    "users_with_review_candidate_support": 366,
    "user_time_checks_passed": true,
    "seen_item_checks_passed": true,
    "cross_category_weight": 0
  }
}
```

| subset | n | Category NDCG@10 | Explicit NDCG@10 | Delta와 paired 95% CI |
|---|---:|---:|---:|---|
| all | 3283 | 0.05054447283302749 | 0.05065172343587139 | 0.00010725060284389484 / [-0.0004484950446248755, 0.0007455588000879884] |
| profile_supported | 415 | 0.05522036750100267 | 0.056068810221813536 | 0.0008484427208108597 / [-0.0036549733481474078, 0.0058716669837605845] |
| candidate_hit | 1060 | 0.15654481538757475 | 0.15687698871694883 | 0.0003321733293740634 / [-0.0014770518512351371, 0.002334584277288085] |
| image_training_unseen_family | 410 | 0.0 | 0.0 | 0.0 / [0.0, 0.0] |
| review_feature_supported | 366 | 0.053526875163564296 | 0.05413117564325023 | 0.0006043004796859275 / [-0.005003212379379724, 0.006116054526331627] |

## 7. 해석

명시적 선호 branch의 선택 alpha는 0.2, category 대비 NDCG@10 차이는 0.000107, paired user bootstrap 95% CI는 [-0.0004484950446248755, 0.0007455588000879884]다.
양의 alpha가 선택됐지만, 개선 여부는 category 대비 delta/CI와 지원 표본 수를 함께 해석해야 한다. AI 추출 정확도가 검증됐다는 뜻은 아니다.
얕은 history, 제한된 카탈로그, 조건/부위 보류, 오류를 포함할 수 있는 Qwen 라벨이 모두 영향을 줄 수 있다. 이 실험만으로 개별 원인의 인과적 기여를 확정하지 않는다.
candidate_hit와 profile_supported 결과는 조건부 진단이다. 이 값이 좋아도 전체 사용자 결과를 대체할 수 없다. Cold subset은 이미지 학습에서 제외한 family이지, CF 상호작용이나 모든 다른 사용자의 미래 정보까지 배제한 cold-start가 아니다.

## 8. 미래 리뷰 비교 — 독립 정답 아님

```json
{
  "shared_user_category_class_pairs": 24,
  "non_tied_pairs": 24,
  "users": 22,
  "agreement": 1.0,
  "meaning": "Same-Qwen historical/future local-opinion consistency only. Not human preference accuracy, recommendation satisfaction, or independent validation."
}
```

과거/미래 모두 같은 Qwen으로 추출했으므로 이는 pseudo-label consistency다. 사람 만족도, 추천된 상품을 직접 만져본 평가, 또는 AI 오류와 독립적인 검증을 대체하지 않는다. 이 통계는 가중치 선택이나 추천 점수에 사용하지 않았다.

## 9. 한계와 보존 검증

- No human audit; all extracted labels are model pseudo-labels.
- Previously inspected cohort: validation-only weights do not create a new confirmatory test.
- User-relative histories are time-filtered; pretrained Last2 and collective recommender data are not globally time-clean.
- Fixed eligible catalog is 7,365 of 825,869 items; this is not full-catalog Amazon recommendation.
- Review-only features use sparse annotated cohort histories, not a full review upper bound.
- Category-local, unconditional garment-level restriction drops conditional and out-of-catalog preferences.
- Image-training-unseen family subset is not a claim of interaction or global temporal cold-start.
- Future review consistency is not independent satisfaction evaluation.

보호 대상으로 기록한 12개 입력 hash는 모두 동일하다. 원문·모델 전체 트리에 대한 과도한 보존 주장이 아니라 protocol.json에 나열된 입력 검증이다.

## 10. 산출물과 재현

- artifacts/results.json: 전체 결과와 한계
- artifacts/validated_evidence.parquet: 원문, focal offset, Qwen 판정
- artifacts/validation_user_profiles.json / test_user_profiles.json: provenance가 연결된 사용자 프로필
- artifacts/selection.json / validation_search.csv: validation 가중치 선택
- artifacts/per_user_results.csv: 방법별 순위와 subset mask
- artifacts/score_breakdowns.json: 고정 규칙으로 뽑은 5명 추천 점수 분해
- artifacts/protocol.json / evaluation_protocol.json: 실행 규칙과 입력 hash
- artifacts/annotations.jsonl / repair_annotations.jsonl: 최초 출력과 재시도 기록

```bash
python pipeline.py prepare
python evaluate.py candidates
python pipeline.py infer
python pipeline.py repair
python pipeline.py repair
python -m unittest -v test_preference.py
python evaluate.py evaluate
python write_report.py
```

기존 사람 audit 양식은 보존됐다. 나중에 실제 사람 판정을 수행하면 별도 human 결과로 추가할 수 있다. 현재 실험을 human-audited로 소급 변경하지 않는다.
