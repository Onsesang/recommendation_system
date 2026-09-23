# 온세상: Last2 촉각 에이전트 데모

Amazon Fashion 전체 catalog에 미리 계산된 FashionCLIP Last2 14D 확률을 사용해,
사용자가 말한 의류 종류와 촉감으로 상품을 정렬하는 독립 Streamlit 데모다. 기존
실험 파일, checkpoint, cache, artifact는 읽기만 하며 재학습이나 이미지 inference를
실행하지 않는다.

## 실행

repository root에서 다음을 실행한다.

```bash
cd /home/user/onsesang/material_span_grounding
streamlit run demo_agent/app.py
```

현재 workspace의 검증된 환경을 명시적으로 사용하려면:

```bash
/home/user/onsesang/miniconda3/envs/texture/bin/streamlit run demo_agent/app.py
```

필요 package는 `demo_agent/requirements.txt`에 있다. 기본 Streamlit 주소는
`http://localhost:8501`이다.

## 기존 artifact 재사용

- Last2 cache: `experiments/16_strong_recommender_tactile/artifacts/product_tactile_profiles.parquet`
- 상품 metadata: `experiments/16_strong_recommender_tactile/data/item_metadata.parquet`
- checkpoint provenance: `experiments/12_class_multilabel_fashionclip_ft/models/fashionclip_last2.pt`
- checkpoint SHA-256: `073b542a9d6bd4450aa1f48596c756cc0812b1b5d914945e8f94f7c3fda1934a`

실행 중 checkpoint 자체를 메모리에 올리지는 않는다. 공식 checkpoint로 이미 만든
825,840행 cache를 직접 읽기 때문에 매 요청 inference가 없다.

## Agent와 ranking

`tactile_parser.py`는 저장소 `recommendation_api.tactile_agent.CATEGORY_PATTERNS`의
기존 broad category heuristic을 재사용하고, 셔츠·자켓·가디건처럼 UI에 필요한 세부
종류만 title keyword로 좁힌다. 한국어/영어 동의어와 근접 부정 표현을 deterministic하게
14개 Last2 class로 변환한다. 세부 title 후보가 설정값보다 적으면 해당 broad category로
완화하고 응답과 화면에 이를 표시한다.

카테고리가 없는 후속 문장은 이전 조건에 합쳐진다. 예를 들어 `부드럽고 얇은 셔츠`
다음의 `조금 더 따뜻한 걸로`는 `shirt + soft + thin + warm`이 된다. 옷 종류와 촉감을
함께 새로 말하면 이전 조건을 교체한다.

각 후보 `i`의 점수는 다음과 같다.

```text
score(i) = [Σ positive_weight × P_i(class)
          + Σ negative_weight × (1 - P_i(class))]
           / Σ all_weights
```

가중치는 모두 `config.json`에서 조정한다. 점수가 같을 때만 기존 `train_count` 내림차순,
ASIN 오름차순으로 결정한다. 매 요청은 NumPy 배열 연산으로 전체 후보를 계산하며 상품별
Python loop로 825K개를 순회하지 않는다.

추천 이유는 LLM 문장이 아니라 `reason_evidence`에 저장한 실제 원본 Last2 확률에서만
만든다. `validate_reason()`이 원본 matrix와 수치 및 표시 문자열을 다시 비교하며 불일치하면
응답 생성을 실패시킨다. 화면에는 이 값이 사람이 만진 물리적 정답이 아닌 이미지 기반
예측임을 명시한다.

`TactileAgent`는 검증된 structured-query를 반환하는 외부 parser를 주입할 수 있다.
외부 parser가 없거나, 실패하거나, 허용되지 않은 class/category를 반환하면 동일한
deterministic parser로 failover한다. 현재 기본 실행은 외부 키가 없어도 항상 동작하는
deterministic 모드이며 상품 ranking 경로는 parser 종류와 무관하게 동일하다.

## 테스트와 offline evaluation

```bash
pytest -q demo_agent/tests
python -m demo_agent.offline_eval
```

offline evaluator는 요구된 다섯 문장을 실제 825,840개 cache에 실행해 parsing,
category 후보 수, 0개가 아닌 결과, 이미지 URL, 추천 이유 수치 검증을 보고한다.
기본적으로 stdout에만 쓰며, 결과를 보존하려면 `demo_agent/` 아래 경로만 지정할 수 있다.

```bash
python -m demo_agent.offline_eval --output demo_agent/artifacts/offline_eval.json
```

## 알려진 한계

- Last2 값은 상품 이미지 기반 모델 예측이며 실제 촉감 측정값이 아니다.
- Amazon metadata category는 title keyword로 만든 미검증 heuristic이라 세부 종류가
  잘못 분류될 수 있다.
- 상품 이미지 URL은 Amazon 원격 CDN 상태에 영향을 받는다. URL이 없는 행에는 로컬
  placeholder를 표시한다.
- 이번 데모는 명시적 촉감 query용이며 사용자 history 개인화나 구매 선호 추론을 하지 않는다.

기존 로그인·사용자 메모리 에이전트 조사와 안전한 연결 경계는
`demo_agent/EXISTING_AGENT_INTEGRATION.md`에 정리했다.
