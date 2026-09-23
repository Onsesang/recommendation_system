#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT.parent
for value in (ROOT / "src", PARENT):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=[str(value) for value in range(12)])
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    if args.phase == "0":
        from tactile_coldstart.protocol import build_protocol
        result = build_protocol()
    elif args.phase == "1":
        from tactile_coldstart.protocol import document_taxonomy
        result = document_taxonomy()
    elif args.phase == "2":
        from tactile_coldstart.grounding import run_qwen_grounding
        result = run_qwen_grounding(limit=args.limit)
    elif args.phase == "3":
        from tactile_coldstart.diagnostics import run_diagnostics
        result = run_diagnostics()
    elif args.phase == "4":
        from tactile_coldstart.audit_v2 import record_skipped_human_audit
        result = record_skipped_human_audit()
    elif args.phase == "5":
        from tactile_coldstart.targets import build_targets
        result = build_targets()
    elif args.phase == "6":
        from tactile_coldstart.visual_features import extract_dino_embeddings, extract_fashionclip_embeddings
        result = {"fashionclip": extract_fashionclip_embeddings(), "dino": extract_dino_embeddings()}
    elif args.phase == "7":
        from tactile_coldstart.modeling import run_model_experiments
        result = run_model_experiments()
    elif args.phase == "8":
        from tactile_coldstart.external import evaluate_external_transfer
        result = evaluate_external_transfer()
    elif args.phase == "9":
        from tactile_coldstart.selective import run_selective_calibration
        result = run_selective_calibration()
    elif args.phase == "10":
        from tactile_coldstart.retrieval import run_coldstart_retrieval
        result = run_coldstart_retrieval()
    else:
        from tactile_coldstart.reporting_v2 import run_final_reporting_v2
        result = run_final_reporting_v2()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
