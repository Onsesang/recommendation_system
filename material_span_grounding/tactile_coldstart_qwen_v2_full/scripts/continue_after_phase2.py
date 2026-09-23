#!/usr/bin/env python3
"""Wait for an already-running Phase 2, recover its cache, then finish Phase 3-11."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from run_phase_sequence import QWEN_PYTHON, ROOT, TEXTURE_PYTHON, notify


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def phase2_complete() -> bool:
    path = ROOT / "manifests" / "phase2_axis_grounding.json"
    if not path.is_file():
        return False
    value = json.loads(path.read_text(encoding="utf-8"))
    return (
        value.get("status") == "complete"
        and value.get("schema_success") == value.get("full_input_claims")
        and value.get("requested_claims") == value.get("full_input_claims")
    )


def run(command: list[str], log_name: str) -> int:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT.parent)
    with (ROOT / "logs" / log_name).open("a", encoding="utf-8") as log:
        return subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, check=False).returncode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase2_pid", type=int)
    args = parser.parse_args()
    while alive(args.phase2_pid):
        time.sleep(30)
    attempt = 0
    while not phase2_complete():
        attempt += 1
        notify(f"[tactile_coldstart_qwen_v2_full] Phase 2 cache recovery/resume attempt {attempt}")
        code = run([str(QWEN_PYTHON), str(ROOT / "scripts" / "run_phase.py"), "2"], "phase_2_recovery.log")
        if code and not phase2_complete():
            notify(f"[tactile_coldstart_qwen_v2_full] Phase 2 resume exit={code}; 30초 후 완료 지점에서 재시도합니다.")
            time.sleep(30)
    value = json.loads((ROOT / "manifests" / "phase2_axis_grounding.json").read_text(encoding="utf-8"))
    notify(f"[tactile_coldstart_qwen_v2_full] Phase 2 완료. grounded={value['schema_success']:,}, mappable={value['mappable']:,}, unmappable={value['unmappable']:,}. Phase 3부터 계속합니다.")
    while True:
        code = run([str(TEXTURE_PYTHON), str(ROOT / "scripts" / "run_phase_sequence.py"), "--start", "3"], "phase_3_to_11_sequence.log")
        if code == 0:
            break
        notify(f"[tactile_coldstart_qwen_v2_full] Phase 3~11 sequence exit={code}; 완료 manifest를 보존한 채 30초 후 재시도합니다.")
        time.sleep(30)


if __name__ == "__main__":
    main()
