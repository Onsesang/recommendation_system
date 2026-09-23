# Dense-500 v2.1 상품 소재 target 생성 결과

> 생성일: 2026-08-13  
> 목적: 추천 프로토타입용 상품 소재 target 구축  
> 범위: **target 생성만 수행했으며 M0/M1 재평가는 건너뜀**

## 결과 요약

| 항목 | 결과 |
|---|---:|
| 입력 리뷰 | 4,158 |
| 입력 상품 | 500 |
| v2.1 semantic accepted claim | 4,527 |
| target 생성 상품 | 495 |
| target 미생성 상품 | 5 |
| target 차원 | 384 |
| 다중 사용자 근거 상품 | 470 |
| 상품별 근거 사용자 범위 | 1~9명 |

target 미생성 상품은 승인된 소재 claim이 없는 다음 5개다.

- `B000Y0JDU4`
- `B00681PVHC`
- `B0140VPCKC`
- `B017GPFFHO`
- `B01CZT4XJC`

## target 생성 방식

1. Recall v2.1의 schema 검증 성공 span 중 semantic accepted 4,527개만 사용한다.
2. `BAAI/bge-small-en-v1.5`로 각 소재 claim을 384차원 단위 벡터로 변환한다.
3. 같은 사용자의 동일 정규화 claim을 중복 제거한다.
4. 사용자 안에서 claim 벡터 평균을 구하고 L2 정규화한다.
5. 한 사용자가 많은 리뷰를 썼더라도 과대 반영되지 않도록, 상품 안에서 사용자 벡터를
   동일 가중치로 평균하고 다시 L2 정규화한다.

상품별 근거 사용자 수 분포는 다음과 같다.

| 사용자 수 | 상품 수 |
|---:|---:|
| 1 | 25 |
| 2 | 84 |
| 3 | 117 |
| 4 | 94 |
| 5 | 84 |
| 6 | 56 |
| 7 | 20 |
| 8 | 11 |
| 9 | 4 |

## 추천 프로토타입용 산출물

- `data/derived/dense_500_v2_1_targets/product_material_targets.npz`
  - `asins`: 벡터 행에 대응하는 정렬된 ASIN 배열
  - `material`: `(495, 384)` float32 단위 벡터
- `data/derived/dense_500_v2_1_targets/products.json`
  - ASIN, `vector_index`, 제목, 카테고리, 리뷰·사용자·claim 통계
- `data/derived/dense_500_v2_1_targets/evidence.jsonl`
  - 추천 설명에 사용할 상품별 claim·원문 quote·review/span 근거
  - 원시 사용자 ID는 포함하지 않음
- `data/derived/dense_500_v2_1_targets/manifest.json`
  - 입력 provenance, 생성 공식, 개수, SHA-256, 누락 상품 목록
- `data/derived/dense_500_v2_1_targets/claim_embeddings.npz`
  - 동일 입력 재생성 시 사용할 claim embedding cache

핵심 파일 SHA-256:

- `products.json`: `f7b0b094b9c769db508f67257836fbf04c715dcfeb3bfec7125a566d2566a026`
- `product_material_targets.npz`: `0b3a20a01a987814edc2aba03b0200f55ebdaf164db98dfa2ee29cda0667fca9`
- `evidence.jsonl`: `2255278a7fb69a3f5e4cb2d4ffb45b2d2664ea89dff1851d853681840c50a575`

## 검증 결과

- 벡터 shape: `(495, 384)`
- 모든 값 finite
- L2 norm 최대 오차: `1.1920928955078125e-07`
- `products.json`, NPZ의 `asins`, `evidence.jsonl` 순서 일치
- target 미생성 5상품 목록 일치
- 공개 JSON/JSONL 산출물에 원시 사용자 ID 없음
- 전체 단위 테스트 20건 통과

재현 명령:

```bash
/home/user/onsesang/miniconda3/envs/texture/bin/python run.py product-targets
```

## 해석과 사용 제한

이 target은 Qwen v2.1 pseudo-label에 Codex AI 개발 검수 규칙을 적용해 얻은 결과이며,
독립적인 사람 gold가 아니다. 추천 프로토타입의 상품 표현과 근거 설명에는 바로 사용할 수
있지만, 전체 리뷰에서 집계했기 때문에 시간순 추천 평가의 test 시점 이후 리뷰가 포함될 수
있다. 따라서 현재 파일은 **프로토타입용**으로 사용하고, 향후 성능 수치를 보고할 때는 각
평가 시점 이전 리뷰만으로 target을 다시 생성해 시간 누출을 차단해야 한다.

M0/M1 재평가는 이번 실행에 포함하지 않았다.
