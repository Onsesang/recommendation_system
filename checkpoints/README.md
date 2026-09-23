# 모델 체크포인트

학습된 모델 weight는 저장소 트리에 직접 두지 않고 **GitHub Releases**에 에셋으로 보관합니다.
(GitHub은 일반 git 파일당 100 MB, LFS 파일당 2 GB 한도가 있고 LFS 저장 용량은 유료입니다.)

## 받기

```bash
# 전체
./checkpoints/fetch_checkpoints.sh

# 특정 실험만
./checkpoints/fetch_checkpoints.sh 24_adaptive_tactile_recommendation
```

각 파일은 원래 경로(`material_span_grounding/experiments/.../*.pt`)로 복원되고, 마지막에
`sha256.txt`로 무결성이 검증됩니다. 저장소가 private이라 `gh auth login`이 필요합니다.

## 릴리스 구성

실험 하나당 릴리스 하나이며, 태그는 `ckpt-<실험디렉터리명>` 입니다.

| 릴리스 태그 | 내용 |
|---|---|
| `ckpt-12_class_multilabel_fashionclip_ft` | FashionCLIP 파인튜닝 변형(frozen / last1 / last2 / projection / full) |
| `ckpt-13_category_only_baseline` | 카테고리 단독 베이스라인 |
| `ckpt-16_recommendation_reranking` | BPR 리랭킹 |
| `ckpt-16_strong_recommender_tactile` | BPR / LightGCN / SASRec / eSASRec / SMORE (lr 1e-3, 3e-4) |
| `ckpt-17_history3_recommender_refresh` | BERT4Rec / GRU4Rec (lr 1e-3, 3e-4) |
| `ckpt-20_tactile_recommender_spec_completion` | I / I+T / I+VX / I+VX+T 및 SHUFFLE 대조군 |
| `ckpt-21_fabricvst_external` | FabricVST taxonomy (best / last, B 변형) |
| `ckpt-24_adaptive_tactile_recommendation` | R0 / R3 게이팅 변형 / R4 λ 스윕 / R5 hard-negative 비율 / R6 |
| `ckpt-data_derived` | image→tactile MLP (multimodal_catalog_v1) |

## 포함 범위

- **포함**: 추론·평가에 필요한 순수 weight `*.pt` (52개, 34.5 GB)
- **제외**: `*.resume.pt` — optimizer state를 포함한 학습 재개용 스냅샷(24개, 91 GB).
  학습을 이어서 돌릴 게 아니라면 필요 없습니다. 로컬 및 `outgoing/` 백업 번들에만 있습니다.
- **제외**: `*_adj_*.pt` — SMORE용 전처리 인접행렬 캐시(2.8 GB). 모델이 아니라
  파생 데이터이며 전처리 스크립트로 재생성됩니다.

## 2 GB 초과 파일

릴리스 에셋은 파일당 2 GB 한도가 있어, 아래 8개는 `.part00` / `.part01`로 분할되어 있습니다.
`fetch_checkpoints.sh`가 자동으로 병합하며, 수동으로는 `cat NAME.pt.part* > NAME.pt` 입니다.

- `16_strong_recommender_tactile`: `smore_lr0.001.pt`, `smore_lr0.0003.pt`
- `20_tactile_recommender_spec_completion`: `I_VX_*`, `I_VX_T_*`, `I_VX_T_SHUFFLE_*` (lr 1e-3, 3e-4)

## 파일

- `manifest.tsv` — `실험태그 / 바이트크기 / 저장소 기준 경로`
- `sha256.txt` — 전체 체크포인트의 sha256
- `fetch_checkpoints.sh` — 다운로드 + 분할 병합 + 검증
