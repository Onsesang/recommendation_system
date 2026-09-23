# Material Span Grounding

리뷰 원문에서 소재·질감에 관한 **exact evidence span**을 Qwen으로 추출하는
독립 프로젝트다. 기존 `/home/user/onsesang/texture_project`와
`/home/user/onsesang/seoyoung`은 읽기 전용 입력으로만 사용한다.

현재는 사람 검수까지 통과했으며, GNN 이전의 M0/M1 단순 검색 실험과 product-dense
후속 평가까지 구현돼 있다.

```text
리뷰 → Qwen exact span 추출 → 코드 원문 일치 검사
     → Qwen 소재 여부·scope·극성 semantic verification
```

Recall v2는 v1 결과를 버리지 않고 두 개의 독립 탐색 lens를 추가한다.

```text
v1 exact spans
  ∪ surface/use lens
  ∪ behavior/care lens
  → exact quote·포함 중복 제거 → 새 후보만 semantic verification
```

채택 claim은 동일 사용자 중복을 제거하고 사용자별 1표로 상품 target embedding을 만든다.

## 구조

```text
configs/                       실행 설정
prompts/                       버전이 고정된 Qwen 프롬프트
material_span/                 Python 패키지
data/input/                    결정적 pilot 표본
data/output/                   원시 생성과 검증된 span
data/manifests/                입력·프롬프트 hash
experiments/01_span_extraction/results/
experiments/02_semantic_verification/results/
audit_app/                      이미지 기반 사람 검수 HTML·백엔드
recommendation_api/             상품 target 조회·M0/M1 검색 백엔드
offline_eval/                   시간순 추천 정량 평가·cohort·bootstrap
notion/                        Notion import용 Markdown
tests/                         데이터 계약 단위 테스트
run.py                         통합 실행 진입점
```

## 실행

```bash
conda run -n texture python run.py sample --limit 1000
conda run -n texture python run.py extract --batch-size 8
conda run -n texture python run.py report
conda run -n texture python run.py verify-prepare
conda run -n texture python run.py verify --batch-size 8
conda run -n texture python run.py verify-report
conda run -n texture python run.py recall-extract --output-root data/v2 --batch-size 6
conda run -n texture python run.py recall-verify-prepare --output-root data/v2
conda run -n texture python run.py recall-verify --output-root data/v2 --batch-size 8
conda run -n texture python run.py recall-report --output-root data/v2
conda run -n texture python run.py simple-m0-m1
conda run -n texture python run.py density --min-users 5 --max-reviews-per-product 5 --max-products 100 --output-root data/dense/simple_100x5
conda run -n texture python run.py dense-m0-m1 --root data/dense/simple_100x5/v2
conda run -n texture python run.py dense-m0-m1 --root data/dense/simple_100x5/v2 --augment-sparse
python -m audit_app.build_v2_manifest
./audit_app/start.sh
./recommendation_api/start.sh
conda run -n texture python -m offline_eval.cli all
```

추천 backend는 기본적으로 `http://127.0.0.1:8877`에서 실행되며 `/docs`에서 API 계약을
확인할 수 있다. 기존 검수 backend의 8765 포트와 분리되어 있다.

offline evaluator는 `data/recommendation_eval/temporal_v1`에 고정 candidate case,
baseline prediction, Recall/NDCG/MRR/TactileMatch와 cold-start 분석 결과를 생성한다.
외부 BPR/CF 모델은 `case_id`와 정렬된 `ranked_items` JSONL만 출력하면 같은 evaluator를
그대로 사용할 수 있다.

## Tactile-aware recommendation prototype

Recall v2.1에서 승인된 4,527개 claim으로 500상품 중 495상품의 review-grounded tactile
profile을 구축했다. 설명, concern, 비교, 대안, context-gated reranking과 Agent는 같은
profile/evidence contract를 공유한다.

```bash
./recommendation_api/start.sh
# http://127.0.0.1:8877/tactile-demo
/home/user/onsesang/miniconda3/envs/texture/bin/python -m offline_eval.tactile_system_eval
```

설계와 데이터 계약은 `docs/tactile/`, 정량 결과는
`data/recommendation_eval/tactile_v1/report.md`에 있다. 현재 target은 전체 선택 리뷰로
만든 프로토타입용이므로 시간순 추천 결과는 진단용이며, 독립 human gold 평가를 대체하지
않는다.

GPU가 보이는 셸에서 `extract`를 실행해야 한다. 결과 파일은 review 단위 JSONL이며
재실행 시 이미 완료된 `review_id`는 건너뛴다.

사람 검수 앱은 기본적으로 `http://127.0.0.1:8765`에서 실행된다. 원격 개발
환경에서는 8765 포트를 로컬로 포워딩한다. 검수 결과는
`audit_app/data/annotations.json`에 즉시 원자적으로 저장되고
`audit_app/data/human_semantic_audit_live.csv`로 자동 내보내진다.
