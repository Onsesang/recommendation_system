#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT.parent
TEXTURE_PYTHON = Path("/home/user/onsesang/miniconda3/envs/texture/bin/python")
QWEN_PYTHON = Path("/home/user/onsesang/miniconda3/envs/material_vllm312/bin/python")


def notify(message: str) -> bool:
    webhook = os.environ.get("TACTILE_DISCORD_WEBHOOK") or os.environ.get("TASK_DISCORD_WEBHOOK")
    if not webhook:
        print("Discord webhook unavailable; notification not sent", file=sys.stderr, flush=True)
        return False
    urls = [webhook]
    if "discordapp.com" in webhook:
        urls.append(webhook.replace("discordapp.com", "discord.com", 1))
    body = json.dumps({"content": message}, ensure_ascii=False).encode("utf-8")
    for url in urls:
        try:
            request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "tactile-coldstart-v2/1.0"}, method="POST")
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status in (200, 204):
                    return True
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"Discord warning: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    return False


def python_for(phase: int) -> Path:
    return QWEN_PYTHON if phase == 2 else TEXTURE_PYTHON


def manifest_for(phase: int) -> Path:
    names = {
        0: "phase0_full_pool.json", 1: "phase1_taxonomy.json", 2: "phase2_axis_grounding.json",
        3: "phase3_diagnostics.json", 4: "phase4_human_audit.json", 5: "phase5_targets.json",
        6: "phase6_dino_features.json", 7: "phase6_7_models.json", 8: "phase8_external.json",
        9: "phase9_selective.json", 10: "phase10_retrieval.json", 11: "phase11_final.json",
    }
    return ROOT / "manifests" / names[phase]


def phase_complete(phase: int) -> bool:
    path = manifest_for(phase)
    if not path.is_file():
        return False
    value = json.loads(path.read_text(encoding="utf-8"))
    if phase == 2:
        return value.get("status") == "complete" and value.get("schema_success") == value.get("full_input_claims")
    if phase == 4:
        return value.get("status") == "skipped_by_user_pending"
    return str(value.get("status", "")).startswith("complete")


def run_phase(phase: int) -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(PARENT)
    log_path = ROOT / "logs" / f"phase_{phase}.log"
    command = [str(python_for(phase)), str(ROOT / "scripts" / "run_phase.py"), str(phase)]
    with log_path.open("a", encoding="utf-8") as log:
        completed = subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, check=False)
    if completed.returncode:
        tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:])
        raise RuntimeError(f"Phase {phase} failed with exit {completed.returncode}. Tail:\n{tail}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=0)
    args = parser.parse_args()
    try:
        for phase in range(args.start, 12):
            if phase_complete(phase):
                notify(f"[tactile_coldstart_qwen_v2_full] Phase {phase} 이미 완료되어 재사용합니다.")
                continue
            notify(f"[tactile_coldstart_qwen_v2_full] Phase {phase} 시작")
            run_phase(phase)
            if not phase_complete(phase):
                raise RuntimeError(f"Phase {phase} process exited but completion manifest is invalid")
            manifest = json.loads(manifest_for(phase).read_text(encoding="utf-8"))
            detail = ""
            if phase == 0:
                summary = manifest["outputs_summary"]
                detail = f" ASIN={summary['products']:,}, family={summary['parent_families']:,}, reviews={summary['selected_reviews']:,}, candidates={summary['lexical_candidates']:,}."
            elif phase == 2:
                detail = f" grounded={manifest['schema_success']:,}, mappable={manifest['mappable']:,}."
            elif phase == 3:
                detail = f" active_axes={','.join(manifest['active_axes'])}."
            elif phase == 4:
                detail = " 사람 검증은 건너뛰었고 pending으로 기록했습니다."
            elif phase == 10:
                detail = f" queries={manifest['queries']:,}."
            notify(f"[tactile_coldstart_qwen_v2_full] Phase {phase} 완료.{detail} 다음 단계를 계속합니다.")
    except BaseException as exc:
        notify(f"[tactile_coldstart_qwen_v2_full] 실행 실패: {type(exc).__name__}: {exc}")
        raise
    final = json.loads(manifest_for(11).read_text(encoding="utf-8"))
    notify(f"[tactile_coldstart_qwen_v2_full] Phase 0~11 전체 완료. Notion 문서: {final['outputs']['notion_report']}")


if __name__ == "__main__":
    main()
