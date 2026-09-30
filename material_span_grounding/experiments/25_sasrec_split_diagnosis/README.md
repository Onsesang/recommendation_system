# Experiment 25: SASRec 후보 검색 진단 (정답 범위 · 데이터 자르는 방식)

SASRec의 첫 후보 검색(Recall@500)이 인기도 목록 수준에 머무는 원인을 찾는다.
결과 요약은 `results/report.html`에 있다. 수치 원본은 `results/*.json`과 `results/runs/*.json`이다.

## 결론

- **코드 문제가 아니다.** 같은 SASRec 클래스(exp16b에서 그대로 복사)를 MovieLens-1M에서 돌리면 논문과 같은 수치가 나온다.
  - negative 100개 샘플링 평가: HR@10 0.826 / NDCG@10 0.600 (논문 0.8245 / 0.5905)
- **원인은 데이터다.** 사용자 86%, 상품 60%가 리뷰 1개뿐이다. 5-core로 거르면 0건이 된다.
  - last_out test 정답의 75.5%는 학습 쌍에 한 번도 나오지 않는 상품(cold)이다.
  - cold 정답의 Recall@500은 모든 설정에서 0이다.
- **정답을 추천 가능 상품으로 제한해도 거의 변하지 않는다.** Recall@500은 3.48%에서 3.75%로 오른다.
- **어떻게 잘라도 SASRec R@500은 인기도보다 낫지 않다.** 세 방식(last_out / timestamp / user holdout)을 모두 비교했다.
- **exp24 학습 레시피(5 epoch마다 검증)는 epoch 1~4의 최고점을 놓친다.** 이 실험은 매 epoch 검증한다.
- **SASRec 250개 + 이미지 kNN 250개를 합치면 last_out 후보 recall이 41% 오른다.**

## 데이터를 자르는 세 가지 방식 (`scripts/protocols.py`)

| 이름 | 방식 | 출처 |
|---|---|---|
| `loo` | 사용자마다 마지막 이벤트를 test, 그 앞을 validation으로 뗌 | 공식 0core/last_out |
| `tsp` | 모든 사용자를 같은 시점 t1=2021-08-11, t2=2022-07-16에서 자름 (세로) | 공식 0core/timestamp |
| `uh` | 사용자를 나눔: 이력 4개 이상 사용자 중 30%는 test, 10%는 validation (가로) | 이 실험에서 만듦 |

`--data all`은 전체 이벤트로 학습한다. `--data rec`은 recommendable_fashion_v1 상품 이벤트로만 학습한다.
평가는 두 경우 모두 추천 가능 상품 정답을 추천 가능 상품 483,779개 안에서 순위 매긴다.

## 재현

필요한 데이터:
- `data/amazon_fashion_0core_last_out/*.csv`: `python -m shopping_agent.evaluation.recommendable_data`가 내려받는다.
- `data/amazon_fashion_0core_timestamp/*.csv`: 아래 명령으로 내려받고 `SHA256SUMS`로 확인한다.
- `experiments/16_strong_recommender_tactile/data/item_metadata.parquet`, `.../data/smore/image_feat.npy`
- `data/recommendable_fashion_v1/items.parquet`

```bash
cd material_span_grounding
for n in train valid test; do
  curl -sSL -o data/amazon_fashion_0core_timestamp/Amazon_Fashion.$n.csv \
    "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/2aa726ef444e72c6a1364c4baa0bcdfb1de55db6/benchmark/0core/timestamp/Amazon_Fashion.$n.csv?download=true"
done
sha256sum -c data/amazon_fashion_0core_timestamp/SHA256SUMS

cd experiments/25_sasrec_split_diagnosis
python scripts/prepare.py                      # cache/events.parquet
python scripts/split_stats.py                  # results/split_stats.json
python scripts/factor_stats.py                 # results/factor_stats.json
scripts/run_queue.sh logs/queue1.txt           # SASRec 37회 (RTX 3060에서 약 2시간)
python scripts/content_knn.py                  # 이미지 kNN 후보
python scripts/union_candidates.py
mkdir -p cache/ml1m && curl -sSL -o cache/ml1m/ml-1m.zip https://files.grouplens.org/datasets/movielens/ml-1m.zip \
  && (cd cache/ml1m && unzip -oq ml-1m.zip)
python scripts/sanity_ml1m.py                  # MovieLens-1M으로 구현 검증
python scripts/summarize.py && python scripts/make_report.py
```

`results/runs_recipe_v5/`는 exp24 레시피(5 epoch마다 검증)로 돌린 비교용 실행 1회다.
RTX 3060의 conda env `texture`(torch 2.5.1)에서 실행했다.
