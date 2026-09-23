# History>=3 추천 실험 결과

## 1. 연구 질문

과거 상호작용이 없는 사용자가 다수인 전체 평균에서는 개인화 차이가 희석될 수 있다. 따라서 평가 시점 이전 interaction이 3개 이상인 사용자만 평가해 순차 추천과 촉각 개인화 효과를 직접 비교했다. 학습 데이터는 줄이지 않았다.

## 2. 데이터

- Amazon Fashion: 2,035,490 users, 825,869 parent items, 2,474,375 interactions.
- Validation history>=3: 14,731 users.
- Test history>=3: 29,991 users.

| split | history_group | users |
| --- | --- | --- |
| validation | 3-4 | 9408 |
| validation | 5-9 | 4047 |
| validation | 10+ | 1276 |
| validation | all_history3 | 14731 |
| test | 3-4 | 21644 |
| test | 5-9 | 6776 |
| test | 10+ | 1571 |
| test | all_history3 | 29991 |

## 3. 재사용한 기존 artifact

| Artifact | Source | Reused? | Reason | Hash |
| --- | --- | --- | --- | --- |
| processed Amazon Fashion split | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/data/events.parquet | REUSE_DIRECTLY | cohort-independent immutable input | 65395aa4e3ef3ea6ab71d297dddc27f0c1e2922367bad2555e6c7e8c0c1a749c |
| user history cache/source | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/data/events.parquet | REUSE_AFTER_FILTERING | rebuild validation/test histories from immutable events and filter evaluation rows only | 65395aa4e3ef3ea6ab71d297dddc27f0c1e2922367bad2555e6c7e8c0c1a749c |
| user mapping | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/data/users.parquet | REUSE_DIRECTLY | cohort-independent immutable input | 9fae226f9c2c2209bbf3feaadc939251dfaeb3695c1daa5cc2dbc1131698a961 |
| item mapping/catalog | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/data/catalog.parquet | REUSE_DIRECTLY | cohort-independent immutable input | 860ae8b3844b2f3bb2b5d76dc8f7fca6373198a63cca42db47b79d213301b02f |
| ASIN to parent_ASIN mapping | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/data/child_parent_mapping.parquet | REUSE_DIRECTLY | cohort-independent immutable input | cfa4b7d3445c184a6839c27548d877bfd72d6aa6f523b2cc518609bb81c85805 |
| validation event/targets | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/data/validation_targets.parquet | REUSE_AFTER_FILTERING | cohort-independent immutable input | b2cfbaa558fcc1a3a1657d53ab33ba476e88c62dd8b4d44ac984bc351e709ee8 |
| test event/targets | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/data/test_targets.parquet | REUSE_AFTER_FILTERING | cohort-independent immutable input | 27d9c49bdb983276b7007fd584e7ee71d25b150c3010112c1c6368474c2e9d20 |
| popularity ranking/cache | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/data/catalog.parquet | REUSE_FOR_REEVALUATION | cohort-independent immutable input | 860ae8b3844b2f3bb2b5d76dc8f7fca6373198a63cca42db47b79d213301b02f |
| BPR checkpoints | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/artifacts/checkpoints/bpr_lr0.0003.pt | REUSE_FOR_REEVALUATION | cohort-independent immutable input | 1ac0ab95835015f577d7181481b0b6f712b828b0366060bf92c8c26609bad0d0 |
| SASRec checkpoints | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/artifacts/checkpoints/sasrec_lr0.0003.pt | REUSE_FOR_REEVALUATION | cohort-independent immutable input | 8420c256b08b0444a558d5de0b32a313c4f990d78db4660561dff9909885f2bb |
| eSASRec checkpoints | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/artifacts/checkpoints/esasrec_lr0.0003.pt | REUSE_FOR_REEVALUATION | cohort-independent immutable input | 8772b7538aaeca0f605e5df217a83a7698478d0e2358ded1896e37aaa17484cb |
| SMORE checkpoint/features | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/artifacts/checkpoints/smore_lr0.001.pt | REUSE_FOR_REEVALUATION | cohort-independent immutable input | 4eea61fb8766653bd4e6de261ef5c189292593836f19dcfacf16ffa0bbbd9189 |
| FashionCLIP feature cache | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/data/smore/image_feat.npy | REUSE_DIRECTLY | cohort-independent immutable input | f8555764be7eb7c2fde9efefed211c67026c0c5aaaf9a7b2a112405acb3c8d1c |
| image cache | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/artifacts/feature_chunks | REUSE_DIRECTLY | cohort-independent immutable input |  |
| Last2 14D tactile probability | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/artifacts/product_tactile_profiles.parquet | REUSE_DIRECTLY | cohort-independent immutable input | a56b834afa985b6bb3a44e5e4cb9dc553693d2b66202c284283b20c945190133 |
| fashionclip_last2.pt | /home/user/onsesang/material_span_grounding/experiments/12_class_multilabel_fashionclip_ft/models/fashionclip_last2.pt | REUSE_DIRECTLY | cohort-independent immutable input | 073b542a9d6bd4450aa1f48596c756cc0812b1b5d914945e8f94f7c3fda1934a |
| validation results | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/artifacts/backbone_validation_results.csv | REUSE_AFTER_FILTERING | select checkpoints with history>=3 columns, never the all-user winner | f1fc7afc84c6d78a9975614e7f7058877e85803fc5f78075d5942b3908c8fa47 |
| candidate results | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/artifacts/validation_candidate_chunks | REUSE_AFTER_FILTERING | rankings are cohort-independent; retain only history>=3 rows |  |
| alpha search | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/artifacts/alpha_search.csv | MUST_RECOMPUTE | evaluation cohort changed; rerun the frozen grid | c04148cfc6bfafe653215323def7d231282fca0315e9f4a3cbc4e194c837bc25 |
| per-user test rankings | /home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/artifacts/sasrec_test_per_user.parquet | REUSE_AFTER_FILTERING | rankings are unchanged; recompute metrics after history>=3 filtering | a221c2f6bdd24fc178939468dfdb6b722dcf3114f499e19dcc5a79d1afd26192 |

## 4. 추천 Backbone

- Popularity: 학습 데이터에서 자주 등장한 상품을 먼저 추천합니다.
- BPR-MF: 사용자와 상품의 잠재 벡터를 쌍별 순위 손실로 학습합니다.
- SASRec: 과거 순서를 한 방향 Transformer로 요약해 다음 상품을 예측합니다.
- eSASRec: SASRec에 LiGR 계열 구조와 다중 음성 표본 학습을 적용합니다.
- BERT4Rec: 과거 sequence 일부를 가리는 양방향 Transformer 학습으로 다음 상품을 예측합니다.
- GRU4Rec: GRU가 과거 순서를 순차적으로 요약해 다음 상품을 예측합니다.
- SMORE-derived: FashionCLIP 이미지·텍스트 graph를 결합한 기존 SMORE 파생 기준선입니다.

## 5. Validation Backbone 결과

| model | NDCG@10 | HR@10 | MRR@10 | Recall@100 | Recall@300 | Recall@500 | Recall@1000 | Recall@3000 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Popularity | 0.00275566 | 0.00563438 | 0.00189143 | 0.02036522 | 0.03217704 | 0.03923698 | 0.05403571 | 0.09327269 |
| BPR-MF | 0.00199870 | 0.00414093 | 0.00135744 | 0.01215125 | 0.01764985 | 0.02022945 | 0.02511710 | 0.03842237 |
| SASRec | 0.00300162 | 0.00549861 | 0.00224745 | 0.02077252 | 0.03143032 | 0.03808295 | 0.04975901 | 0.07317901 |
| eSASRec | 0.00296944 | 0.00590591 | 0.00208824 | 0.02022945 | 0.03129455 | 0.03984794 | 0.05539339 | 0.08533026 |
| BERT4Rec | 0.00294975 | 0.00583803 | 0.00207873 | 0.01846446 | 0.03068359 | 0.03713258 | 0.04860498 | 0.07494400 |
| GRU4Rec | 0.00298953 | 0.00543072 | 0.00224545 | 0.01690313 | 0.02803611 | 0.03536759 | 0.04880863 | 0.07535130 |
| SMORE-derived | 0.00171252 | 0.00285113 | 0.00136676 | 0.00570226 | 0.00821397 | 0.01038626 | 0.01323739 | 0.02416672 |

## 6. 선택 Backbone

Validation NDCG@10 우선 규칙으로 **SASRec**을 선택했다. 후보 K는 3000이며, Recall 0.80 기준 충족 여부는 False이다.

## 7. Final Test Backbone 결과

아래 test는 모델 선택에 사용하지 않은 최종 평가용 데이터이며 모든 모델이 같은 29,991명이다.

| Model | NDCG@10 | HR@10 | MRR@10 | candidate Recall@selected_K |
| --- | --- | --- | --- | --- |
| Popularity | 0.00281439 | 0.00606849 | 0.00183312 | 0.08315828 |
| BPR-MF | 0.00137083 | 0.00270081 | 0.00096922 | 0.02764163 |
| SASRec | 0.00349417 | 0.00576840 | 0.00280234 | 0.06578640 |
| eSASRec | 0.00321906 | 0.00603514 | 0.00236740 | 0.07488913 |
| BERT4Rec | 0.00304059 | 0.00536828 | 0.00231645 | 0.06858724 |
| GRU4Rec | 0.00306869 | 0.00516822 | 0.00241713 | 0.06641993 |
| SMORE-derived | 0.00117644 | 0.00190057 | 0.00095120 | 0.01907239 |

## 8. Candidate Recall

| model | model_key | K | Recall |
| --- | --- | --- | --- |
| Popularity | popularity | 100 | 0.02036522 |
| BPR-MF | bpr | 100 | 0.01215125 |
| SASRec | sasrec | 100 | 0.02077252 |
| eSASRec | esasrec | 100 | 0.02022945 |
| BERT4Rec | bert4rec | 100 | 0.01846446 |
| GRU4Rec | gru4rec | 100 | 0.01690313 |
| SMORE-derived | smore | 100 | 0.00570226 |
| Popularity | popularity | 300 | 0.03217704 |
| BPR-MF | bpr | 300 | 0.01764985 |
| SASRec | sasrec | 300 | 0.03143032 |
| eSASRec | esasrec | 300 | 0.03129455 |
| BERT4Rec | bert4rec | 300 | 0.03068359 |
| GRU4Rec | gru4rec | 300 | 0.02803611 |
| SMORE-derived | smore | 300 | 0.00821397 |
| Popularity | popularity | 500 | 0.03923698 |
| BPR-MF | bpr | 500 | 0.02022945 |
| SASRec | sasrec | 500 | 0.03808295 |
| eSASRec | esasrec | 500 | 0.03984794 |
| BERT4Rec | bert4rec | 500 | 0.03713258 |
| GRU4Rec | gru4rec | 500 | 0.03536759 |
| SMORE-derived | smore | 500 | 0.01038626 |
| Popularity | popularity | 1000 | 0.05403571 |
| BPR-MF | bpr | 1000 | 0.02511710 |
| SASRec | sasrec | 1000 | 0.04975901 |
| eSASRec | esasrec | 1000 | 0.05539339 |
| BERT4Rec | bert4rec | 1000 | 0.04860498 |
| GRU4Rec | gru4rec | 1000 | 0.04880863 |
| SMORE-derived | smore | 1000 | 0.01323739 |
| Popularity | popularity | 3000 | 0.09327269 |
| BPR-MF | bpr | 3000 | 0.03842237 |
| SASRec | sasrec | 3000 | 0.07317901 |
| eSASRec | esasrec | 3000 | 0.08533026 |
| BERT4Rec | bert4rec | 3000 | 0.07494400 |
| GRU4Rec | gru4rec | 3000 | 0.07535130 |
| SMORE-derived | smore | 3000 | 0.02416672 |

실제 다음 상품이 초기 추천 후보 안에 충분히 포함되지 않는 문제가 남아 있으며, K는 validation 규칙으로만 고정했다.

## 9. Tactile Profile

평가 이전 history의 category-local Last2 14차원 평균을 사용했다. Test에서 tactile inference가 가능한 history로 profile이 생성된 사용자는 29,991/29,991명(100.00%)이다. 실제 test target category와 같은 category의 과거 tactile support가 있는 사용자는 18,277명(60.94%)이고 평균 support는 1.285개다. 과거 interaction은 선호의 직접 증거가 아니라 noisy proxy이다.

## 10. Alpha Search

선택값: profile=all_history, classes=14, alpha=0.

| profile | classes | alpha | NDCG@10 | HR@10 | MRR@10 |
| --- | --- | --- | --- | --- | --- |
| all_history | 14 | 0.00000000 | 0.00300162 | 0.00549861 | 0.00224745 |
| all_history | 14 | 0.05000000 | 0.00218182 | 0.00414093 | 0.00159781 |
| all_history | 14 | 0.10000000 | 0.00210530 | 0.00407304 | 0.00152260 |
| all_history | 14 | 0.15000000 | 0.00205453 | 0.00393728 | 0.00149660 |
| all_history | 14 | 0.20000000 | 0.00206621 | 0.00400516 | 0.00149520 |
| all_history | 14 | 0.25000000 | 0.00202506 | 0.00386939 | 0.00147955 |
| all_history | 14 | 0.30000000 | 0.00198540 | 0.00373362 | 0.00146568 |
| all_history | 14 | 0.35000000 | 0.00198466 | 0.00373362 | 0.00146481 |
| all_history | 14 | 0.40000000 | 0.00199048 | 0.00373362 | 0.00147085 |
| all_history | 14 | 0.45000000 | 0.00199061 | 0.00373362 | 0.00147123 |
| all_history | 14 | 0.50000000 | 0.00197409 | 0.00366574 | 0.00146767 |
| all_history | 14 | 0.55000000 | 0.00196215 | 0.00359785 | 0.00146993 |
| all_history | 14 | 0.60000000 | 0.00196215 | 0.00359785 | 0.00146993 |
| all_history | 14 | 0.65000000 | 0.00196423 | 0.00359785 | 0.00147220 |
| all_history | 14 | 0.70000000 | 0.00196341 | 0.00359785 | 0.00147144 |
| all_history | 14 | 0.75000000 | 0.00195058 | 0.00352997 | 0.00147257 |
| all_history | 14 | 0.80000000 | 0.00194902 | 0.00352997 | 0.00147096 |
| all_history | 14 | 0.85000000 | 0.00197162 | 0.00359785 | 0.00148114 |
| all_history | 14 | 0.90000000 | 0.00202741 | 0.00380151 | 0.00149736 |
| all_history | 14 | 0.95000000 | 0.00199387 | 0.00366574 | 0.00148944 |
| all_history | 14 | 1.00000000 | 0.00132456 | 0.00285113 | 0.00085881 |
| all_history | 8 | 0.00000000 | 0.00300162 | 0.00549861 | 0.00224745 |
| all_history | 8 | 0.05000000 | 0.00228460 | 0.00461612 | 0.00159934 |
| all_history | 8 | 0.10000000 | 0.00214466 | 0.00420881 | 0.00153507 |
| all_history | 8 | 0.15000000 | 0.00205688 | 0.00393728 | 0.00149865 |
| all_history | 8 | 0.20000000 | 0.00209508 | 0.00407304 | 0.00151120 |
| all_history | 8 | 0.25000000 | 0.00208312 | 0.00400516 | 0.00151317 |
| all_history | 8 | 0.30000000 | 0.00204588 | 0.00386939 | 0.00150196 |
| all_history | 8 | 0.35000000 | 0.00204983 | 0.00386939 | 0.00150630 |
| all_history | 8 | 0.40000000 | 0.00203538 | 0.00380151 | 0.00150506 |
| all_history | 8 | 0.45000000 | 0.00203635 | 0.00380151 | 0.00150619 |
| all_history | 8 | 0.50000000 | 0.00203791 | 0.00380151 | 0.00150781 |
| all_history | 8 | 0.55000000 | 0.00204154 | 0.00380151 | 0.00151169 |
| all_history | 8 | 0.60000000 | 0.00202192 | 0.00373362 | 0.00150490 |
| all_history | 8 | 0.65000000 | 0.00203133 | 0.00373362 | 0.00151621 |
| all_history | 8 | 0.70000000 | 0.00203138 | 0.00373362 | 0.00151651 |
| all_history | 8 | 0.75000000 | 0.00201682 | 0.00366574 | 0.00151538 |
| all_history | 8 | 0.80000000 | 0.00201056 | 0.00366574 | 0.00150810 |
| all_history | 8 | 0.85000000 | 0.00198623 | 0.00359785 | 0.00149566 |
| all_history | 8 | 0.90000000 | 0.00200172 | 0.00366574 | 0.00149727 |
| all_history | 8 | 0.95000000 | 0.00203142 | 0.00373362 | 0.00151500 |
| all_history | 8 | 1.00000000 | 0.00146021 | 0.00291901 | 0.00101207 |
| rating_ge_4 | 14 | 0.00000000 | 0.00300162 | 0.00549861 | 0.00224745 |
| rating_ge_4 | 14 | 0.05000000 | 0.00224650 | 0.00434458 | 0.00162017 |
| rating_ge_4 | 14 | 0.10000000 | 0.00223811 | 0.00434458 | 0.00161252 |
| rating_ge_4 | 14 | 0.15000000 | 0.00221733 | 0.00427670 | 0.00160481 |
| rating_ge_4 | 14 | 0.20000000 | 0.00219177 | 0.00420881 | 0.00159210 |
| rating_ge_4 | 14 | 0.25000000 | 0.00218900 | 0.00420881 | 0.00158946 |
| rating_ge_4 | 14 | 0.30000000 | 0.00214911 | 0.00407304 | 0.00157531 |
| rating_ge_4 | 14 | 0.35000000 | 0.00214951 | 0.00407304 | 0.00157577 |
| rating_ge_4 | 14 | 0.40000000 | 0.00215378 | 0.00407304 | 0.00158019 |
| rating_ge_4 | 14 | 0.45000000 | 0.00213399 | 0.00400516 | 0.00157321 |
| rating_ge_4 | 14 | 0.50000000 | 0.00213710 | 0.00400516 | 0.00157645 |
| rating_ge_4 | 14 | 0.55000000 | 0.00214181 | 0.00400516 | 0.00158210 |
| rating_ge_4 | 14 | 0.60000000 | 0.00212218 | 0.00393728 | 0.00157531 |
| rating_ge_4 | 14 | 0.65000000 | 0.00212426 | 0.00393728 | 0.00157758 |
| rating_ge_4 | 14 | 0.70000000 | 0.00212345 | 0.00393728 | 0.00157682 |
| rating_ge_4 | 14 | 0.75000000 | 0.00210591 | 0.00386939 | 0.00157230 |
| rating_ge_4 | 14 | 0.80000000 | 0.00212398 | 0.00393728 | 0.00157747 |
| rating_ge_4 | 14 | 0.85000000 | 0.00214837 | 0.00400516 | 0.00158935 |
| rating_ge_4 | 14 | 0.90000000 | 0.00222736 | 0.00427670 | 0.00161594 |
| rating_ge_4 | 14 | 0.95000000 | 0.00219350 | 0.00420881 | 0.00158657 |
| rating_ge_4 | 14 | 1.00000000 | 0.00146883 | 0.00319055 | 0.00094246 |
| rating_ge_4 | 8 | 0.00000000 | 0.00300162 | 0.00549861 | 0.00224745 |
| rating_ge_4 | 8 | 0.05000000 | 0.00228175 | 0.00448035 | 0.00162978 |
| rating_ge_4 | 8 | 0.10000000 | 0.00223598 | 0.00434458 | 0.00161066 |
| rating_ge_4 | 8 | 0.15000000 | 0.00217585 | 0.00414093 | 0.00158905 |
| rating_ge_4 | 8 | 0.20000000 | 0.00217503 | 0.00414093 | 0.00158849 |
| rating_ge_4 | 8 | 0.25000000 | 0.00216133 | 0.00407304 | 0.00158857 |
| rating_ge_4 | 8 | 0.30000000 | 0.00213869 | 0.00407304 | 0.00155729 |
| rating_ge_4 | 8 | 0.35000000 | 0.00213102 | 0.00407304 | 0.00154719 |
| rating_ge_4 | 8 | 0.40000000 | 0.00213399 | 0.00407304 | 0.00155058 |
| rating_ge_4 | 8 | 0.45000000 | 0.00213220 | 0.00407304 | 0.00154889 |
| rating_ge_4 | 8 | 0.50000000 | 0.00213555 | 0.00407304 | 0.00155220 |
| rating_ge_4 | 8 | 0.55000000 | 0.00213555 | 0.00407304 | 0.00155220 |
| rating_ge_4 | 8 | 0.60000000 | 0.00211592 | 0.00400516 | 0.00154541 |
| rating_ge_4 | 8 | 0.65000000 | 0.00212063 | 0.00400516 | 0.00155107 |
| rating_ge_4 | 8 | 0.70000000 | 0.00211982 | 0.00400516 | 0.00155032 |
| rating_ge_4 | 8 | 0.75000000 | 0.00209757 | 0.00393728 | 0.00154013 |
| rating_ge_4 | 8 | 0.80000000 | 0.00209251 | 0.00393728 | 0.00153448 |
| rating_ge_4 | 8 | 0.85000000 | 0.00206818 | 0.00386939 | 0.00152203 |
| rating_ge_4 | 8 | 0.90000000 | 0.00209878 | 0.00400516 | 0.00152542 |
| rating_ge_4 | 8 | 0.95000000 | 0.00209580 | 0.00400516 | 0.00152203 |
| rating_ge_4 | 8 | 1.00000000 | 0.00145576 | 0.00291901 | 0.00100662 |

## 11. Final Strong vs Strong + Tactile

| Model | NDCG@10 | HR@10 | MRR@10 |
| --- | --- | --- | --- |
| SASRec | 0.00349417 | 0.00576840 | 0.00280234 |
| SASRec + Tactile | 0.00349417 | 0.00576840 | 0.00280234 |

- paired NDCG@10 delta: 0.00000000
- paired bootstrap 95% CI: [0.00000000, 0.00000000]
- improved / unchanged / worsened: 0 / 29991 / 0
- entered / left Top10: 0 / 0

## 12. History 길이별 진단

| history_group | users | base_NDCG@10 | tactile_NDCG@10 | delta |
| --- | --- | --- | --- | --- |
| 3-4 | 21644 | 0.00347100 | 0.00347100 | 0.00000000 |
| 5-9 | 6776 | 0.00417360 | 0.00417360 | 0.00000000 |
| 10+ | 1571 | 0.00088278 | 0.00088278 | 0.00000000 |

이 구간 결과는 사후 진단이며 모델이나 alpha 선택에 사용하지 않았다.

## 13. 기존 실험과 달라진 점

기존 Experiment 16은 all-user가 주 평가 집단이었다. 이번 실험은 validation 시 train history, test 시 train+선행 validation history가 3개 이상인 사용자만 평가했다. 서로 다른 평가 population의 수치를 직접적인 성능 향상으로 해석하지 않는다.

실행 중 제공된 번호 순서(Step 10 backbone test, Step 12 tactile validation)를 먼저 따른 예비 backbone test pass가 있었다. 더 엄격한 “모든 validation 선택 후 test” 원칙을 적용하기 위해 이 pass의 산출물을 삭제하지 않고 `artifacts/quarantined_pre_alpha_test/`에 격리했다. 예비 test 값은 선택 코드의 입력으로 사용되지 않았으며, alpha=0을 포함한 모든 validation 결정을 hash로 고정한 뒤 최종 backbone/tactile test를 다시 실행했다. 따라서 최종 표는 두 번째 pass만 사용하지만, 완전히 미열람된 confirmatory test였다고 주장하지 않는다.

## 14. 결과 해석

이 결과는 충분한 과거 interaction이 있는 Amazon Fashion 사용자에서 모델 간 다음-item 순위 차이와 Last2 후처리 효과를 보여준다. 직접적인 촉감 만족도, 구매 의도, 다른 category나 플랫폼으로의 일반화를 증명하지 않는다.

## 15. 논문에 사용할 수 있는 핵심 수치

- Validation users: 14,731; Test users: 29,991.
- Selected backbone: SASRec.
- Candidate K: 3000.
- Tactile alpha: 0 (all_history, 14 classes).
- Tactile NDCG@10 delta: 0.00000000, 95% CI [0.00000000, 0.00000000].

## 16. Limitations

- 0-core split은 대부분 사용자의 학습 history가 매우 짧으며 history>=3 집단은 전체 사용자를 대표하지 않는다.
- 전체 catalog에서 train evidence가 없는 상품이 많아 추천 후보 recall이 낮다.
- 리뷰 interaction은 click이나 purchase와 동일하지 않으며 촉각 선호의 직접 label이 아니다.
- SMORE-derived는 기존 FashionCLIP 이미지·텍스트 graph adapter이며 원 논문의 완전한 재현이라고 주장하지 않는다.
- BERT4Rec/GRU4Rec은 현재 저장소 안의 투명한 최소 구현이고 동일 탐색 예산을 썼지만 모든 공개 구현의 세부 최적화를 포함하지 않는다.
