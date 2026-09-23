# Same-category Evaluation Results

## 1. 실험 목적

상품 category를 고정한 상태에서 공식 FashionCLIP Last2 score가 동일 category 내 tactile-positive 상품을 tactile-negative 상품보다 높게 ranking하는지 평가했다. 이것은 새 모델 학습이 아니라 고정 checkpoint의 post-hoc diagnostic이다.

## 2. 평가 설계

Locked test의 각 `(category, tactile class)`를 독립적인 binary ranking cell로 정의했다. mask=1이고 positive와 negative가 모두 있는 cell만 primary 평가에 포함했다. AUROC와 모든 positive-negative pair의 tie=0.5 pairwise accuracy를 primary로 사용하고, AP는 해당 cell prevalence를 뺀 AP lift와 함께 해석했다. 기존 development-selected global threshold의 F1은 secondary metric이며 category별 threshold를 선택하지 않았다.

## 3. 데이터와 support

기존 split과 target/mask를 그대로 사용했다: 전체 8,498, train 6,300, development 1,077, locked test 1,121; test family 1,035, family overlap 0. Category는 11종이며 전체 valid cell은 107/154, reliable-support(positive≥10, negative≥10)는 28개다.

| Category | Test products | Valid classes | Reliable classes |
|---|---:|---:|---:|
| accessory | 120 | 13 | 3 |
| dress | 392 | 12 | 10 |
| other | 65 | 11 | 1 |
| outerwear | 32 | 10 | 0 |
| pants | 104 | 11 | 2 |
| skirt | 33 | 8 | 0 |
| sleepwear | 39 | 10 | 0 |
| sweater | 46 | 6 | 0 |
| swimwear | 4 | 2 | 0 |
| top | 224 | 12 | 9 |
| underwear | 62 | 12 | 3 |

## 4. Global same-category 결과

| Metric | Category-only | Last2 | Last2 − Category-only |
|---|---:|---:|---:|
| Macro-cell AUROC | 0.5000 | 0.6568 | 0.1568 |
| Pair-weighted AUROC | 0.5000 | 0.7528 | 0.2528 |
| Macro category-cell AP | 0.4902 | 0.6830 | 0.1928 |
| Macro AP lift | 0.0000 | 0.1928 | 0.1928 |
| Macro normalized AP lift | 0.0000 | 0.3867 | 0.3867 |
| Pairwise accuracy | 0.5000 | 0.7528 | 0.2528 |

Category-only의 category/class 내부 최대 probability range는 0이며 tolerance 1e-06 이하다. 실제 계산된 AUROC/pairwise accuracy가 0.5이고 AP lift가 0에 가까워 constant predictor sanity check를 통과했다.

## 5. Class별 결과

| Class | Valid cat. | Reliable cat. | Obs. | Pos. | Last2 macro AUC | Last2 pair-w. AUC | Macro AP lift | Cat-only AUC |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| soft | 8 | 2 | 656 | 618 | 0.4766 | 0.6479 | -0.0066 | 0.5000 |
| firm | 5 | 0 | 631 | 12 | 0.6759 | 0.8036 | 0.1098 | 0.5000 |
| smooth | 10 | 2 | 154 | 88 | 0.5113 | 0.7132 | 0.1399 | 0.5000 |
| rough | 10 | 2 | 159 | 64 | 0.5364 | 0.7267 | 0.1496 | 0.5000 |
| non_elastic | 8 | 0 | 419 | 21 | 0.6049 | 0.6754 | 0.1692 | 0.5000 |
| elastic | 9 | 4 | 463 | 390 | 0.6529 | 0.6348 | 0.0779 | 0.5000 |
| thin | 11 | 5 | 667 | 461 | 0.7663 | 0.7736 | 0.2242 | 0.5000 |
| thick | 11 | 6 | 667 | 197 | 0.7794 | 0.7901 | 0.2842 | 0.5000 |
| flexible | 8 | 1 | 109 | 49 | 0.6138 | 0.6625 | 0.2545 | 0.5000 |
| stiff | 9 | 2 | 117 | 54 | 0.6001 | 0.6642 | 0.1898 | 0.5000 |
| warm | 8 | 2 | 221 | 157 | 0.7966 | 0.8429 | 0.2013 | 0.5000 |
| cool | 9 | 2 | 216 | 64 | 0.8002 | 0.8583 | 0.4154 | 0.5000 |
| spongy | 0 | 0 | 13 | 1 | N/A | N/A | N/A | N/A |
| crisp | 1 | 0 | 14 | 10 | 1.0000 | 1.0000 | 0.5000 | 0.5000 |

집중 class:

- `thick`: valid/reliable category 11/6, pair-weighted AUROC 0.7901, macro AP lift 0.2842.
- `flexible`: valid/reliable category 8/1, pair-weighted AUROC 0.6625, macro AP lift 0.2545.
- `cool`: valid/reliable category 9/2, pair-weighted AUROC 0.8583, macro AP lift 0.4154.
- `rough`: valid/reliable category 10/2, pair-weighted AUROC 0.7267, macro AP lift 0.1496.
- `smooth`: valid/reliable category 10/2, pair-weighted AUROC 0.7132, macro AP lift 0.1399.
- `thin`: valid/reliable category 11/5, pair-weighted AUROC 0.7736, macro AP lift 0.2242.
- `warm`: valid/reliable category 8/2, pair-weighted AUROC 0.8429, macro AP lift 0.2013.

`firm`, `non_elastic`, `spongy`, `crisp`는 sparse cell이 많아 descriptive result로만 해석해야 한다. AUROC 1.0 같은 극단값도 support가 작으면 강한 증거가 아니다.

## 6. Category별 결과

| Category | Valid classes | Reliable classes | Observed pairs | Last2 macro AUROC | Last2 macro AP lift |
|---|---:|---:|---:|---:|---:|
| accessory | 13 | 3 | 491 | 0.7482 | 0.2511 |
| dress | 12 | 10 | 1506 | 0.7622 | 0.1994 |
| other | 11 | 1 | 292 | 0.6689 | 0.1977 |
| outerwear | 10 | 0 | 125 | 0.4738 | 0.1883 |
| pants | 11 | 2 | 474 | 0.5611 | 0.1089 |
| skirt | 8 | 0 | 136 | 0.5547 | 0.1098 |
| sleepwear | 10 | 0 | 177 | 0.6192 | 0.1674 |
| sweater | 6 | 0 | 175 | 0.6353 | 0.1756 |
| swimwear | 2 | 0 | 9 | 1.0000 | 0.5833 |
| top | 12 | 9 | 838 | 0.6916 | 0.1650 |
| underwear | 12 | 3 | 283 | 0.6992 | 0.2470 |

## 7. Reliable-support 분석

사전에 고정한 positive≥10 및 negative≥10 조건을 만족하는 28개 cell 결과다.

| Metric | Category-only | Last2 | Difference |
|---|---:|---:|---:|
| Macro-cell AUROC | 0.5000 | 0.7144 | 0.2144 |
| Pair-weighted AUROC | 0.5000 | 0.7578 | 0.2578 |
| Macro category-cell AP | 0.5502 | 0.7438 | 0.1936 |
| Macro AP lift | 0.0000 | 0.1936 | 0.1936 |
| Macro normalized AP lift | 0.0000 | 0.4174 | 0.4174 |
| Pairwise accuracy | 0.5000 | 0.7578 | 0.2578 |

## 8. Bootstrap CI

Locked-test parent family 단위 paired bootstrap 1,000회(seed 20260904)의 percentile 95% CI다. 각 replicate에서 single-class cell은 안전하게 제외했다.

| Subset / Metric | Last2 estimate | Last2 95% CI | Difference estimate | Difference 95% CI |
|---|---:|---:|---:|---:|
| all_valid / macro_cell_auroc | 0.6568 | [0.6199, 0.7126] | 0.1568 | [0.1199, 0.2126] |
| all_valid / pair_weighted_auroc | 0.7528 | [0.7091, 0.7921] | 0.2528 | [0.2091, 0.2921] |
| all_valid / macro_category_ap_lift | 0.1928 | [0.1834, 0.2418] | 0.1928 | [0.1834, 0.2418] |
| all_valid / pairwise_accuracy | 0.7528 | [0.7091, 0.7921] | 0.2528 | [0.2091, 0.2921] |
| reliable_support / macro_cell_auroc | 0.7144 | [0.6834, 0.7716] | 0.2144 | [0.1834, 0.2716] |
| reliable_support / pair_weighted_auroc | 0.7578 | [0.7130, 0.7995] | 0.2578 | [0.2130, 0.2995] |
| reliable_support / macro_category_ap_lift | 0.1936 | [0.1839, 0.2603] | 0.1936 | [0.1839, 0.2603] |
| reliable_support / pairwise_accuracy | 0.7578 | [0.7130, 0.7995] | 0.2578 | [0.2130, 0.2995] |

Category-centered score는 label을 쓰지 않고 category/class 평균 score만 제거했다. Test 자체 평균을 뺀 transductive diagnostic과 development 평균을 test에 적용한 stricter diagnostic을 모두 저장했다.

| Centering reference | Macro-class AUROC | Pooled AUROC | Pooled AP lift |
|---|---:|---:|---:|
| Locked-test score mean | 0.6791 | 0.7180 | 0.1826 |
| Development score mean | 0.6742 | 0.7178 | 0.1814 |

## 9. F1 vs ranking metric

Same-category 판단의 primary metric은 AUROC, pairwise accuracy, AP lift다. F1은 prevalence와 기존 global development threshold에 민감하므로 CSV에 secondary metric으로만 보존했다. 특히 soft처럼 prevalence가 높은 class는 constant prediction도 높은 F1을 얻을 수 있다.

## 10. Category shortcut에 대한 결론

Last2의 within-category pair-weighted AUROC가 Category-only보다 +0.2528 높고 paired family-bootstrap 95% CI도 0을 상회한다. 따라서 category prior만으로 설명되지 않는 image-correlated within-category ranking signal이 있다는 근거가 있다. 동시에 global Category-only 성능이 높았다는 사실은 category shortcut이 여전히 중요한 설명임을 뜻하므로, 두 현상은 함께 존재한다.

이 결과는 category를 고정해도 image-correlated ranking signal이 남는지를 말할 뿐, 모델이 물리적 촉감을 인과적으로 이해한다는 증거는 아니다.

## 11. 한계

Target은 human ground truth가 아니라 review/Qwen-derived pseudo-label이다. 일부 속성은 이미지에서 직접 관측하기 어렵고, sparse class/cell은 추정 불확실성이 크다. Post-hoc locked-test diagnostic이므로 결과를 본 뒤 cutoff, threshold, checkpoint를 변경하지 않았다.

## 12. 다음 실험

추출된 qualitative candidate를 human audit하고, reliable-support class를 중심으로 category-matched retrieval 및 family/category-stratified 검증을 수행하는 것이 우선이다. 이미지 관측 가능성이 높은 class에만 confidence weighting을 적용하는 downstream 설계도 검토할 수 있다.

## Sanity checks

- PASS — `official_last2_checkpoint_hash_matches_pre_inference_manifest`
- PASS — `model_weights_not_changed`
- PASS — `qwen_grounding_not_executed`
- PASS — `v3_target_not_regenerated_or_modified`
- PASS — `original_family_disjoint_split_reused`
- PASS — `observed_mask_only_evaluated`
- PASS — `category_field_matches_experiment13`
- PASS — `no_category_specific_threshold_tuning`
- PASS — `existing_development_thresholds_reused`
- PASS — `locked_test_not_used_for_model_selection`
- PASS — `category_only_constant_within_category`
- PASS — `single_class_cells_skipped_with_reason`
- PASS — `support_saved_for_every_cell`
- PASS — `existing_v2_v3_v13_files_unchanged`
