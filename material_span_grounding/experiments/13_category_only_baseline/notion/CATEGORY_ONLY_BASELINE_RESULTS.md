# Category-only Baseline Results

## 1. 실험 목적

이미지 없이 상품 category만으로 v3 tactile atomic-class 성능의 어느 정도가 설명되는지 측정했다. 성능 최대화가 아니라 category shortcut의 크기를 진단하는 통제 실험이다.

## 2. 데이터와 leakage 방지

기존 v3의 8,498개 ASIN target/mask와 동일한 family-disjoint split(train 6,300, development 1,077, locked test 1,121)을 그대로 사용했다. category field는 `category`이다. vocabulary는 train에서만 만들었고 UNK를 포함해 12개다. development/test UNK 수는 각각 0/0다. train/dev/test family overlap은 모두 0이다.

학습용 파생 NPZ에는 train/development만 들어 있으며 locked-test label은 development 선택이 동결된 뒤 별도 평가 단계에서 처음 사용했다. Qwen grounding과 v3 target 생성은 재실행하지 않았다.

## 3. 모델 구조

`category ID → 64차원 learnable embedding → linear → 14 logits` 구조다. 예측 입력은 category 하나뿐이며 이미지, FashionCLIP feature/model, title, description, review, brand를 사용하지 않았다.

## 4. 학습 방법

Observed pair에만 masked BCE를 적용했다. positive weight는 train에서만 계산하고 [0.25, 4.0]로 clip했다. AdamW(lr=0.001, weight decay=0.01), batch 256, 최대 30 epoch, patience 5를 사용했다. Development macro-F1로 epoch 3을 선택했고 class별 threshold는 development에서 0.10–0.90, 0.05 간격으로 고정했다.

## 5. 전체 결과

| Split | Macro-F1 | Micro-F1 | Macro-AP | Micro-AP | Macro-AUROC | Micro-AUROC |
|---|---:|---:|---:|---:|---:|---:|
| Development | 0.6317 | 0.7202 | 0.5699 | 0.7406 | 0.6030 | 0.7879 |
| Locked test | 0.5797 | 0.7120 | 0.5359 | 0.7557 | 0.5749 | 0.7972 |

## 6. class별 결과

| Class | Observed | Positive | Negative | Precision | Recall | F1 | AP | AUROC | Threshold |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| soft | 656 | 618 | 38 | 0.9421 | 1.0000 | 0.9702 | 0.9377 | 0.4528 | 0.10 |
| firm | 631 | 12 | 619 | 0.0412 | 0.3333 | 0.0734 | 0.0240 | 0.4797 | 0.30 |
| smooth | 154 | 88 | 66 | 0.5714 | 1.0000 | 0.7273 | 0.6442 | 0.6271 | 0.10 |
| rough | 159 | 64 | 95 | 0.4025 | 1.0000 | 0.5740 | 0.4721 | 0.5551 | 0.10 |
| non_elastic | 419 | 21 | 398 | 0.0501 | 1.0000 | 0.0955 | 0.0605 | 0.5471 | 0.10 |
| elastic | 463 | 390 | 73 | 0.8423 | 1.0000 | 0.9144 | 0.8822 | 0.6195 | 0.10 |
| thin | 667 | 461 | 206 | 0.6912 | 1.0000 | 0.8174 | 0.7096 | 0.5507 | 0.10 |
| thick | 667 | 197 | 470 | 0.2956 | 0.9289 | 0.4485 | 0.3254 | 0.5379 | 0.40 |
| flexible | 109 | 49 | 60 | 0.4400 | 0.6735 | 0.5323 | 0.4467 | 0.4770 | 0.50 |
| stiff | 117 | 54 | 63 | 0.4615 | 1.0000 | 0.6316 | 0.4828 | 0.5303 | 0.10 |
| warm | 221 | 157 | 64 | 0.7104 | 1.0000 | 0.8307 | 0.8117 | 0.6493 | 0.10 |
| cool | 216 | 64 | 152 | 0.3667 | 0.5156 | 0.4286 | 0.3689 | 0.5679 | 0.50 |
| spongy | 13 | 1 | 12 | 0.3333 | 1.0000 | 0.5000 | 0.5000 | 0.9167 | 0.45 |
| crisp | 14 | 10 | 4 | 1.0000 | 0.4000 | 0.5714 | 0.8373 | 0.5375 | 0.55 |

`firm`, `non_elastic`, `spongy`는 희소 class이므로 표에서 제거하지 않았다. 표본 수가 매우 작아 F1/AP 변동성이 크며, 단일 split 결과를 일반화해서는 안 된다.

## 7. FashionCLIP last2와 비교

| Model | Image used? | Category used? | Test Macro-F1 | Test Micro-F1 | Test Macro-AP |
|---|---|---|---:|---:|---:|
| Category-only | No | Yes | 0.5797 | 0.7120 | 0.5359 |
| Frozen FashionCLIP | Yes | No | 0.5784 | 0.7621 | 0.5607 |
| Projection | Yes | No | 0.6166 | 0.7824 | 0.6143 |
| Last1 | Yes | No | 0.6050 | 0.8145 | 0.6412 |
| Last2 | Yes | No | 0.6010 | 0.8216 | 0.6232 |
| Full | Yes | No | 0.5801 | 0.8066 | 0.6073 |

Last2 − Category-only: Macro-F1 +0.0214, Micro-F1 +0.1096, Macro-AP +0.0872.

| Class | Category-only F1 | Last2 F1 | Last2 − Category-only |
|---|---:|---:|---:|
| soft | 0.9702 | 0.9702 | +0.0000 |
| firm | 0.0734 | 0.0000 | -0.0734 |
| smooth | 0.7273 | 0.7304 | +0.0032 |
| rough | 0.5740 | 0.6087 | +0.0347 |
| non_elastic | 0.0955 | 0.0645 | -0.0309 |
| elastic | 0.9144 | 0.9144 | +0.0000 |
| thin | 0.8174 | 0.8242 | +0.0068 |
| thick | 0.4485 | 0.5294 | +0.0809 |
| flexible | 0.5323 | 0.6614 | +0.1292 |
| stiff | 0.6316 | 0.6310 | -0.0006 |
| warm | 0.8307 | 0.8698 | +0.0391 |
| cool | 0.4286 | 0.6933 | +0.2648 |
| spongy | 0.5000 | 0.2857 | -0.2143 |
| crisp | 0.5714 | 0.6316 | +0.0602 |

- 이미지 모델 우위가 큰 class(ΔF1 ≥ 0.05): thick, flexible, cool, crisp
- 거의 같은 class(|ΔF1| ≤ 0.02): soft, smooth, elastic, thin, stiff
- Category-only F1이 더 높은 class: firm, non_elastic, spongy

## 8. category shortcut 관점의 해석

Category-only가 Last2 macro-F1의 90% 이상에 도달해, 현재 성능의 상당 부분이 category shortcut으로 설명될 가능성이 크다. same-category evaluation이 필수적이다.

이 비교만으로 이미지 모델이 촉감을 ‘이해한다’고 단정할 수 없다. 높은 Category-only 성능은 category prior의 설명력을, 양의 Last2−Category 차이는 그 prior를 넘어서는 image-correlated signal의 가능성을 뜻한다. class별 차이는 표본 수, target noise, threshold 효과와 함께 해석해야 한다.

## 9. 한계

Category는 coarse label 11종이고 embedding+linear 모델은 category별 prior에 가깝다. 같은 category 안의 시각적 다양성을 평가하지 않으며, 희소 class의 결과는 불안정하다. 또한 target 자체가 review/Qwen-derived supervision이므로 시각적으로 관측 불가능한 속성이 포함될 수 있다.

## 10. 다음 실험 제안

가장 중요한 후속 실험은 same-category evaluation이다. Category를 고정한 상태에서 Last2가 제품 간 tactile 차이를 구분하는지 측정하고, category-stratified bootstrap confidence interval 및 category+image 결합 모델을 추가하면 category prior와 이미지의 증분 기여를 더 직접적으로 분리할 수 있다.

## Sanity checks

- PASS — `no_image_tensor_loaded`
- PASS — `no_fashionclip_feature_or_model_used`
- PASS — `category_vocabulary_train_only`
- PASS — `qwen_grounding_not_regenerated`
- PASS — `original_v3_target_unchanged_and_reused`
- PASS — `original_family_split_unchanged_and_reused`
- PASS — `family_overlap_zero`
- PASS — `locked_test_not_used_for_training_or_early_stopping`
- PASS — `locked_test_not_used_for_threshold_selection`
- PASS — `loss_and_metrics_observed_mask_only`
- PASS — `only_category_is_predictive_input`
- PASS — `v2_v3_source_results_not_modified`
