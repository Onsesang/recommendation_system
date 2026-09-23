#!/usr/bin/env python3
"""Watch the auto-generated audit quality gate and report meaningful changes."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METRICS = (
    PROJECT_ROOT / "experiments/03_human_semantic_audit/results/metrics.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--interval", type=float, default=30.0)
    parser.add_argument("--exit-on-terminal", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.interval < 1:
        raise SystemExit("--interval must be at least 1 second")
    previous = None
    while True:
        if args.metrics.is_file():
            metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
            current = (
                metrics["status"],
                metrics["sample"]["labeled"],
                metrics["development_triggered"],
            )
            if current != previous:
                print(
                    json.dumps(
                        {
                            "status": current[0],
                            "labeled": current[1],
                            "expected": metrics["sample"]["expected"],
                            "development_triggered": current[2],
                            "failures": metrics["gate"]["failures"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                previous = current
            if args.exit_on_terminal and (
                metrics["development_triggered"] or metrics["status"] == "final_pass"
            ):
                return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
