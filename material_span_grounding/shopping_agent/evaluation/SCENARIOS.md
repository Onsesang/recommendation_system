# 시연 시나리오 파일 작성법

`demo_scenarios.json`은 시연 대화 세트이자 자동 판정 기준이다. 코드를 고치지 않고 이 파일만
수정하면 된다. 수정한 뒤에는 API 호출 없이 형식부터 검사한다.

```bash
python -m shopping_agent.evaluation.tool_agent_scenarios --check
```

## 구조

```json
{
  "scenarios": [
    {
      "id": "S3",
      "title": "촉감 검색 → 담기",
      "turns": [
        {
          "message": "안 까끌하고 얇은 여름 원피스 찾아줘",
          "note": "dress, want=thin, avoid=rough.",
          "expect": {"search": {"category": ["dress"], "want": ["thin"], "avoid": ["rough"]}}
        },
        {
          "message": "2번 장바구니에 담아줘",
          "note": "직전 검색 2번을 담는다.",
          "expect": {"refers": {"tool": "add_to_cart", "positions": [2]}, "cart_updated": true}
        }
      ]
    }
  ]
}
```

- 한 시나리오는 한 대화 세션이다. 턴은 순서대로 같은 세션에 보내며, 시나리오마다 새 사용자로 시작한다.
- 시연용 30문장 세트는 `demo_30.json`(`--scenarios shopping_agent/evaluation/demo_30.json`), 회귀용 48턴은 `demo_scenarios.json`이다.
- `criterion`(선택)은 HTML 요약에서 이 턴을 어느 판단 기준으로 셀지 정한다: `search refers cart no_tools forbid other`. 없으면 `expect`의 첫 키를 따른다.
- `note`는 자동 판정에 쓰지 않는다. 검수표에 "기대"로 표시되어 사람이 판정할 때 기준이 된다.
- `expect`를 비워 두면(`{}`) 공통 규칙만 검사한다.

## expect 키

| 키 | 값 | 판정 |
|---|---|---|
| `no_tools` | `true` | 도구를 부르지 않고 상품도 반환하지 않아야 한다 (인사, 범위 밖) |
| `tools` | `["view_cart"]` | 나열한 도구가 모두 호출되어야 한다 |
| `search` | 아래 표 | `search_products`의 마지막 호출 인자를 검사한다 |
| `refers` | `{"tool": "add_to_cart", "positions": [2]}` | 직전 검색 목록의 해당 번호 상품을 정확히 가리켜야 한다. 도구는 `get_product_detail`, `compare_products`, `add_to_cart`. `remove_from_cart`도 쓸 수 있다(보여준 목록 번호 기준). 담기·빼기는 `"quantity": 2`로 수량도 검사한다(빼기에서 `null`은 전부) |
| `cart_updated` | `true` / `false` | 이번 턴에 장바구니가 바뀌었는지 |
| `forbid` | `["\\d[\\d,]*\\s*원"]` | 답변에 이 정규식과 맞는 표현이 있으면 실패. 도구에 없는 가격·사이즈·재고를 지어내는지 확인할 때 쓴다 |

`search` 안의 키:

| 키 | 예 | 판정 |
|---|---|---|
| `category` | `["sweater", "cardigan"]` | 이 중 하나여야 한다. 옷 종류가 불분명하면 `[null]` |
| `want` | `["thin"]` | 모두 포함해야 한다 (더 있어도 통과) |
| `avoid` | `["rough"]` | 모두 포함해야 한다 |
| `not_want` | `["thin"]` | `want`에 있으면 실패 (조건 수정 턴에서 이전 조건이 남았는지) |
| `either` | `[{"avoid": ["thick"]}, {"want": ["thin"]}]` | 나열한 해석 중 하나를 만족하면 통과 ("덜 두꺼운"처럼 여러 해석이 맞는 표현) |
| `keyword` | `"white"` 또는 `["navy", "dark blue"]` | 영어 keywords에 들어 있어야 한다. 목록이면 그중 하나 (부분 일치, 대소문자 무시) |
| `unsupported` | `true` | 비침·통기성·보풀처럼 표현 못 하는 조건을 `unsupported_concepts`에 넣어야 한다 |

촉감 값: `soft firm smooth rough non_elastic elastic thin thick flexible stiff warm cool spongy crisp`

옷 종류: `shirt tshirt sweater jacket coat pants jeans dress skirt hoodie cardigan top outerwear underwear sleepwear swimwear` 등
(`demo_agent/models.py`의 `SUPPORTED_CATEGORIES`)

## 모든 턴에 적용되는 공통 규칙

- OpenAI 도구 루프가 실패해 로컬 라우터로 넘어가면 실패
- 답변에 마크다운(`**`, `#`, 목록, 표)이 있으면 실패
- 리뷰 근거가 없는 상품인데 "리뷰"를 근거처럼 말하면 실패. 문장 단위로 보며, 부정("리뷰 근거는 없어요")이나 확인 제안("리뷰 근거가 있는지 볼까요?")이 있는 문장은 통과
- 보여준 적 없는 상품을 상세·비교·담기 대상으로 쓰면 실패
- 답변에 상품 ID(B0…)가 있으면 경고 (스크린리더가 열 글자를 읽는다)
- 5문장 또는 300자를 넘으면 경고 (실패는 아님, 스크린리더 길이 기준)

## 실행과 결과

```bash
# 모델 비교, 설정마다 2회 반복
python -m shopping_agent.evaluation.tool_agent_scenarios \
    --models gpt-5.4-mini gpt-5.4-nano --reasoning-efforts low --repeats 2

# 일부 시나리오만
python -m shopping_agent.evaluation.tool_agent_scenarios --only S3 S5
```

결과는 `evaluation/results/<시각>/`에 생긴다.

- `review.html`: 대화형 검수표. 설정별 답변, 도구 인자, 검색 상위 3개와 지칭·담기 대상 상품 사진(초록=기대 상품, 빨강=다른 상품),
  턴마다 OpenAI 요청·응답 원문(응답 ID, 모델 스냅샷, function_call, 도구가 돌려준 값, 토큰). 사진은 data URI로 들어가 파일 하나로 열린다
  (썸네일 캐시 `results/.image_cache/`). 결론 문단은 `--render <run>/results.json --note note.txt`로 맨 위에 넣는다
- `review.md`: 턴마다 설정별 답변, 도구 인자, 상위 3개 이미지를 나란히 보여주는 검수표
- `review.csv`: 같은 내용을 한 행씩. 판정 칸(조건해석, 지칭, 근거정직성, 말투 1~5, 메모)을 채운다
- `results.json`: 원본 데이터

## 사람 검수 UI

```bash
python -m shopping_agent.evaluation.review_app shopping_agent/evaluation/results/<시각>/results.json
# 브라우저에서 http://127.0.0.1:8890 (다른 포트: --port 8891)
```

한 페이지 = 한 사용자 발화. 판정은 누르는 즉시 결과 폴더의 `judgments.json`에 저장된다.

- **추천 검수**(기본 탭): 검색이 있는 턴만 나온다. 에이전트가 만든 검색 조건(설정별 옷 종류·원함·피함·키워드)과,
  모든 설정이 추천한 상위 5개 상품을 중복 없이 모아 보여 준다. 상품마다 맞음 / 애매 / 안 맞음과 메모.
  요약에서 설정별 상위 3개·5개 정확도(엄격: 맞음만, 관대: 애매 0.5점)와 안 맞음 목록을 본다.
- **대화 검수**: 답변마다 조건 해석·지칭·근거 정직성 O / X / 해당 없음과 메모. 도구가 가리킨 상품을
  "화면 N번"으로 풀어 보여 주고, 직전 목록에 없는 상품이면 빨간색으로 표시한다.
- 공통: ← → 버튼·방향키 이동, 진행률, 필터, 턴 바로가기, 블라인드(모델 이름 숨김), 판정 기준, 요약,
  CSV 내보내기(탭별), 이미지 확대.

## 검색 순위 설정 비교 (LLM 없이)

```bash
python -m shopping_agent.evaluation.ranking_variants \
    --source shopping_agent/evaluation/results/<회귀 실행>/results.json \
    --judgments shopping_agent/evaluation/results/<이전 검수>/judgments.json
# A/B 비교 검수 (상위 3개가 달라진 턴만, 설정 이름은 가려짐)
python -m shopping_agent.evaluation.pairwise_app <위 결과>/results.json --baseline baseline --candidates texture_words color
# 브라우저에서 http://127.0.0.1:8892 → 1 = A, 2 = 비슷함, 3 = B
```

- 설정 후보는 `evaluation/ranking_variants.json`. 회귀 실행에서 모델이 만든 검색 조건을 그대로 재계산하므로 설정 효과만 비교된다.
- 자동 지표(이전 판정 기준 정확도, 색상 일치, 촉감 충족)를 먼저 보고, 사람은 A/B 한 번씩만 고른다. 결과는 `pairwise_judgments.json`.
