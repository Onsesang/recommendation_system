# vLLM 전환 및 전체 재실행 프로토콜

> 동결일: 2026-08-13  
> 범위: 기존 Qwen 추출·검증 산출물 전체의 vLLM 재실행  
> protected test: 미사용

## 결정

기존 Hugging Face Transformers 직접 추론 결과는 비교 기준으로 그대로 보존한다. 새 결과는
`data/vllm/` 아래에만 기록하며 서로 다른 백엔드의 span이나 semantic 판단을 섞지 않는다.

## 고정 실행 조건

| 항목 | 값 |
|---|---|
| 모델 | Qwen/Qwen3-VL-8B-Instruct |
| 백엔드 | vLLM 0.27.1 |
| 환경 | Conda `material_vllm312`, Python 3.12 |
| 양자화 | BitsAndBytes in-flight 4-bit |
| dtype | bfloat16 |
| decoding | temperature 0, seed 42 |
| GPU | NVIDIA GeForce RTX 3060 12GB |
| extraction retry | 최대 2회 |
| verification retry | 최대 2회 |
| 진행 알림 | 전체 작업량 기준 10% 단위 Discord webhook |

이 머신에서는 vLLM V2 runner의 UVA 초기화가 지원되지 않아 vLLM V1 engine runner를
사용한다. 이는 Hugging Face `model.generate`로 되돌아간다는 뜻이 아니라, vLLM 0.27.1의
안정 호환 runner를 사용하는 것이다.

## 재실행 범위

1. pilot 1,000리뷰 v1 추출 및 semantic verification
2. pilot 1,000리뷰 Recall v2 두-lens 추출 및 semantic verification
3. dense 100상품×5사용자, 500리뷰 Recall v2 추출 및 semantic verification
4. dense 500상품, 4,158리뷰 Recall v2 추출 및 semantic verification
5. 기존 Transformers 결과와 span overlap·공통 span 판정 일치율 비교

## 입력 및 prompt SHA-256

| 대상 | SHA-256 |
|---|---|
| pilot 1,000 | `5119c99f511abc15cc450d7df92de1a1142ca1b4251cc9093b00507f8560d113` |
| dense 100×5 | `01fab7cb86544594e79912a717fb6a36d3fda64961f4435354a8d0d2816d192d` |
| dense 500 | `ac2b3b6e061dacaaefcf601532496e291ee4edb022ff194a99cf755f365ab3d8` |
| extraction v1 | `9a174496b7720199cbdeea3d751f932b54ff90f4e9265e0afa6f6699c65e911b` |
| Recall surface | `362acaa7641b5486d19b260d8add1e055be3cabeb2955c7e1d03f6425361feb3` |
| Recall behavior | `520e807e615db4f268222a73c6aeea98b0a689234291a25a4efff22f517f1869` |
| semantic verifier | `eff1bf1bc2a3fb9a4eb98ec5ca8807473d8f50325653977d18e87840de6d09e1` |

## 진행률 정의

- 0–5%: pilot v1 추출
- 5–10%: pilot v1 의미 검증
- 10–70%: 세 데이터셋 Recall v2 추출 task 수 비례
- 70–100%: 세 데이터셋 semantic 후보 수 비례

각 임계값은 `data/vllm/progress.json`에 기록하므로 프로세스를 재시작해도 같은 10% 알림을
중복 발송하지 않는다. 각 JSONL은 batch마다 fsync하고, 재실행 시 성공한 항목을 이어서 쓴다.

