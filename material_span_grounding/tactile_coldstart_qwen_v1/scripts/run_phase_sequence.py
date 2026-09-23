#!/usr/bin/env python3
from __future__ import annotations

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
    webhook = os.environ.get("TACTILE_DISCORD_WEBHOOK")
    if not webhook:
        return False
    urls = [webhook]
    if "discordapp.com" in webhook:
        urls.append(webhook.replace("discordapp.com", "discord.com", 1))
    payload = json.dumps({"content": message}, ensure_ascii=False).encode("utf-8")
    last_error = "unknown error"
    for url in urls:
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 tactile-coldstart/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status in (200, 204):
                    return True
                last_error = f"HTTP {response.status}"
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
    # Notification transport must never invalidate or interrupt an experiment.
    print(f"Discord notification warning: {last_error}", file=sys.stderr, flush=True)
    return False


def run(python: Path, phase: str) -> None:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(PARENT)
    command = [str(python), str(ROOT / "scripts" / "run_phase.py"), phase]
    print(f"\n=== running phase {phase} ===", flush=True)
    subprocess.run(command, cwd=ROOT, env=environment, check=True)


def main() -> None:
    phase2_path = ROOT / "manifests" / "phase2_axis_grounding.json"
    phase2 = json.loads(phase2_path.read_text(encoding="utf-8"))
    if not (
        phase2.get("status") == "complete"
        and phase2.get("requested_claims") == phase2.get("full_input_claims")
        and phase2.get("schema_success") == phase2.get("full_input_claims")
    ):
        raise RuntimeError("Phase 2 full grounding manifest is not complete")
    sequence = [
        (TEXTURE_PYTHON, "3"),
        (TEXTURE_PYTHON, "4"),
        (TEXTURE_PYTHON, "4-eval"),
        (TEXTURE_PYTHON, "5"),
        (QWEN_PYTHON, "6-vlm"),
        (TEXTURE_PYTHON, "6-dino"),
        (TEXTURE_PYTHON, "6-7"),
        (TEXTURE_PYTHON, "8"),
        (TEXTURE_PYTHON, "9"),
        (TEXTURE_PYTHON, "10"),
        (TEXTURE_PYTHON, "11"),
    ]
    try:
        for python, phase in sequence:
            run(python, phase)
            if phase == "3":
                diagnostics = json.loads((ROOT / "manifests" / "phase3_diagnostics.json").read_text(encoding="utf-8"))
                if not diagnostics.get("gate_passed"):
                    raise RuntimeError("Phase 3 feasibility gate failed with no active axes")
                print(f"Phase 3 gate active axes: {diagnostics['active_axes']}", flush=True)
            if phase in {"3", "8", "10"}:
                notify(f"[tactile_coldstart_qwen_v1] Phase {phase} 완료. 다음 단계를 계속 실행합니다.")
    except BaseException as exc:
        notify(f"[tactile_coldstart_qwen_v1] 실행 실패: {type(exc).__name__}: {exc}")
        raise
    final = json.loads((ROOT / "manifests" / "phase11_final.json").read_text(encoding="utf-8"))
    notion = final["outputs"]["notion_report"]
    notify(f"[tactile_coldstart_qwen_v1] Phase 0-11 완료. status={final['status']}. Notion-ready 문서: {notion}")


if __name__ == "__main__":
    main()
