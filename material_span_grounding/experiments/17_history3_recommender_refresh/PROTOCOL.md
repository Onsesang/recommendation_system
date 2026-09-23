# History>=3 추천 실험 사전 프로토콜

## 연구 질문

평가 시점 이전 상호작용이 3개 이상인 사용자에서 강한 순차 추천 모델과 Last2 기반 촉각 후처리 순서 조정의 효과를 비교한다. 학습 데이터, 전체 parent 상품 catalog, 공식 split과 ID mapping은 Experiment 16과 동일하게 유지하며 평가 집단만 바꾼다.

## 고정 규칙

- 원본: Amazon Reviews'23 `Amazon_Fashion`, revision `2aa726ef444e72c6a1364c4baa0bcdfb1de55db6`, 공식 `0core/last_out` split.
- Validation history: train event만. Test history: train과 시간상 앞선 validation event.
- 평가 대상: 해당 평가 시점의 `history_length >= 3`. 학습 사용자는 줄이지 않는다.
- 전체 parent catalog 825,869개를 유지한다. 이전에 본 상품은 모든 모델에서 제외한다.
- 같은 점수는 `parent_asin` 오름차순(현재 mapping의 `iid` 오름차순)으로 결정한다.
- Validation만 모델, checkpoint, K, tactile profile, class subset, alpha 선택에 쓴다. 이 선택을 JSON으로 고정한 다음에만 test 결과를 계산한다.
- 모델 순서 tie-break: Popularity, BPR-MF, SASRec, eSASRec, BERT4Rec, GRU4Rec, SMORE-derived.
- 모델 선택: NDCG@10, HR@10, MRR@10, 위 사전 모델 순서.
- K grid: 100, 300, 500, 1000, 3000. 선택 모델의 validation recall이 0.80 이상인 가장 작은 K, 없으면 3000.
- alpha grid: 0, 0.05, ..., 1.00. Validation NDCG@10 최대, 동률이면 더 작은 alpha, 14 classes, all_history 순.
- tactile profile: 평가 이전 category-local mean. `all_history`와 `rating_ge_4`, 14 classes와 기존 reliable 8 classes를 비교한다.
- paired bootstrap: 사용자 단위 1,000회, seed 20260904.
- seed: 20260904.

## 모델과 공정한 탐색 예산

기존 BPR-MF, SASRec, eSASRec, SMORE-derived는 Experiment 16에 남은 두 learning rate(0.001, 0.0003)의 checkpoint를 history>=3 validation 결과로 다시 선택한다. Popularity는 train count만 사용한다.

새 BERT4Rec과 GRU4Rec은 기존 sequential model과 같은 dimension 64, 최대 sequence length 50, batch size 256, learning rates `{0.001, 0.0003}`, 최대 50 epochs, 5 epoch마다 validation, patience 5 validation checks를 사용한다. 두 모델 모두 전체 catalog에서 뽑은 64개 sampled negatives를 사용한다. BERT4Rec은 15% masked-item 학습과 bidirectional Transformer 2 layers/2 heads/dropout 0.2, GRU4Rec은 one-layer GRU/dropout 0.2 next-item 학습을 사용한다. Test를 읽어 설정을 바꾸지 않는다.

## 재사용 및 금지

Experiment 16은 read-only source다. 원본 파일을 복사·수정하지 않고 절대경로로 읽으며, 핵심 재사용 입력의 SHA-256을 `manifests/reuse_manifest.csv`에 저장한다. Qwen labeling, Last2 재학습, 전체 이미지 다운로드, 825k Last2 inference는 하지 않는다.

## Test 개방 조건

`artifacts/selected_backbone.json`에 backbone/checkpoint/K가 기록되고 그 파일과 validation 표의 SHA-256이 `artifacts/validation_lock.json`에 고정된 뒤에만 test 평가 stage가 실행될 수 있다.

