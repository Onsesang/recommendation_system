#!/usr/bin/env python3
"""Single end-of-workflow Discord notification.

The webhook URL is read from DISCORD_WEBHOOK_URL and is never printed, logged or
written into any report. If the variable is unset the workflow is not failed;
one line is printed instead.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime


def send(message: str) -> bool:
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        print("Discord notification skipped: DISCORD_WEBHOOK_URL is not configured.")
        return False
    payload = json.dumps({"content": message[:1900]}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "fabricvst-experiment/1.0"},
        method="POST",
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.status in {200, 204}:
                    return True
        except (urllib.error.URLError, OSError):
            if attempt == 2:
                print("Discord notification failed after 3 attempts.")
                return False
    return False


def part_complete(part: str, title: str, facts: list[str], results_dir: str) -> bool:
    """One notification per PART boundary, not per stage inside a PART."""
    body = "\n".join(f"- {line}" for line in facts)
    return send(
        f"[FabricVST {part}] {title}\n\n"
        f"{body}\n\n"
        f"Results: {results_dir}\n"
        f"At: {datetime.now().isoformat(timespec='seconds')}"
    )


def success(lines: list[str], checkpoint: str, old_macro_f1, new_macro_f1, results_dir: str) -> bool:
    body = "\n".join(f"- {line}" for line in lines)
    return send(
        "[FabricVST Experiment Complete]\n\n"
        "Status: SUCCESS\n\n"
        f"{body}\n\n"
        f"Best checkpoint: {checkpoint}\n\n"
        f"Old last2 Macro F1: {old_macro_f1}\n"
        f"New model Macro F1: {new_macro_f1}\n\n"
        f"Results: {results_dir}\n\n"
        f"Finished at: {datetime.now().isoformat(timespec='seconds')}"
    )


def failure(stage: str, reason: str, completed: list[str], last_output: str) -> bool:
    return send(
        "[FabricVST Experiment Finished]\n\n"
        "Status: FAILED\n\n"
        f"Failed stage: {stage}\n\n"
        f"Reason: {reason[:300]}\n\n"
        f"Completed stages: {', '.join(completed) if completed else 'none'}\n\n"
        f"Last valid output: {last_output}\n\n"
        f"Finished at: {datetime.now().isoformat(timespec='seconds')}"
    )
