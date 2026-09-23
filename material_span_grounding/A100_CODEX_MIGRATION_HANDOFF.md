# A100 Codex 환경·프로젝트·데이터 이관 실행 설계서

이 문서는 **A100 서버에서 실행 중인 Codex에게 그대로 맡길 작업 프롬프트**다. 목표는
현재 WSL 환경의 `material_span_grounding` 프로젝트, 완료된 실험 산출물, 로컬 입력
데이터, Python 환경을 A100 서버에 복구하고 검증하는 것이다. 호스트의 NVIDIA 드라이버는
A100 서버 관리 대상이므로 복사하거나 교체하지 않는다.

## A100 Codex에게 보낼 한 줄 프롬프트

아래 문장을 A100 서버의 `/home/user/onsesang/material_span_grounding` 디렉터리에서 시작한 Codex에게 보낸다.

> `A100_CODEX_MIGRATION_HANDOFF.md`와 저장소의 `AGENTS.md`를 끝까지 읽고, 문서의 Stage 0부터 Stage 8까지 순서대로 실제 실행해줘. 계획만 설명하지 말고 환경 구축, 경로 이관, 모델 다운로드, 테스트, 결과 검증, 최종 보고서 작성까지 완료해줘. NVIDIA 커널 드라이버는 변경하지 말고, 기존 Phase 0~11 실험 산출물은 덮어쓰거나 재실행하지 마. 진행 중 안전하게 해결 가능한 오류는 원인을 조사하고 수정한 뒤 계속 진행하고, 외부 권한이나 서버 관리자 조치가 반드시 필요한 경우에만 정확한 증거와 필요한 명령을 보고해줘.

Codex는 프로젝트 루트에서 시작하면 작업 전에 `AGENTS.md`를 읽는다. 따라서 반드시
`/home/user/onsesang/material_span_grounding`에서 Codex를 시작한다. 참고:
[OpenAI Codex의 AGENTS.md 안내](https://developers.openai.com/codex/guides/agents-md).

## 1. 이관 목표와 완료 조건

다음 조건을 모두 만족해야 이관이 완료된 것이다.

1. A100 서버의 실제 GPU 이름, VRAM, 드라이버, CUDA 호환 상태가 기록되어 있다.
2. 프로젝트와 원본 입력 데이터가 고정 루트 `/home/user/onsesang` 아래에 복구되어 있다.
3. 소스 환경의 두 Conda 환경 `texture`, `material_vllm312`가 같은 Python·핵심 패키지
   버전으로 만들어져 있다.
4. Qwen, FashionCLIP, DINOv2, BGE가 지정된 commit revision으로 로컬 캐시에 있다.
5. `/home/onsesang` 절대 경로가 고정 A100 루트 `/home/user/onsesang`으로 안전하게 치환되어 있다.
6. `texture`와 `material_vllm312` 모두 A100 CUDA tensor smoke test를 통과한다.
7. 루트 unittest 20개와 v2 unittest 23개가 모두 통과한다.
8. 기존 v2 Phase 0~11 완료 manifest와 결과 파일이 존재하며, 실험을 재실행하지 않고
   상태만 검증했다.
9. 실제 실행 결과와 소스 환경 대비 차이를
   `migration/a100/A100_MIGRATION_REPORT.md`에 기록했다.

## 2. 소스 환경 기준선

소스는 Ubuntu 24.04.4 WSL2, x86_64이며 RTX 3060에서 작성되었다. GPU 드라이버는
591.59, `nvidia-smi`가 표시한 최대 CUDA 호환 버전은 13.1이었다. A100 서버의 커널,
드라이버, 장치명과 VRAM은 달라도 정상이다.

### 프로젝트와 데이터

| 항목 | 소스 위치 | 대략적 크기/수량 | 복구 방식 |
|---|---|---:|---|
| 전체 프로젝트·실험 결과 | `/home/onsesang/material_span_grounding` | 590MB | 프로젝트 ZIP |
| 상품 split | `seoyoung/data/splits/train.json` | 8.2MB | 입력 데이터 ZIP |
| 추천 interaction | `seoyoung/data/interim/recommendation_interactions.parquet` | 9.8MB | 입력 데이터 ZIP |
| Amazon Fashion review Dataset | `yoojeong/amazon_reviews_all/review_Amazon_Fashion` | 약 680MB, 2 Arrow shard | 입력 데이터 ZIP |
| 로컬 상품 이미지 | `texture_project/images_train` | 약 5.1GB, 21,059개 | 입력 데이터 ZIP |
| 상품 이미지 metadata | `texture_project/data/product_images.json` | 약 517MB | 입력 데이터 ZIP |

이 프로젝트 루트는 Git 저장소가 아니므로 인터넷에서 Git clone만 해서는 복원할 수 없다.
프로젝트 ZIP이 원본 코드와 현재 산출물의 기준이다. 입력 데이터도 로컬에서 만들어진 split,
Arrow dataset, 이미지 집합이므로 함께 옮긴다.

### Python 환경

| 환경 | Python | 핵심 패키지 |
|---|---|---|
| `texture` | 3.10.20 | torch 2.5.1+cu121, torchvision 0.20.1+cu121, transformers git commit `a66638d854ae536e0ca31e8bcfa480adfaf58284`, bitsandbytes 0.49.2, numpy 2.2.6, pandas 2.3.3, scikit-learn 1.7.2 |
| `material_vllm312` | 3.12.13 | torch 2.13.0+cu130, torchvision 0.28.0+cu130, transformers 5.15.0, vLLM 0.27.1, bitsandbytes 0.50.0 |

전체 패키지 명세는 다음 파일에 있다.

- `migration/a100/environment.texture.yml`
- `migration/a100/environment.material_vllm312.yml`

Conda 환경 디렉터리 자체는 각각 약 8GB이고 절대 경로와 네이티브 라이브러리를 포함하므로
그대로 복사하지 않는다. 위 고정 명세로 A100에서 다시 만든다.

### 고정 모델 revision

| 용도 | Hugging Face ID | revision |
|---|---|---|
| Qwen semantic labeler | `Qwen/Qwen3-VL-8B-Instruct` | `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b` |
| FashionCLIP | `patrickjohncyh/fashion-clip` | `7e3ba62ce16b379a1ab479346b66f192e76f51b7` |
| DINOv2-small | `facebook/dinov2-small` | `ed25f3a31f01632728cabb09d1542f84ab7b0056` |
| BGE text baseline | `BAAI/bge-small-en-v1.5` | `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` |

이 모델들은 A100 서버에서 인터넷으로 같은 revision을 받을 수 있으므로 기본 전송 ZIP에는
넣지 않았다. 소스의 관련 Hugging Face hub cache는 약 18GB이며 그중 Qwen이 약 17GB다.
Hugging Face 접근이 차단된 서버라면 모델 캐시만 별도 오프라인 묶음으로 요청한다.

## 3. 보안과 변경 경계

- NVIDIA 커널 드라이버를 설치, 제거, 업그레이드하거나 재부팅하지 않는다.
- `/usr`, `/etc`, 다른 사용자의 홈, 기존 시스템 CUDA를 변경하지 않는다.
- `sudo`가 필요하면 먼저 이유를 보고한다. Miniconda와 Python 패키지도 `/home/user/onsesang/miniconda3`에 설치한다.
- 기존 Phase 0~11 산출물, raw review, exact span을 덮어쓰지 않는다.
- 프로젝트의 `shopping_agent/.env`, 실제 API key, Discord webhook은 전송하지 않았다.
- `shopping_agent/.env.example`은 안전한 빈 템플릿으로만 복원한다. 실제 키는 사용자가 A100
  터미널에서 직접 입력하며 Codex 대화나 셸 history에 붙이지 않는다.
- 서버 접속 암호도 문서에 기록하지 않는다. 이미 대화로 노출된 암호는 이관 후 변경하고
  SSH key 인증으로 전환하는 것을 권장한다.
- A100 드라이버가 정확한 CUDA 13 runtime을 지원하지 않는다면 임의로 드라이버를 바꾸거나
  패키지 버전을 조용히 낮추지 않는다. 호환성 증거와 가능한 대안을 보고서에 남기고,
  서버 관리자 조치가 필요한 경우에만 hard blocker로 처리한다.

## 4. A100 Codex 실행 절차

### Stage 0 — 인수물과 체크섬 검증

1. `/home/user/onsesang/incoming/a100_migration_bundle_20260825`의 파일 목록을 확인한다.
2. `SHA256SUMS.parts`가 있으면 먼저 조각 파일 무결성을 확인한다.
3. 분할된 입력 데이터가 있으면 파일명 순서대로 합친다.
4. `SHA256SUMS.archives`로 완성된 ZIP 파일을 확인한다.
5. 체크섬이 하나라도 다르면 압축을 풀지 말고 실패한 파일만 다시 전송하도록 보고한다.

예시:

```bash
cd /home/user/onsesang/incoming/a100_migration_bundle_20260825
sha256sum -c SHA256SUMS.parts
cat material_span_grounding_external_inputs_20260825.zip.part-* > \
  material_span_grounding_external_inputs_20260825.zip
sha256sum -c SHA256SUMS.archives
```

### Stage 1 — 압축 해제와 레이아웃 확인

아카이브에는 소스 작업 루트 기준 상대 경로가 들어 있다. A100의 고정 작업 루트는
`/home/user/onsesang`이다. 기존 경로가 있으면 무조건 덮어쓰지 말고 내용과 소유자를 먼저
확인한다. 새 서버에 동일 프로젝트가 없다면 다음처럼 고정 루트에 푼다.

```bash
install -d -m 0750 /home/user/onsesang
cd /home/user/onsesang/incoming/a100_migration_bundle_20260825
bsdtar -xf material_span_grounding_project_20260825.zip -C /home/user/onsesang
bsdtar -xf material_span_grounding_external_inputs_20260825.zip -C /home/user/onsesang
```

`bsdtar`가 없다면 `unzip`을 사용한다. 압축을 푼 뒤 다음 경로가 있어야 한다.

```text
/home/user/onsesang/material_span_grounding
/home/user/onsesang/seoyoung/data/splits/train.json
/home/user/onsesang/seoyoung/data/interim/recommendation_interactions.parquet
/home/user/onsesang/yoojeong/amazon_reviews_all/review_Amazon_Fashion
/home/user/onsesang/texture_project/images_train
/home/user/onsesang/texture_project/data/product_images.json
```

최종 디렉터리 구조는 다음과 같이 고정한다.

```text
/home/user/onsesang/
├── incoming/
│   └── a100_migration_bundle_20260825/   # 전송한 ZIP 조각·문서·체크섬
├── material_span_grounding/              # 프로젝트 코드·v1/v2 결과
├── seoyoung/
│   └── data/                              # split·추천 interaction
├── yoojeong/
│   └── amazon_reviews_all/                # Amazon Fashion review dataset
├── texture_project/
│   ├── data/                              # 상품 이미지 metadata
│   └── images_train/                      # 로컬 이미지 21,059개
├── miniconda3/                            # 두 Conda 환경
└── .cache/
    └── huggingface/                       # 고정 revision 모델 cache
```

### Stage 2 — A100와 OS 사전 점검

다음을 실행하고 결과를 보고서 초안에 기록한다.

```bash
uname -a
sed -n '1,20p' /etc/os-release
nvidia-smi
nvidia-smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv,noheader
df -h /home/user/onsesang
```

GPU 이름에 A100이 포함되는지, 최소 40GB 정도의 VRAM이 보이는지, 프로젝트·환경·모델을
위해 홈에 충분한 공간이 있는지 확인한다. `nvidia-smi`가 실패하면 Python 환경보다 먼저
서버 관리자에게 드라이버 상태 확인을 요청한다.

### Stage 3 — 경로 dry-run

소스 코드와 manifest에는 `/home/onsesang` 절대 경로가 남아 있다. 실제 치환 전에 변경
대상을 검토한다.

```bash
cd /home/user/onsesang/material_span_grounding
python3 migration/a100/relocate_paths.py \
  --project-root "$PWD" --old-home /home/onsesang \
  --new-home /home/user/onsesang --dry-run \
  > /tmp/material_span_a100_relocation_dry_run.json
```

변경 범위가 `material_span_grounding` 내부 텍스트 파일뿐인지 확인한다. 이 도구는 raw
binary, 이미지, NPZ, Parquet, Arrow, 모델 파일을 수정하지 않는다.

### Stage 4 — Conda 환경 구축

`migration/a100/bootstrap_a100.sh`는 다음 작업을 자동으로 수행한다.

1. A100과 `nvidia-smi`를 확인한다.
2. 필요하면 `/home/user/onsesang/miniconda3`에 Miniconda를 설치한다.
3. `texture`, `material_vllm312` 환경을 고정 YAML로 만든다.
4. 프로젝트 텍스트 경로를 `/home/user/onsesang`으로 치환한다.
5. Hugging Face 실제 cache를 `/home/user/onsesang/.cache/huggingface`에 두고,
   `Path.home()`을 사용하는 기존 코드 호환을 위해 `$HOME/.cache/huggingface`에는 그 위치를
   가리키는 symlink만 둔다.
6. 안전한 `.env.example`을 복원한다.
7. 네 모델의 고정 revision을 다운로드한다.
8. CUDA, 데이터, unittest, 완료 manifest를 검증한다.

실행 전 스크립트와 YAML을 읽어 변경 범위를 확인한 뒤 실행한다.

```bash
cd /home/user/onsesang/material_span_grounding
chmod +x migration/a100/*.sh migration/a100/*.py
bash migration/a100/bootstrap_a100.sh 2>&1 | tee migration/a100/bootstrap_a100.log
```

환경 이름이 이미 존재하면 스크립트는 삭제하거나 덮어쓰지 않는다. Codex는 기존 환경이
이 프로젝트용인지 조사하고, 핵심 버전이 일치하면 재사용한다. 불일치하면 기존 환경을
보존한 채 이름 변경 또는 사용자 확인이 필요한 사항을 보고한다.

### Stage 5 — 모델 검증

다운로드가 완료되면 revision별 snapshot 경로가 존재하는지 확인한다. 코드의
`local_files_only=True` 호출이 네트워크 없이 열리는지 processor/config 수준의 smoke test를
수행한다. Qwen 전체 generation이나 Phase 2를 다시 실행할 필요는 없다.

Hugging Face 다운로드가 막히면 다음을 기록한다.

- 실패한 repo ID와 revision
- HTTP/DNS/인증 오류 원문
- `$HF_HOME`과 실제 cache 위치
- 필요한 오프라인 모델 cache 예상 크기

토큰을 문서나 명령행에 넣지 않는다.

### Stage 6 — A100 실행 검증

자동 검증이 중간에 중단되었거나 별도 재검증이 필요하면 다음을 실행한다.

```bash
cd /home/user/onsesang/material_span_grounding
A100_WORKSPACE_ROOT=/home/user/onsesang \
CONDA_EXE=/home/user/onsesang/miniconda3/bin/conda \
  bash migration/a100/verify_a100.sh "$PWD" \
  2>&1 | tee migration/a100/verify_a100.log
```

성공 기준은 다음과 같다.

- `texture`: CUDA available, A100 이름 출력, tensor 연산 성공
- `material_vllm312`: torch, transformers, vLLM import와 CUDA 확인 성공
- root unittest: `Ran 20 tests`, `OK`
- v2 unittest: `Ran 23 tests`, `OK`
- Phase 4는 `skipped_by_user_pending`가 정상이며 human-validated로 바꾸지 않음
- Phase 8은 `complete_with_leeds_unavailable`가 기존 정상 상태
- 나머지 요구 Phase manifest는 `complete`

### Stage 7 — 결과물 무변경 확인

다음 핵심 파일이 존재하는지와 크기, SHA-256을 기록한다.

```text
tactile_coldstart_qwen_v2_full/data/reviews_full_pool.jsonl
tactile_coldstart_qwen_v2_full/data/lexical_tactile_candidates_all.jsonl
tactile_coldstart_qwen_v2_full/artifacts/axis_groundings.jsonl
tactile_coldstart_qwen_v2_full/artifacts/product_axis_targets.jsonl
tactile_coldstart_qwen_v2_full/artifacts/phase6_7_model_results.json
tactile_coldstart_qwen_v2_full/artifacts/phase9_selective_results.json
tactile_coldstart_qwen_v2_full/artifacts/phase10_retrieval_results.json
tactile_coldstart_qwen_v2_full/artifacts/phase11_paper_results.json
tactile_coldstart_qwen_v2_full/notion/TACTILE_COLDSTART_V2_FULL_PHASE_0_TO_11.md
```

경로 문자열 치환 외에는 기존 산출물을 수정하지 않는다. 특히 `scripts/run_phase_sequence.py`를
실행하지 않는다. A100 재실험은 이관 검증이 끝난 뒤 별도 요청으로만 수행한다.

### Stage 8 — 최종 보고서

`migration/a100/A100_MIGRATION_REPORT.md`를 작성한다. 최소 포함 항목은 다음과 같다.

- 이관 시작·완료 시각
- A100 모델, VRAM, 드라이버, OS
- 압축 파일과 체크섬 검증 결과
- 복구한 경로, 파일 수와 크기
- 두 Conda 환경의 Python·torch·CUDA·transformers·vLLM 버전
- 네 모델의 실제 resolved snapshot 경로
- path relocation 변경 파일 수와 manifest 위치
- CUDA smoke test 결과
- 20개 + 23개 unittest 결과
- Phase 0~11 manifest 상태
- 소스 기준선과 달라진 점 및 이유
- 남은 제한: Phase 4 human audit 미실시, Leeds 비공개/미확인

보고서를 작성한 뒤 사용자에게 성공 여부와 보고서 경로를 알린다. 실패가 있더라도 가능한
다른 Stage를 먼저 완료하고, 마지막에 hard blocker만 모아 구체적으로 보고한다.

## 5. Windows를 경유한 전송 명령

### 방법 A — 현재 Linux가 같은 노트북의 WSL인 경우

현재 환경은 WSL2로 확인되었다. 같은 Windows 노트북이라면 PowerShell에서 다음처럼
Downloads로 복사하는 것이 가장 간단하다. `<WINDOWS_USER>`를 실제 Windows 계정명으로
바꾼다.

```powershell
wsl.exe -d Ubuntu -- bash -lc 'cp -av /home/onsesang/a100_migration_bundle_20260825 /mnt/c/Users/<WINDOWS_USER>/Downloads/'
```

배포판 이름이 `Ubuntu`가 아니면 먼저 확인한다.

```powershell
wsl.exe --list --verbose
```

### 방법 B — 현재 Linux가 별도 원격 서버인 경우

Windows PowerShell에서 현재 서버의 실제 SSH 사용자, 호스트, 포트로 바꿔 실행한다.

```powershell
$Source = "<CURRENT_USER>@<CURRENT_SERVER_HOST>"
$Local = "$env:USERPROFILE\Downloads\a100_migration_bundle_20260825"
New-Item -ItemType Directory -Force -Path $Local | Out-Null
scp -P <CURRENT_SERVER_SSH_PORT> -r "${Source}:/home/onsesang/a100_migration_bundle_20260825/*" $Local
```

### Windows에서 파일 hash 확인

`SHA256SUMS.parts`와 비교할 값은 다음처럼 계산할 수 있다.

```powershell
Get-ChildItem "$env:USERPROFILE\Downloads\a100_migration_bundle_20260825" -File |
  Get-FileHash -Algorithm SHA256 |
  Format-Table Hash, Path -AutoSize
```

### Windows → A100 서버

Windows VPN을 먼저 연결한 뒤 PowerShell에서 실행한다. 암호는 명령에 적지 말고 SSH가
요청할 때 입력한다.

```powershell
$Local = "$env:USERPROFILE\Downloads\a100_migration_bundle_20260825"
$Remote = "user@10.201.31.126"
ssh -p 2024 $Remote "mkdir -p /home/user/onsesang/incoming/a100_migration_bundle_20260825"
Get-ChildItem $Local -File | ForEach-Object {
  scp -P 2024 $_.FullName "${Remote}:/home/user/onsesang/incoming/a100_migration_bundle_20260825/"
}
```

전송 후 접속한다.

```powershell
ssh -p 2024 user@10.201.31.126
```

대용량 전송이 중간에 자주 끊기면 분할 파일 중 실패한 조각만 다시 `scp`하면 된다.

## 6. A100에 Codex가 없을 때

OpenAI 공식 설치 방법은 Linux에서 다음 명령을 실행하는 것이다.

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

설치 후 프로젝트 루트에서 `codex`를 실행하고 로그인한다.
[Codex CLI 공식 안내](https://developers.openai.com/codex/cli).

```bash
cd /home/user/onsesang/material_span_grounding
codex
```

그 다음 이 문서 맨 위의 “A100 Codex에게 보낼 한 줄 프롬프트”를 입력한다.

## 7. 이관본에서 의도적으로 제외한 것

- `shopping_agent/.env`: 실제 API key가 있으므로 제외
- 기존 `shopping_agent/.env.example`: 키처럼 보이는 값이 있어 제외하고 빈 안전 템플릿 제공
- Conda 환경 디렉터리 자체: 절대 경로·GPU native library 때문에 명세로 재구축
- 전체 Hugging Face cache: 인터넷에서 고정 revision 재다운로드 가능하며 약 18GB
- stale PID와 Python bytecode cache: 실행 환경에서 다시 생성

프로젝트의 raw data, 현재 결과 JSON/JSONL/NPZ/joblib, 실험 log, 보고서, v1/v2 코드는
전송본에 포함한다.
