# Experiment 20 중단 시점 상세 인계 문서

작성 시각: 2026-09-09 16:33 KST (+09:00)  
안전 중단 시각: 2026-09-09 16:25:06 KST / 2026-09-09 07:25:06 UTC  
실험명: `20_tactile_recommender_spec_completion`  
상태: **안전 중단됨 — 검증 10개 run 중 9개 완료, 마지막 run epoch 2 저장 완료**

이 문서는 새 GPT/Codex 세션이 지금까지의 과학적 설계, 실제 실행 상태, 검증 결과, 잠금 규칙과 재개 방법을 다시 추측하지 않고 그대로 이어받기 위한 상세 handoff다. 아래 경로의 실제 파일을 우선 재검증한 뒤 이 문서와 상태가 다르면 더 최신의 원자적 산출물을 기준으로 삼는다.

---

## 1. 새 GPT에게 바로 전달할 작업 지시

```text
/home/user/onsesang/material_span_grounding/experiments/20_tactile_recommender_spec_completion/EXP20_PAUSED_HANDOFF_20260909.md
를 처음부터 끝까지 읽고 실제 프로세스, tmux, protocol_state, complete/resume checkpoint를 재검증해줘.

Experiment 20은 검증 10개 run 중 9개가 완료됐고, 마지막
I_VX_T_SHUFFLE / learning_rate=0.0003 run이 epoch 2까지 원자적으로 저장된 상태에서 안전 중단됐다.
완료 run, 입력 동결, tactile graph, 구현 잠금은 다시 만들지 말고 보존해.

새 tmux 세션 exp20_continuation에서 train_select.py를 --force 없이 실행해 동일 checkpoint와
optimizer/RNG state를 복원하고 epoch 3부터 이어가. 학습이 끝나 validation selection을 잠근 뒤에만
evaluate_test.py로 재사용 공식 test를 열고, make_report.py와 sanity_checks.py까지 순서대로 완료해.

과학 설정이나 잠긴 metric/training code를 수정하지 말고, test 결과로 어떤 선택도 바꾸지 마.
Track A는 Exp16에서 이미 열었던 공식 test를 재사용하므로 반드시 locked post-hoc exploratory로 표현하고
fresh confirmatory 결과라고 쓰지 마.

Discord webhook은 credential이므로 문서/코드/로그에 URL을 기록하지 말고 DISCORD_WEBHOOK_URL 환경변수로만 전달해.
단계별 알림 상태도 확인해. 완료 후 최종 report와 machine-readable artifacts, sanity check 결과를 검증해줘.
```

---

## 2. 가장 중요한 현재 상태

### 2.1 실행 상태

- 실행 중인 `train_select.py`, `evaluate_test.py`, `make_report.py`: **없음**
- `exp20_continuation` tmux 세션: **없음**
- 마지막으로 실행하던 조합: `I_VX_T_SHUFFLE`, learning rate `0.0003`
- 마지막 완전 저장 epoch: **2 / 20**
- 다음 재개 epoch: **3**
- 전체 validation run 진행률: **9 / 10 완료**
- 공식 Exp20 test 평가: **시작하지 않음**
- 최종 Exp20 report: **아직 생성되지 않음**
- protocol state: `implementation_frozen_before_validation`

사용자 요청에 따라 실행 프로세스에 `SIGINT`를 보냈고 2초 이내 정상 종료했다. 이어서 `exp20_continuation` tmux 세션을 제거하여 자동 후속 실행도 멈췄다. 완료 산출물이나 체크포인트는 삭제하지 않았다.

### 2.2 정확한 resume checkpoint

```text
/home/user/onsesang/material_span_grounding/experiments/20_tactile_recommender_spec_completion/
  artifacts/checkpoints/I_VX_T_SHUFFLE_lr0.0003_seed20260904.resume.pt
```

- 파일 크기: `10,890,020,026` bytes
- mtime: `2026-09-09 16:23:52.699579714 +0900`
- 내부 `epoch`: `2`
- 내부 `best_epoch`: `None`
  - 정상이다. validation은 5 epoch마다 수행하므로 이 run은 아직 첫 validation checkpoint에 도달하지 않았다.
- 이 resume 파일에는 model state, Adam optimizer state, NumPy RNG state, CPU Torch RNG state, CUDA RNG state, 현재 best 값과 bad counter가 들어 있다.
- `train_select.py`를 `--force` 없이 재실행하면 완료된 9개 run은 `.complete.json`을 보고 건너뛰고, 이 run만 epoch 3부터 동일 상태로 이어간다.

### 2.3 안전 중단 감사 이벤트

`artifacts/events.jsonl`의 마지막 안전 중단 기록:

```json
{
  "time_utc": "2026-09-09T07:25:06Z",
  "stage": "exp20_safe_pause",
  "status": "complete",
  "variant": "I_VX_T_SHUFFLE",
  "learning_rate": 0.0003,
  "resume_epoch": 2,
  "tmux_session": "exp20_continuation",
  "completed_validation_runs": 9,
  "total_validation_runs": 10
}
```

안전 중단 이벤트까지 Discord 알림 감사 로그는 `270`건이며 `270/270`이 HTTP `204`, 오류는 `0`건이다. 실제 webhook URL은 credential이므로 어느 handoff/report에도 기록하지 않는다. 이 문서 생성 완료 알림이 추가되면 전체 건수는 1 증가하는 것이 정상이다.

---

## 3. 실험의 배경과 Exp20을 만든 이유

원래 목표는 졸업 프로젝트에서 학습한 tactile image model `fashionclip_last2.pt`를 Amazon Reviews'23 `Amazon_Fashion` 추천에 실제로 적용해 다음을 분리 평가하는 것이다.

1. 강한 추천 backbone이 BPR보다 일반 next-item 추천과 candidate retrieval을 개선하는가.
2. 넓은 전체 catalog에서 Last2 tactile 정보를 추가하면 일반 추천이 개선되는가.
3. 사용자가 촉감 조건을 명시하거나 tactile preference evidence가 있을 때 원하는 촉감 상품을 위로 올리는가.

Experiment 16은 전체 catalog 처리, Strong/SASRec 및 SMORE 계열 실험, 보수적 tactile reranking, explicit tactile exploratory 평가까지 완료했다. 그러나 원래 명세의 핵심 일부, 특히 **진짜 in-model tactile modality와 공정한 modality ablation/control**을 완전히 구현한 것은 아니었다. Exp20은 이 미충족 항목을 고정된 후속 실험으로 채우기 위해 만들었다.

Exp20의 핵심 추가점:

- `fashionclip_last2.pt`에서 얻은 고정 14차원 확률을 별도의 `T` modality로 모델 내부에 투입
- 전체 `825,869` parent-item catalog 유지
- tactile feature가 없는 상품도 catalog에서 제거하지 않고 tactile branch만 정확히 0으로 mask
- interaction-only, interaction+tactile, generic multimodal, generic multimodal+tactile를 같은 split/목적함수/seed로 비교
- 같은 파라미터 수와 broad category/popularity 구조를 통제하기 위한 stratified shuffled tactile negative control 포함
- validation-only learning-rate/epoch 선택 후에만 공식 test를 여는 상태 머신 적용

Experiment 16 최종 보고서는 별도 파일이며 Exp20 validation/test와 혼합하면 안 된다.

```text
/home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile/
  notion/STRONG_RECOMMENDER_TACTILE_RESULTS.md
```

---

## 4. 과학적 주장 범위

### 4.1 Track A는 confirmatory가 아니다

Exp20이 사용할 공식 Amazon_Fashion test split은 Exp16에서 이미 열어 본 split이다. 따라서 Exp20은 구현과 selection을 test 재열람 전에 잠갔더라도 결과 해석은 반드시 다음과 같다.

```text
locked post-hoc exploratory follow-up
```

금지 표현:

- fresh confirmatory test
- official SMORE reproduction
- history proves tactile preference

허용되는 정확한 설명:

- `SMORE-derived scalable adaptation`
- `fixed Last2 tactile modality`
- 재사용 공식 test에 대한 `post-hoc exploratory` 결과

새 confirmatory 주장을 하려면 이전 실험 어디에서도 보지 않은 미래 temporal interaction이나, 후보/질문/partition을 label 수집 전에 hash-lock한 prospective human benchmark가 필요하다.

### 4.2 고정 primary contrast

```text
proposed: I_VX_T
control:  I_VX
metric:   NDCG@10
population: all official Amazon_Fashion test targets
direction: greater is better
seed: 20260904
```

계획된 paired user bootstrap은 1,000회, seed `20260904`, percentile 95% interval이다. 다만 현재 `evaluate_test.py`가 기록하는 것은 exact per-user rank와 paired point contrast이며, 현 구현만으로 bootstrap CI가 최종 report에 자동 포함된다고 가정하면 안 된다. 최종 산출물 생성 후 protocol 대비 보고 항목을 점검해야 한다. test를 본 뒤 분석 규칙을 바꾸면 안 된다.

---

## 5. 핵심 경로와 실행 환경

### 5.1 경로

```text
Project root:
/home/user/onsesang/material_span_grounding

Experiment root:
/home/user/onsesang/material_span_grounding/experiments/20_tactile_recommender_spec_completion

Python:
/home/user/onsesang/miniconda3/envs/texture/bin/python

Final report 예정 경로:
/home/user/onsesang/material_span_grounding/experiments/20_tactile_recommender_spec_completion/
  notion/EXP20_TACTILE_RECOMMENDER_SPEC_COMPLETION_REPORT.md
```

### 5.2 확인된 환경

| 항목 | 값 |
|---|---|
| Python | 3.10.20 |
| PyTorch | 2.5.1+cu121 |
| PyTorch CUDA | 12.1 |
| NumPy | 2.2.6 |
| pandas | 2.3.3 |
| pyarrow | 24.0.0 |
| FAISS | 1.12.0 |
| GPU | NVIDIA A100 80GB PCIe |
| NVIDIA driver | 560.35.03 |
| filesystem free at handoff | 약 598 GiB |
| Exp20 `artifacts/` 크기 | 약 82 GiB |
| Exp20 `data/` 크기 | 약 1.4 GiB |

중단 당시 이 실험의 GPU process는 모두 종료했다. 서버에는 다른 사용자의 GPU process가 있을 수 있으므로 재개 전에 VRAM/process를 다시 확인해야 한다.

---

## 6. 고정 protocol과 모델 정의

### 6.1 공통 학습 규칙

| 설정 | 고정값 |
|---|---|
| primary seed | 20260904 |
| robustness seeds | 20260905, 20260906; primary 선택 대체 불가 |
| embedding dimension | 64 |
| LR grid | 0.001, 0.0003 |
| maximum epochs | 20 |
| validation interval | 매 5 epoch |
| optimizer | Adam |
| objective | BPR, user train positive 전체를 피하는 uniform full-catalog negative 1개 |
| regularization | 1e-6 |
| gradient clipping | 5.0 |
| user-item graph layers | 3 |
| modality graph layers | 1 |
| dropout | 0.1 |
| contrastive weight / temperature | 0.01 / 0.2 |
| contrastive in-batch cap | 1024 |

같은 variant 안에서 checkpoint 선택 순서는 다음으로 고정됐다.

1. full-validation NDCG@10 내림차순
2. HR@10 내림차순
3. MRR@10 내림차순
4. 더 이른 epoch
5. 더 작은 learning rate

다섯 architecture 중 하나만 승자로 골라 나머지를 버리지 않는다. 다섯 그룹을 모두 보고하고, 각 그룹 내부의 LR/epoch만 validation으로 선택한다.

### 6.2 다섯 고정 variant

| ID | 구성 | 수식/역할 |
|---|---|---|
| `I` | interaction | `behavioral_content`; interaction-only control |
| `I_T` | interaction + tactile | `behavioral_content + tactile_side`; tactile ablation |
| `I_VX` | interaction + image + text | `behavioral_content + generic_side`; primary generic control |
| `I_VX_T` | interaction + image + text + tactile | `behavioral_content + generic_side + (1/3)*tactile_side`; primary proposed |
| `I_VX_T_SHUFFLE` | 위와 같으나 tactile vector를 strata 안에서 섞음 | aligned signal이 아닌 capacity/category/popularity 구조 통제 |

`V`는 고정 입력의 generic FashionCLIP image 512D, `X`는 generic FashionCLIP metadata text 512D다. Exp16 SMORE adapter와 맞추기 위해 generic feature table은 recommendation 쪽에서 trainable하다.

`T`는 다음 고정 순서의 Last2 continuous probability 14D이며 threshold를 적용하지 않는다.

```text
soft, firm, smooth, rough, non_elastic, elastic, thin, thick,
flexible, stiff, warm, cool, spongy, crisp
```

Last2 checkpoint와 feature table은 학습하지 않는다. recommendation-side projection, gate, preference parameter만 학습한다. `I_VX_T`의 tactile residual scale `1/3`은 generic 3-view average의 한 branch 상당으로 고정했으며 튜닝하지 않았다.

### 6.3 shuffle control

- seed: `20260904`
- whole 14D item vector를 하나의 단위로 permutation
- availability 유지
- strata: frozen diagnostic category × train-count bucket
- count bucket: `0`, `1_to_5`, `6_to_10`, `11_plus`
- missing item은 missing/zero 그대로 유지
- mapping rows: `825,840`
- fixed points: `44`
- mapping SHA256: `bd1a90a0e900f7b54438ecc9a843ce888b2ceae3a5925371d454e0b1e8b66041`

---

## 7. 입력 동결과 개발 split

### 7.1 입력 manifest

- `artifacts/input_manifest.json`
- 동결 입력 수: `18`
- manifest SHA256 recorded in implementation lock: `8fbd5f90eaeacaa2d5d7ade25baf70345c28bb1f1a17ea374b5057bd4741fe33`
- 공식 Last2 checkpoint SHA256: `073b542a9d6bd4450aa1f48596c756cc0812b1b5d914945e8f94f7c3fda1934a`
- full-catalog tactile profile SHA256: `a56b834afa985b6bb3a44e5e4cb9dc553693d2b66202c284283b20c945190133`
- generic image feature SHA256: `f8555764be7eb7c2fde9efefed211c67026c0c5aaaf9a7b2a112405acb3c8d1c`
- generic text feature SHA256: `8ddfea1615b318dc3c8ddd8bb02954af3f13c93faafcb6583b4b908042b519c2`
- Exp16 processed event source SHA256: `65395aa4e3ef3ea6ab71d297dddc27f0c1e2922367bad2555e6c7e8c0c1a749c`
- validation target SHA256: `b2cfbaa558fcc1a3a1657d53ab33ba476e88c62dd8b4d44ac984bc351e709ee8`
- test target SHA256는 metric 계산 없이 input manifest에 미리 기록: `27d9c49bdb983276b7007fd584e7ee71d25b150c3010112c1c6368474c2e9d20`

테스트 파일 hash를 미리 기록한 것은 test 결과를 열거나 selection에 사용한 것이 아니다. 실제 test rows/metrics 접근은 `validation_locked_before_exp20_test` 이후로 제한돼 있다.

### 7.2 train-only 개발 view

혼합 `events.parquet`를 모델이 직접 읽지 않도록 `prepare_development_views.py`가 audited view를 만들었다.

| 파일 | rows | SHA256 |
|---|---:|---|
| `data/train_events.parquet` | 157,490 | `e5ae2a455b5370a80541bab20d1e0ca1d191b8aebf60076d926b4b7b93abaeb8` |
| `data/validation_events.parquet` | 281,395 | `e0df2eba5ab48c682da654e85e1dc20db8a1aac5cce8014d61479d46b17fecdc` |
| `data/validation_targets.parquet` | 281,395 | `b2cfbaa558fcc1a3a1657d53ab33ba476e88c62dd8b4d44ac984bc351e709ee8` |

validation 전체 target은 281,395개이고 이 중 train history가 있어 personalized model scoring을 받는 사용자는 76,755명이다. 나머지 sparse/zero-history 대상이 전체 평균에 포함되므로 절대 NDCG 값이 낮게 보인다.

### 7.3 실제 train/validation 데이터 통계와 사용 열

handoff 보강 시 실제 parquet와 availability array를 다시 읽어 확인한 값이다. 공식 test row는 현재 state에서 열지 않았다.

#### Training data

`data/train_events.parquet` schema:

```text
user_id: string
parent_asin: string
rating: double
timestamp: int64
split: string
uid: int32
iid: int32
```

| 항목 | 실제 값 |
|---|---:|
| event rows | 157,490 |
| unique train users | 76,755 |
| unique train items | 109,485 |
| unique `(uid, iid)` pairs | 157,490 |
| duplicate pair events | 0 |
| rating min / max / mean | 1.0 / 5.0 / 4.086653 |
| split 값 | `train` 157,490건만 존재 |

모델 학습에서 실제 사용하는 열은 integer `uid`, `iid`다. `rating` 크기는 loss weight나 positive/negative threshold로 쓰지 않고, split에 포함된 모든 review/rating event를 implicit positive로 취급한다. `timestamp`는 upstream official leave-last-out split을 형성하는 데 쓰였지만 현재 BPR model input에는 직접 들어가지 않는다. `user_id`와 `parent_asin`은 identity/provenance용이며 embedding index는 `uid`, `iid`다. `verified_purchase`는 이 materialized view에 없고 학습 filter로 사용하지 않았다. 따라서 interaction을 click 또는 purchase라고 표현하면 안 된다.

#### Validation target data

`data/validation_targets.parquet`는 위 공통 열 외에 다음을 가진다.

```text
train_history_length: int64
history_length: int64
target_train_count: int32
```

| 항목 | 실제 값 |
|---|---:|
| validation target rows / unique users | 281,395 / 281,395 |
| train에 존재하는 UID | 76,755 |
| train에 없는 UID | 204,640 |
| target `(uid, iid)`가 train pair에 이미 존재 | 0 |
| target train-count = 0 | 172,923 |
| target train-count <= 5 | 253,507 |
| target train-count <= 10 | 265,545 |
| train history >= 1 | 76,755 |
| train history >= 3 | 14,731 |
| train history >= 5 | 5,323 |
| train history min / max / mean | 0 / 309 / 0.559676 |
| tactile/image available target | 281,385 |
| tactile/image missing target | 10 |
| split 값 | `validation` 281,395건만 존재 |

Catalog는 `iid`, `parent_asin`, `train_count` 열을 가지며 `iid`는 `0..825868`의 연속 정수다.

| catalog 항목 | 실제 값 |
|---|---:|
| 전체 items | 825,869 |
| train-count > 0 | 109,485 |
| train-count = 0 | 716,384 |
| train_count 합 | 157,490 |

즉 train-cold item 716,384개를 추천 universe에서 제거하지 않는다. validation target 중 172,923개도 train-count 0이다.

### 7.4 variant/run별 실제 입력 데이터 매트릭스

두 LR run은 데이터가 다른 실험이 아니다. 각 variant가 동일 train/validation rows와 seed를 사용하고 learning rate만 달리한다.

| Variant | 공통 interaction/catalog | generic image/text 입력 | tactile 입력 | availability/graph 예외 |
|---|---|---|---|---|
| `I` | `train_events.parquet`, `catalog.parquet`; validation은 `validation_targets.parquet` | 사용 안 함 | 사용 안 함 | cold/no-train user는 popularity fallback |
| `I_T` | 동일 | 사용 안 함 | `tactile_feat_14.npy`, `tactile_available.npy`, `tactile_adj_40_True.pt` | missing 29 item의 tactile branch를 0으로 유지 |
| `I_VX` | 동일 | Exp16 `image_feat.npy`, `text_feat.npy`, image/text graph | 사용 안 함 | image missing 29 item도 catalog 유지; text는 전 item 사용 가능 |
| `I_VX_T` | 동일 | `I_VX`와 동일 | aligned `tactile_feat_14.npy`와 동일 tactile graph | tactile residual만 고정 1/3 scale |
| `I_VX_T_SHUFFLE` | 동일 | `I_VX`와 동일 | `tactile_feat_14_shuffled.npy`, 같은 availability, **같은 원본 tactile graph** | feature vector alignment만 strata 안에서 깨고 architecture/graph/parameterization 유지 |

실제 dense feature 상태:

| Feature | shape | available | missing | unavailable인데 nonzero인 row | available인데 all-zero인 row |
|---|---:|---:|---:|---:|---:|
| generic image | 825,869 × 512 | 825,840 | 29 | 0 | 0 |
| generic text | 825,869 × 512 | 825,869 | 0 | 0 | 0 |
| tactile aligned | 825,869 × 14 | 825,840 | 29 | 0 | 0 |
| tactile shuffled | 825,869 × 14 | 825,840 | 29 | 0 | 0 |

`models_exp20.py`는 tactile에는 `tactile_available` mask를 명시적으로 적용한다. generic image availability array는 모델 내부에서 직접 mask하지 않지만 upstream `image_feat.npy`의 unavailable 29개 row가 정확히 0이며, image graph에서도 이 29개 iid에 닿는 edge가 0임을 재확인했다. text는 모든 catalog item에 feature가 있다. 따라서 missing modality 때문에 item을 제거하거나 다른 item으로 대체하지 않는다.

generic fusion graph는 별도 외부 데이터가 아니라 실행 시 frozen image graph와 text graph의 sparse edge별 max-pool로 만든다. `I_VX_T_SHUFFLE`은 shuffled vector로 tactile graph를 다시 만들지 않고 aligned tactile에서 구축한 같은 frozen graph를 사용한다는 점도 결과 해석 시 명시해야 한다.

---

## 8. tactile feature와 graph 구축 결과

### 8.1 tactile feature

- catalog graph nodes: `825,869`
- tactile feature items: `825,840`
- tactile available SHA256: `d31fb89de6f8769e844269125375e1d3dbf5f8d3fa84709655b57a2042dce6e5`
- frozen 14D feature SHA256: `b8e598474b5eb29790f100a3dcd7603e4b1b6a001e5c67e76132ba4fb74377e9`
- shuffled 14D feature SHA256: `14fceba6d9d355f36b8a1008ce7741f2e9478f8d5a56c14e769fb3d068674054`

### 8.2 tactile graph

- artifact: `data/tactile_adj_40_True.pt`
- 크기: `1,321,345,696` bytes
- graph SHA256: `3148d8f9413a52f34bb4bef74645cbfc4ea87b04f44132e07260dbee0af6a93b`
- graph k: `40`
- FAISS index: `IndexIVFFlat`
- nlist: `7,270`
- index training sample: `150,000`
- audit query sample: `1,000`
- selected nprobe: `32`
- exact-neighbor audit mean Recall@40: `0.99875`
- minimum per-query Recall@40: `0.925`
- acceptance threshold: mean Recall@40 `>= 0.95`
- directed edges before symmetrization: `33,033,600`
- self edge 제거, negative cosine 0 clamp, reverse edge 추가, symmetric degree normalization 적용

처음 graph 실행에서 `missing ROOT import` NameError가 한 번 발생했다. 추천 validation metric을 계산하기 전에 수정하고 재실행했다. sparse COO construction 관련 runtime amendment도 첫 validation metric/checkpoint 전에 implementation lock에 반영됐다. 이 실패는 과학적 결과를 보고 수정한 것이 아니다.

---

## 9. 구현 잠금과 검증 전 점검

### 9.1 synthetic dry run

```json
{
  "status": "pass",
  "official_validation_metrics_computed": false,
  "official_test_metrics_computed": false,
  "synthetic_items": 12,
  "synthetic_edges": 48
}
```

### 9.2 implementation lock

- 현재 lock 파일: `artifacts/implementation_lock.json`
- lock status: `complete`
- 최종 lock SHA256 referenced by all completed checkpoints: `1f745399c2e63e74d0a591d8c76761fbfb58539dd30cad2559dc1f135b6522b3`
- frozen protocol SHA256: `d42e83f73564fb1ea10ecc2d585de46487026a0628791f90d73ba33e1b8b3409`
- frozen model variants SHA256: `d4a2d64f1b8075e705fd15ccac77817a59170d022db2581545c99d55105b9e26`

현재 핵심 source hash는 lock과 일치한다.

| 파일 | SHA256 |
|---|---|
| `common.py` | `b01edb24a6df7aa873884eebc897c29c0220b4211207eeeebe7bf5736a251db8` |
| `models_exp20.py` | `c16ee35ba077fa169463d310737412fdfb37771f2ca2996c5f8a56ad0cb0410b` |
| `train_select.py` | `c735dfd95173dce2f4f9dac166c9475eefe6900ce8f38722f18f9e25c892860a` |

`evaluate_test.py`, `make_report.py`, `sanity_checks.py`는 validation 실행이 시작된 뒤 추가된 **post-lock orchestration/report/check 전용 파일**이다. 학습, 선택 또는 frozen `evaluate_exact()` metric core는 바꾸지 않았다.

| post-lock orchestration 파일 | 현재 SHA256 |
|---|---|
| `evaluate_test.py` | `758d09b75075ea672a702f7d6f1b4021fce29f49497c99a4643f8eef24bcd83e` |
| `make_report.py` | `09c49961c7c43f4a1ce2534bbe56d8472b6d6c152083d66e5144bbf4fa13e3e7` |
| `sanity_checks.py` | `1c6a1e5be062d38ceb4f6cb30b7eb24457693c8864925d103f74e07330bc6982` |

이 세 파일은 그 성격과 추가 시점을 최종 report에서 숨기지 말아야 한다.

### 9.3 실행 중 발생한 예외와 처리

| 시각(UTC) | 단계 | 예외/중단 | 처리와 과학적 영향 |
|---|---|---|---|
| 2026-09-08 03:34:34 | tactile graph | `NameError`: `ROOT` import 누락 | recommendation validation 전에 import를 수정하고 graph를 처음부터 정상 생성; metric 기반 수정 아님 |
| 2026-09-08 03:45:35 | 첫 validation startup | graph initialization이 너무 느려 수동 blocked 처리 | validation metric/checkpoint가 하나도 생기기 전에 중단; dense/비효율 초기화를 sparse COO runtime construction으로 수정하고 implementation lock을 amendment한 뒤 시작 |
| 이후 장기 학습 | validation grid | 세션 중단과 사용자 요청 중단이 여러 차례 있었음 | `.resume.pt`의 model/optimizer/NumPy/Torch/CUDA RNG를 그대로 복원; `.complete.json` run은 skip; `--force` 및 과학 설정 변경 없음 |
| 2026-09-09 07:25:06 | 마지막 shuffle LR | 사용자 요청 안전 중단 | epoch 2 atomic resume를 확인한 뒤 SIGINT, tmux 제거; 완료 artifact 보존 |

`events.jsonl`에 `exp20_validation_run started`가 여러 번 있는 것은 위 resume 때문에 생긴 실행 감사 기록이다. 동일 run을 서로 다른 실험 결과로 세거나 완료 metric을 중복 평균하지 않는다. 공식 결과 단위는 각 `(variant, learning_rate)`의 단일 `.complete.json`이다.

---

## 10. 완료된 validation 결과

아래는 test가 아니라 **validation** 결과다. `all_official_targets` 281,395개에 대한 exact full-catalog rank metric이다.

### 10.1 Top-K metric: 9개 완료 run

| Variant | LR | best epoch | NDCG@5 | HR@5 | NDCG@10 | HR@10 | MRR@10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `I` | 0.001 | 20 | 0.003809658 | 0.005980917 | **0.004466264** | 0.008024307 | 0.003371367 |
| `I` | 0.0003 | 20 | 0.003777944 | 0.005927611 | 0.004430544 | 0.007953233 | 0.003346390 |
| `I_T` | 0.001 | 15 | 0.003911653 | 0.006083974 | 0.004586792 | 0.008180671 | 0.003481765 |
| `I_T` | 0.0003 | 20 | 0.003948158 | 0.006155049 | **0.004636642** | 0.008287283 | 0.003513348 |
| `I_VX` | 0.001 | 20 | 0.004676747 | 0.007238935 | **0.005544626** | 0.009925549 | 0.004199144 |
| `I_VX` | 0.0003 | 20 | 0.004301474 | 0.006659678 | 0.005037535 | 0.008948276 | 0.003834397 |
| `I_VX_T` | 0.001 | 20 | 0.004612569 | 0.007160753 | **0.005437117** | 0.009726541 | 0.004120290 |
| `I_VX_T` | 0.0003 | 20 | 0.004216696 | 0.006549512 | 0.004940252 | 0.008799019 | 0.003754138 |
| `I_VX_T_SHUFFLE` | 0.001 | 20 | 0.004621596 | 0.007164306 | **0.005447876** | 0.009733648 | 0.004130978 |

굵은 NDCG@10은 현재 각 variant 안에서 가장 좋은 완료 run이다. shuffle의 LR `0.0003`이 아직 끝나지 않았으므로 `I_VX_T_SHUFFLE`의 최종 선택은 아직 잠그면 안 된다.

### 10.2 candidate recall: 9개 완료 run

| Variant | LR | R@100 | R@300 | R@500 | R@1k | R@3k | R@10k | R@30k |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `I` | 0.001 | 0.025167 | 0.041223 | 0.050196 | 0.066309 | 0.104263 | 0.166961 | 0.240630 |
| `I` | 0.0003 | 0.025093 | 0.041348 | 0.050530 | 0.066771 | 0.105020 | 0.167711 | 0.240633 |
| `I_T` | 0.001 | 0.025327 | 0.041216 | 0.050029 | 0.065808 | 0.103353 | 0.165177 | 0.235153 |
| `I_T` | 0.0003 | 0.025836 | 0.042151 | 0.051170 | 0.067354 | 0.105471 | 0.167203 | 0.236976 |
| `I_VX` | 0.001 | 0.028831 | 0.046102 | 0.055719 | 0.072919 | 0.112927 | 0.178567 | 0.254567 |
| `I_VX` | 0.0003 | 0.027367 | 0.044379 | 0.053636 | 0.070033 | 0.108669 | 0.171783 | 0.244617 |
| `I_VX_T` | 0.001 | 0.028448 | 0.045516 | 0.055129 | 0.072105 | 0.112060 | 0.177462 | 0.254308 |
| `I_VX_T` | 0.0003 | 0.027261 | 0.044489 | 0.053978 | 0.070634 | 0.109874 | 0.174410 | 0.250534 |
| `I_VX_T_SHUFFLE` | 0.001 | 0.028536 | 0.045481 | 0.054958 | 0.071984 | 0.111992 | 0.177302 | 0.253921 |

사전등록 candidate K 규칙은 full-validation recall `>=0.80`을 만족하는 가장 작은 K, 없으면 K=30,000과 `retrieval_bottleneck_unresolved`다. 현재 완료된 어떤 run도 R@30k 0.80에 근접하지 못했다. 따라서 완료 variant들은 fallback K=30,000이 될 것이며, 마지막 run 완료 후 프로그램이 최종 `validation_selection.json`에 기록해야 한다.

### 10.3 epoch별 validation curve

각 셀은 `NDCG@10 / Recall@30000`이다.

| Variant | LR | epoch 5 | epoch 10 | epoch 15 | epoch 20 |
|---|---:|---:|---:|---:|---:|
| `I` | 0.001 | .004449531 / .241077 | .004444589 / .240758 | .004460356 / .240630 | .004466264 / .240630 |
| `I` | 0.0003 | .004414519 / .240985 | .004418731 / .240914 | .004423157 / .240754 | .004430544 / .240633 |
| `I_T` | 0.001 | .004565797 / .235665 | .004583291 / .236184 | **.004586792 / .235153** | .004561300 / .234134 |
| `I_T` | 0.0003 | .004245117 / .230082 | .004435646 / .232485 | .004594447 / .235459 | .004636642 / .236976 |
| `I_VX` | 0.001 | .004943194 / .251959 | .005290191 / .255626 | .005448759 / .255324 | .005544626 / .254567 |
| `I_VX` | 0.0003 | .004944303 / .241117 | .004679277 / .243160 | .004898184 / .244677 | .005037535 / .244617 |
| `I_VX_T` | 0.001 | .004901058 / .251497 | .005179117 / .255921 | .005356621 / .255477 | .005437117 / .254308 |
| `I_VX_T` | 0.0003 | .004738985 / .239947 | .004598631 / .242328 | .004770462 / .246472 | .004940252 / .250534 |
| `I_VX_T_SHUFFLE` | 0.001 | .004964832 / .251188 | .005239172 / .255495 | .005375948 / .255200 | .005447876 / .253921 |

### 10.4 완료 checkpoint SHA256

| Variant | LR | best epoch | selected model checkpoint SHA256 |
|---|---:|---:|---|
| `I` | 0.001 | 20 | `1174a911756bd25c5b71e9f0272610cd45fa5c6b9ac7e03de9b386ec5d428054` |
| `I` | 0.0003 | 20 | `35121d64ea9534557a96ec0c94ef04661c013b0c9267019dcf407cd9f94a978a` |
| `I_T` | 0.001 | 15 | `1f3a1e495be61c7006546f9974097a78c05f61ce8b82c22bb1a0d82e73d21684` |
| `I_T` | 0.0003 | 20 | `830f2411e90acd972986ef1bbfdc8cf36ba44fe7136290dd7fa6d2126a27e426` |
| `I_VX` | 0.001 | 20 | `fbfe0727f790bd8dc7cfc0e74ec509b8a14f2bfb5911be307a7f47f9baa44d95` |
| `I_VX` | 0.0003 | 20 | `ace47a2822072633226d8f8fc1e32bb304bc2519b7c7e1a250fec8034998615c` |
| `I_VX_T` | 0.001 | 20 | `9511a2b4ab6b6963193285ef43bc108e33b930e2db67a6b84c2ac2fe865abdcd` |
| `I_VX_T` | 0.0003 | 20 | `0804c3ba2551db881fb121e7d44e0c1113b9fc657d8029a41c050c4d232ac667` |
| `I_VX_T_SHUFFLE` | 0.001 | 20 | `5eccb2378be9f3e2b3f358798241e566ba6950fd0369288a189a835b6a13ddf8` |

### 10.5 validation 평가에 실제 사용한 데이터와 rank 계산

모든 위 validation metric은 다음과 같이 계산됐다.

1. 평가 target은 `data/validation_targets.parquet`의 281,395개 row를 그대로 사용한다. tactile/image가 없거나 train-count가 0이라는 이유로 target을 제외하지 않는다.
2. validation history는 `data/train_events.parquet`에 있는 해당 UID의 모든 선행 `iid`만 사용한다. validation target/event를 model parameter update나 history에 넣지 않는다.
3. UID가 76,755개 train UID 중 하나면 학습된 user embedding으로 전체 825,869-item score matrix를 batch 단위로 계산한다.
4. 그 UID의 train history item은 모든 variant에서 score를 `-inf`로 바꿔 동일하게 제거한다.
5. target score보다 큰 item 수를 세고, score가 정확히 같으면 더 작은 `iid`가 target보다 앞선 것으로 처리한다. 즉 rank는 1-based이며 tie-break는 canonical `iid` ascending이다.
6. UID가 train에 없으면 학습 user embedding이 없으므로 catalog `train_count` 내림차순, `iid` 오름차순의 deterministic popularity ranking을 쓴다.
7. popularity fallback에서도 이미 본 item이 target보다 앞에 있으면 그 수만큼 rank에서 제외한다. target 자체가 history에 있으면 leakage error를 발생시킨다.
8. 모든 target rank를 합친 뒤 NDCG/HR/MRR 및 rank가 K 이하인 비율을 계산한다. target이 한 개이므로 여기서 `Recall@K`는 full-catalog exact rank가 K 안에 들어온 target의 비율이다.

따라서 표의 Recall@100~30000은 별도 ANN candidate 파일의 recall이 아니라 **동일 full-catalog exact rank에서 K를 잘랐을 때의 target hit 비율**이다. 이 구현 의미를 final report에서 “candidate generator를 따로 실행해 얻은 recall”이라고 잘못 설명하면 안 된다.

### 10.6 평가 예외 처리와 포함/제외 원칙

| 상황 | 실제 처리 |
|---|---|
| train history가 없는 validation user 204,640명 | 제외하지 않고 deterministic popularity fallback; primary 전체 metric에 포함 |
| train history가 있는 user 76,755명 | model exact full-catalog score; train-seen item 공통 제거 |
| train-count 0 item 716,384개 | catalog에 그대로 포함 |
| train-count 0 validation target 172,923개 | 평가에서 그대로 포함 |
| tactile/image missing catalog item 29개 | item 유지; upstream zero row, tactile explicit mask, 해당 modality graph edge 없음 |
| tactile/image missing validation target 10개 | primary metric에 그대로 포함; missing modality가 neutral/zero contribution |
| text missing item | 없음; 825,869개 전부 feature available |
| target이 history에 이미 존재 | leakage로 간주; fallback은 명시적 RuntimeError, personalized 경로도 non-finite target score guard로 실패 |
| score tie | 더 작은 integer `iid` 우선 |
| NaN/Inf loss 또는 target score | 즉시 exception; 값을 대체하거나 run을 조용히 drop하지 않음 |
| failed/missing variant | protocol상 N/A와 error type/trace를 남겨야 하며 다른 model로 대체 금지 |
| low candidate recall | cohort를 골라 threshold 충족으로 바꾸지 않고 K=30,000 + `retrieval_bottleneck_unresolved` |

`train_history_ge_1`, `ge_3`, `ge_5` secondary cohort는 target parquet에 미리 존재하는 `train_history_length`로만 나눈다. target category나 test outcome으로 cohort를 정하지 않는다. 현재 `evaluate_exact()`가 실제 자동 출력하는 cohort는 이 세 history cohort뿐이다. preregistration에 적힌 tactile-support/cold/outside-family cohort는 현재 pipeline에서 자동 생성되지 않으므로 Section 16의 후속 audit 대상으로 남아 있다.

평가에서 사용하지 않은 정보:

- validation `rating` 값: relevance weight 또는 gain으로 사용하지 않음
- validation target의 `timestamp`: rank score에 사용하지 않음
- `user_id`, `parent_asin` 문자열: model feature로 사용하지 않음
- `verified_purchase`: materialized target/view에 없으며 filter/weight로 사용하지 않음
- target category: filter/score/cohort 선택에 사용하지 않음
- review text, Qwen evidence, human audit label: 현재 general validation에 사용하지 않음
- Exp16/14/19 test 결과와 test candidate chunk: development/selection에 사용 금지

### 10.7 test 평가에 예정된 데이터와 예외 처리

현재 Exp20 test는 아직 열지 않았다. `evaluate_test.py`가 validation lock 이후 수행할 처리는 frozen code 기준으로 다음과 같다.

- target: Exp16의 hash-pinned `data/test_targets.parquet`
- model parameter: official train으로만 학습한 selected checkpoint; validation으로 재학습하지 않음
- test-time history: train history + 시간상 앞선 official validation event
- train에 존재하는 UID: selected model exact full-catalog scoring
- train에 존재하지 않는 UID: validation history가 생겼더라도 학습 user embedding이 없으므로 popularity fallback
- seen removal: train 및 preceding validation item을 모든 방법에서 제거
- catalog/missing modality/tie 처리: validation과 동일
- output: variant별 모든 target의 `(uid, iid, rank, variant)` parquet와 aggregated metric
- test 결과 사용: 보고/locked contrast에만 사용; LR, epoch, K, graph, architecture를 다시 선택하지 않음

`evaluate_test.py`는 per-user parquet를 temporary file에 쓴 뒤 atomic replace한다. 기존 per-user 파일이 있으면 row 수가 test target과 같은 경우 재사용하고, 최종 `sanity_checks.py`에서 row 수뿐 아니라 `(uid, iid)` 순서, variant column, positive rank와 SHA256까지 다시 검사한다.

---

## 11. 중단된 마지막 run의 진행 내역

`I_VX_T_SHUFFLE`, LR `0.0003`:

| Epoch | mean training loss | validation |
|---:|---:|---|
| 1 | 0.763017700864123 | 아직 수행 시점 아님 |
| 2 | 0.735449634782680 | 아직 수행 시점 아님 |

이 run에는 아직 `.complete.json`과 best `.pt`가 없다. 첫 validation은 epoch 5가 끝난 뒤 생성된다. `.resume.pt`만 존재하는 것이 정상이다.

이 run이 완료되기 전에는 다음 파일도 아직 없어야 정상이다.

- `artifacts/validation_results.csv`
- `artifacts/validation_selection.json`
- `artifacts/test_results.json`
- `artifacts/test_I_per_user.parquet`
- `artifacts/test_I_T_per_user.parquet`
- `artifacts/test_I_VX_per_user.parquet`
- `artifacts/test_I_VX_T_per_user.parquet`
- `artifacts/test_I_VX_T_SHUFFLE_per_user.parquet`
- `artifacts/report_manifest.json`
- `notion/EXP20_TACTILE_RECOMMENDER_SPEC_COMPLETION_REPORT.md`

handoff 작성 시 실제 점검에서도 위 파일들은 생성되지 않았다.

---

## 12. 잠정 validation 해석 — 최종 test 결론이 아님

마지막 shuffle LR run이 끝나지 않아 전체 selection은 아직 잠기지 않았다. 아래는 현재 완료 결과만으로 계산한 **잠정 관찰**이다.

| 비교 | validation NDCG@10 delta | 상대 변화 | 주의 |
|---|---:|---:|---|
| selected `I_T` − selected `I` | +0.000170378 | +3.8148% | interaction-only 기준 tactile 추가는 validation에서 양수 |
| selected `I_VX` − selected `I` | +0.001078362 | +24.1446% | generic image/text의 validation 이득 |
| selected `I_VX_T` − selected `I_VX` | −0.000107509 | −1.9390% | primary tactile residual은 validation에서 control보다 낮음 |
| aligned `I_VX_T` − shuffled control, 동일 LR 0.001 | −0.000010759 | −0.1975% | 사실상 매우 작은 음의 차이; shuffle LR 0.0003 미완료 |

현재 validation만 보면 generic multimodal `I_VX`가 가장 높고, aligned tactile `I_VX_T`가 이를 넘지 못했다. 그러나 이것은 test 결과가 아니고 paired uncertainty도 계산하지 않았으므로 tactile representation의 일반적 무용성을 결론 내리면 안 된다. 특히 RQ3 explicit tactile utility와 일반 next-item prediction은 별도 문제다.

### 12.1 잠정 selected run의 history cohort 결과

각 셀은 `NDCG@10 / HR@10 / MRR@10 / Recall@30000`이다.

| Variant | train history >=1, n=76,755 | >=3, n=14,731 | >=5, n=5,323 |
|---|---|---|---|
| `I` LR .001 | .002695 / .005081 / .001971 / .147196 | .002995 / .006110 / .002060 / .166044 | .002098 / .004697 / .001329 / .188052 |
| `I_T` LR .0003 | .003320 / .006045 / .002491 / .133802 | .003429 / .006110 / .002604 / .154911 | .002601 / .005260 / .001780 / .170393 |
| `I_VX` LR .001 | .006649 / .012051 / .005006 / .198293 | .005627 / .010590 / .004126 / .226461 | .003812 / .007702 / .002654 / .245914 |
| `I_VX_T` LR .001 | .006255 / .011322 / .004717 / .197342 | .005459 / .010250 / .004005 / .226529 | .004041 / .008078 / .002827 / .242720 |
| `I_VX_T_SHUFFLE` LR .001 | .006294 / .011348 / .004756 / .195922 | .005402 / .010590 / .003848 / .222863 | .003569 / .007890 / .002297 / .237836 |

전체 cohort와 personalized cohort의 수치 관계가 직관과 다르게 보일 수 있다. zero-history 대상은 별도 fallback 경로를 사용하고 사용자 구성도 다르므로, cohort metric을 단순 가중치 없이 직접 비교하거나 history가 tactile 선호를 증명한다고 해석하면 안 된다.

---

## 13. 재개 절차 — tmux 사용

### 13.1 절대 하지 말아야 할 것

- `train_select.py --force` 사용 금지
- 완료 `.complete.json`, `.pt`, `.resume.pt` 삭제/이름 변경 금지
- `freeze_inputs.py`, `prepare_development_views.py`, `build_tactile_graph.py`, `lock_implementation.py` 재실행 금지
- `configs/protocol.json`, `configs/model_variants.json`, `common.py`, `models_exp20.py`, `train_select.py` 수정 금지
- 현재 state에서 공식 test target rows/metric을 수동으로 열어 보지 말 것
- Exp16 test metric이나 test candidate chunk를 selection에 넣지 말 것
- test 결과를 보고 LR, epoch, graph, candidate K, model 수식, cohort를 바꾸지 말 것

과학 설정이나 잠긴 metric/training 구현 변경이 정말 필요하면 Exp20을 덮어쓰지 말고 새 experiment/version을 만들어야 한다.

### 13.2 재개 전 재검증

```bash
cd /home/user/onsesang/material_span_grounding/experiments/20_tactile_recommender_spec_completion

pgrep -af 'train_select.py|evaluate_test.py|make_report.py'
tmux has-session -t exp20_continuation
cat artifacts/protocol_state.json
find artifacts/checkpoints -maxdepth 1 -name '*.complete.json' -printf '%f\n' | sort
tail -n 30 artifacts/events.jsonl
nvidia-smi
df -h .
```

예상 상태:

- relevant process 없음
- tmux session 없음
- state `implementation_frozen_before_validation`
- complete JSON 9개
- 마지막 resume epoch 2

### 13.3 webhook을 파일/명령 문자열에 직접 남기지 않는 방법

현재 shell에서 실제 URL을 대화로 다시 전달받아 숨김 입력하거나 안전한 secret mechanism으로 환경변수에 넣는다.

```bash
read -rsp 'Discord webhook: ' DISCORD_WEBHOOK_URL
echo
export DISCORD_WEBHOOK_URL

tmux set-environment -g DISCORD_WEBHOOK_URL "$DISCORD_WEBHOOK_URL"
```

webhook URL을 Markdown, JSON, Python source, 실행 로그, git 파일에 직접 쓰지 않는다.

### 13.4 tmux에서 남은 전체 pipeline 실행

```bash
tmux new-session -d -s exp20_continuation \
  "bash -lc 'set -o pipefail; cd /home/user/onsesang/material_span_grounding/experiments/20_tactile_recommender_spec_completion; { \
  /home/user/onsesang/miniconda3/envs/texture/bin/python train_select.py && \
  /home/user/onsesang/miniconda3/envs/texture/bin/python evaluate_test.py && \
  /home/user/onsesang/miniconda3/envs/texture/bin/python make_report.py && \
  /home/user/onsesang/miniconda3/envs/texture/bin/python sanity_checks.py && \
  /home/user/onsesang/miniconda3/envs/texture/bin/python -c \"from common import event; event(\\\"exp20_sanity_checks\\\", \\\"complete\\\")\"; \
  } 2>&1 | tee -a artifacts/continuation_runner.log'"

# tmux server global environment에는 secret을 계속 남기지 않는다.
tmux set-environment -gu DISCORD_WEBHOOK_URL
unset DISCORD_WEBHOOK_URL
```

이 명령은 `train_select.py`가 성공해야만 test로 넘어간다. 완료 9개 run은 skip하고 마지막 run의 epoch 3부터 재개한다.

### 13.5 진행 확인

```bash
tmux list-sessions
tmux capture-pane -pt exp20_continuation -S -200
tail -n 30 artifacts/continuation_runner.log
tail -n 30 artifacts/events.jsonl
tail -n 10 artifacts/notifications.jsonl
nvidia-smi
```

PyTorch의 non-writable NumPy tensor warning과 trusted local checkpoint에 대한 `torch.load(weights_only=False)` FutureWarning은 이전 실행에서도 발생했으며 run 실패 원인은 아니었다. 새로운 traceback, non-finite loss, OOM, hash mismatch는 별도로 조사해야 한다.

---

## 14. 남은 단계의 정확한 동작과 완료 조건

### Phase 1 — 마지막 validation run 완료

`train_select.py`가 다음을 수행한다.

1. 완료 9개 run skip
2. `I_VX_T_SHUFFLE`, LR .0003 resume load
3. epoch 3~20 수행; 5/10/15/20에서 validation
4. 해당 run `.pt`, `.complete.json` 생성
5. 전체 10개 run을 `artifacts/validation_results.csv`에 기록
6. variant별 LR/epoch 선택을 `artifacts/validation_selection.json`에 잠금
7. state를 `validation_locked_before_exp20_test`로 전이

성공 조건:

- complete JSON 정확히 10개
- `validation_selection.json.status == "validation_locked"`
- `model_selections`가 `I`, `I_T`, `I_VX`, `I_VX_T`, `I_VX_T_SHUFFLE` 모두 포함
- state가 `validation_locked_before_exp20_test`

### Phase 2 — locked post-hoc exploratory test

`evaluate_test.py`는 validation lock 없이는 실행되지 않는다.

1. state를 `exploratory_test_opened_no_retuning`으로 비가역 전이
2. 선택 checkpoint hash 검증
3. 다섯 variant를 같은 전체 test target/catalog에서 exact rank 평가
4. 각 variant per-user parquet 저장
5. 아래 paired contrast 계산
   - `primary_I_VX_T_minus_I_VX`
   - `aligned_tactile_minus_shuffle`
   - `tactile_ablation_I_T_minus_I`
6. `artifacts/test_results.json` 저장
7. state를 `complete_locked_posthoc_exploratory`로 전이

예정 output:

```text
artifacts/test_I_per_user.parquet
artifacts/test_I_T_per_user.parquet
artifacts/test_I_VX_per_user.parquet
artifacts/test_I_VX_T_per_user.parquet
artifacts/test_I_VX_T_SHUFFLE_per_user.parquet
artifacts/test_results.json
```

per-user 파일이 완전하게 존재하면 재실행 시 재사용할 수 있도록 구현돼 있다. 부분 파일을 완전한 파일로 오판하지 않도록 rows/variant/hash와 최종 sanity를 반드시 확인한다.

### Phase 3 — 최종 report

`make_report.py` 예정 output:

```text
notion/EXP20_TACTILE_RECOMMENDER_SPEC_COMPLETION_REPORT.md
artifacts/report_manifest.json
```

report는 validation selection, test metrics, paired contrasts, lock/hash, tactile graph provenance와 한계를 포함한다. 결과가 음수/null이어도 숨기지 않는다.

### Phase 4 — sanity checks

`sanity_checks.py`는 다음을 검사한다.

- final protocol state
- 5개 validation selection 존재
- 5개 test result 존재
- confirmatory flag가 false
- per-user 파일 hash 일치
- test target과 row 수 및 `(uid, iid)` 순서 일치
- rank가 모두 양수
- variant column 일치
- primary contrast 존재
- 최종 report 존재

최종 출력은 다음이어야 한다.

```text
Exp20 sanity checks passed
```

---

## 15. 최종 완료 판정 체크리스트

다음 조건을 모두 만족하기 전에는 “실험 완료”라고 보고하지 않는다.

- [ ] 마지막 `I_VX_T_SHUFFLE`, LR .0003 run epoch 20 완료
- [ ] complete JSON 10개
- [ ] `artifacts/validation_results.csv` 생성
- [ ] `artifacts/validation_selection.json` status `validation_locked`
- [ ] state가 test 전 `validation_locked_before_exp20_test`로 전이
- [ ] 동일 test universe에서 5개 variant exact 평가 완료
- [ ] per-user test parquet 5개 생성 및 hash/row/order 검증
- [ ] paired contrast 3개 생성
- [ ] `artifacts/test_results.json` 생성
- [ ] state `complete_locked_posthoc_exploratory`
- [ ] 최종 Markdown report 생성
- [ ] `artifacts/report_manifest.json` 생성
- [ ] `sanity_checks.py` 통과
- [ ] Discord 각 주요 단계 알림 성공 여부 확인
- [ ] 최종 해석에서 post-hoc exploratory / retrieval bottleneck / human ground-truth 한계를 명시

---

## 16. 재개 후 특히 점검해야 할 미충족 범위

Exp20 현재 구현의 핵심 Track A는 true in-model tactile modality의 general recommendation 비교에 집중한다. 원래 전체 사전등록에는 global/category-local tactile profile reranking, explicit tactile query의 동일 candidate-pool 비교, prospective human Track B, 미래 temporal Track C, reliable 8-class sensitivity와 bootstrap CI 등 더 넓은 항목이 있다.

현재 `train_select.py` → `evaluate_test.py` → `make_report.py` pipeline이 자동으로 직접 완결하는 범위와 `PREREGISTRATION.md` 전체 요구가 완전히 동일하다고 가정하면 안 된다. 최종 general recommendation pipeline을 먼저 잠금 상태 그대로 완료한 뒤, 아래 항목을 artifact 기반으로 audit해야 한다.

- primary paired bootstrap 1,000회와 95% CI가 최종 산출물에 실제 포함되는가
- tactile-support/cold-target/outside-family 등 사전등록 cohort가 모두 생성되는가
- global/category-local 8개 profile과 validation-only alpha 선택이 구현됐는가
- same candidate pool의 explicit tactile RQ3 비교가 Exp20 산출물에 포함되는가
- reliable 8-class sensitivity 및 robustness seed가 수행됐는가
- candidate retrieval failure와 reranking failure가 분리 보고되는가
- recommendation score breakdown 요구가 충족되는가
- prospective human/future temporal track은 실제 데이터가 없으면 명확히 pending/N/A로 남는가

이 audit에서 미구현 항목을 발견해도 이미 열린 Track A 결과를 보고 기존 locked run을 수정하면 안 된다. 일반 pipeline을 완료·보존한 다음, 새로운 version/보조 experiment 또는 명시적으로 분리된 후속 분석으로 처리하고 claim boundary를 유지한다.

---

## 17. 주요 artifact 목록

### 과학 설계/코드

- `PREREGISTRATION.md`
- `configs/protocol.json`
- `configs/model_variants.json`
- `common.py`
- `models_exp20.py`
- `train_select.py`
- `evaluate_test.py`
- `make_report.py`
- `sanity_checks.py`

### 동결/감사

- `artifacts/input_manifest.json`
- `artifacts/development_views_manifest.json`
- `artifacts/tactile_graph_report.json`
- `artifacts/synthetic_dry_run.json`
- `artifacts/implementation_lock.json`
- `artifacts/protocol_state.json`
- `artifacts/events.jsonl`
- `artifacts/notifications.jsonl`
- `artifacts/continuation_runner.log`

### 데이터/graph

- `data/train_events.parquet`
- `data/validation_events.parquet`
- `data/validation_targets.parquet`
- `data/tactile_feat_14.npy`
- `data/tactile_feat_14_shuffled.npy`
- `data/tactile_available.npy`
- `data/tactile_adj_40_True.pt`
- `artifacts/tactile_shuffle_mapping.parquet`

### checkpoints

- 완료 run: `artifacts/checkpoints/*.complete.json`, 대응 best `.pt`, resume `.pt`
- 중단 run: `artifacts/checkpoints/I_VX_T_SHUFFLE_lr0.0003_seed20260904.resume.pt`

---

## 18. 마지막 인계 요약

Exp20은 입력 동결, train-only split, full-catalog frozen Last2 14D feature, 고정 tactile kNN graph, synthetic dry run, implementation lock까지 끝났다. 모델 5개 × LR 2개의 validation grid 중 9개 run이 완료됐다. 현재 validation에서는 generic multimodal `I_VX`가 `I_VX_T`보다 약간 높고 shuffled tactile control도 aligned tactile과 거의 같지만, 이는 test가 아닌 잠정 validation 관찰이다.

마지막 `I_VX_T_SHUFFLE`, LR .0003은 epoch 2까지 model/optimizer/RNG를 포함한 10.89 GB resume checkpoint로 안전하게 저장됐다. 실행 프로세스와 tmux는 모두 종료돼 있다. 새 세션은 frozen 파일을 고치거나 `--force`를 쓰지 말고 tmux에서 `train_select.py`를 재개해야 한다. validation selection이 모두 잠긴 뒤에만 공식 test를 열고, 결과는 반드시 재사용 test에 대한 locked post-hoc exploratory로 보고해야 한다.
