#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = "/home/user/onsesang/miniconda3/envs/texture/bin/python"


def notify(message: str) -> None:
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url: return
    request = urllib.request.Request(
        url,
        data=json.dumps({"content": message}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "onsesang-research-runner/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30): pass
    except Exception as exc:
        print(f"Discord notification warning: {type(exc).__name__}: {exc}", flush=True)


def run(name: str, command: list[str], marker: Path) -> None:
    if marker.is_file() and json.loads(marker.read_text()).get("status") == "complete":
        notify(f"[onsesang v3][{name}] 기존 완료 체크포인트 확인, 다음 단계로 진행합니다.")
        return
    attempts = 0
    while True:
        attempts += 1
        notify(f"[onsesang v3][{name}] 시작 (시도 {attempts})")
        result = subprocess.run(command, cwd=ROOT, env=os.environ.copy())
        if result.returncode == 0:
            notify(f"[onsesang v3][{name}] 완료")
            return
        delay = min(300, 15 * attempts)
        notify(f"[onsesang v3][{name}] 실패(code={result.returncode}), {delay}초 후 체크포인트에서 재시도합니다.")
        time.sleep(delay)


def main() -> int:
    common = {"HOME": "/home/user/onsesang", "HF_HOME": "/home/user/onsesang/.cache/huggingface", "HF_HUB_CACHE": "/home/user/onsesang/.cache/huggingface/hub", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"}
    os.environ.update(common)
    run("Stage 2 Qwen32B 전체 class grounding", [PYTHON, str(ROOT / "scripts/ground_classes.py")], ROOT / "manifests/ground_classes.json")
    run("Stage 2B grounding parse repair", [PYTHON, str(ROOT / "scripts/repair_groundings.py")], ROOT / "manifests/repair_groundings.json")
    run("Stage 3 reviewer-first class target", [PYTHON, str(ROOT / "scripts/build_targets.py")], ROOT / "manifests/build_targets.json")
    run("Stage 4 FashionCLIP fine-tuning ablation", [PYTHON, str(ROOT / "scripts/train_fashionclip.py")], ROOT / "manifests/train_fashionclip.json")
    run("Stage 5 최종 평가 및 Notion 문서", [PYTHON, str(ROOT / "scripts/make_report.py")], ROOT / "manifests/final.json")
    notify("[onsesang v3] 전체 실험 완료. Qwen32B class grounding, FashionCLIP fine-tuning ablation, locked-test 평가와 Notion 문서 생성을 마쳤습니다.")
    return 0


if __name__ == "__main__": raise SystemExit(main())
