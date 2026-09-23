# 촉감 선호 추출 소규모 Pilot

## 현재 상태

모델 추출 64/64건. Schema와 원문 인용 자동 검증 통과 62건. 사람 판정 0건.

**사람 검증 대기: 모델 출력의 semantic accuracy, F1, 사람 간 일치도는 아직 측정되지 않았다. 자동 검증 통과율을 정확도로 해석하지 않는다.**

## 표본 및 모델

실험 16의 validation 사용자에 해당하는 공식 train/validation 리뷰에서만 고른 64개 표본이다. 사용자 hash로 development 32개와 audit holdout 32개를 분리했다. 공식 test 리뷰는 사용하지 않았다. 표본 추출·prompt는 모델 출력 확인 전에 고정했다.

Opinion cue, negation, rare-property, unmarked stratum에서 hash로 표본을 골랐다. 부족한 stratum은 남은 pool에서 hash 순서로 보충했다. 층화 표본이므로 전체 데이터의 선호 비율을 추정하는 데 사용하면 안 된다.

Qwen/Qwen3-VL-32B-Instruct revision 0cfaf48183f594c314753d30a4c4974bc75f3ccb, 4-bit NF4 + BF16. 신규 preference pilot 추론만 수행했고 기존 v3 grounding이나 Last2 학습은 재실행하지 않았다.

## 출력의 의미

- property_phrase: 원문의 표현을 그대로 보존한 open-vocabulary 속성
- class_id: 기존 14-class와 연결 가능한 경우의 mapping; 나머지는 unmapped
- property_state: present / absent / uncertain / not_tactile
- attitude: like / dislike / unknown / mixed; 표현된 속성 상태에 대한 평가
- scope / condition: 부위와 상황; 명시되지 않으면 unknown
- evidence_quote: 제공된 문맥에서 그대로 복사한 근거

“I like that it is not thick”의 absent+like를 thick 선호 +1로 바로 바꾸지 않는다. 상황별 의견을 전역의 영구 선호로 전환하지 않는다. 현재는 annotation feasibility만 검사하며 signed user vector나 추천 score를 생성하지 않았다.

## 자동 출력 통계 (사람 검증 전)

```json
{
  "attitudes": {
    "dislike": 8,
    "unknown": 27,
    "like": 27
  },
  "property_states": {
    "present": 56,
    "absent": 6
  },
  "rejected": [
    {
      "sample_id": "7953f158b1d39ac828c9b05c",
      "validation_error": "non_verbatim_evidence"
    },
    {
      "sample_id": "3856a26cbb1cb22b7cd4e1c0",
      "validation_error": "non_verbatim_evidence"
    }
  ]
}
```

Rejected output도 raw_output과 함께 보존한다. 원문과 맞지 않는 인용을 임의로 수정해 통과 처리하지 않았다.

## Human audit 수행

가능하면 두 사람이 동일 표본을 독립 판정한다. 먼저 development를 검토하여 오류 유형을 정리한다. Prompt를 바꾸면 새 버전으로 기록하고, 기존 audit holdout의 사람 답안을 보며 조정하지 않는다.

웹 화면은 Qwen 답변을 보여주지 않는다. 각 annotator ID로 property, state, attitude, scope, condition, evidence를 입력한다. 원문 인용과 enum을 저장 전에 검증한다. 저장된 CSV는 annotations/<annotator_id>.csv이며 결과를 수정하면 해당 평가자의 같은 sample 행만 갱신한다.

```bash
cd /home/user/onsesang/material_span_grounding/experiments/18_tactile_preference_pilot
/home/user/onsesang/miniconda3/envs/texture/bin/streamlit run app.py --server.address 127.0.0.1 --server.port 8518
```

VS Code Remote SSH의 Ports에서 8518을 포워딩한 뒤 로컬 브라우저에서 http://localhost:8518 에 접속한다. 이 문서 생성 시 서버는 상시 실행하지 않았다.

CSV 입력도 가능하다. artifacts/human_annotation_template.csv를 복사해 작성하고 annotations/ 안에 저장한다. 평가자 ID, 모든 label field, verbatim evidence를 채워야 한다. 미완료 행은 invalid_human_rows로 보고되며 자동으로 사람 정답이 생성되지 않는다.

판정 후 분석:

```bash
/home/user/onsesang/miniconda3/envs/texture/bin/python pilot.py analyze
/home/user/onsesang/miniconda3/envs/texture/bin/python write_reports.py
```

분석은 development/holdout 및 평가자별 모델 일치율과 support, 두 사람 간 raw agreement/Cohen kappa를 계산한다. 합의된 adjudicated gold가 없으면 이를 확정 정확도로 보고하지 않는다. 동일 단일 라벨만 존재하여 kappa가 정의되지 않는 경우 null로 기록한다.

## 재현 순서

```bash
python pilot.py prepare
python pilot.py infer
python pilot.py analyze
python -m unittest -v test_pilot.py
python write_reports.py
```

prepare는 표본 및 빈 template을 다시 생성한다. infer는 기록된 sample ID를 건너뛰어 재개한다. 출력 실패도 완료된 추출 시도로 남는다. Prompt나 표본을 변경한 재실험은 기존 결과 파일을 재사용하지 않고 새 버전 폴더에서 수행해야 한다.
