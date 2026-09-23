#!/usr/bin/env python3
"""Shared Discord notifier for experiments 22-24.

Reuses the delivery logic of experiments/21_fabricvst_external/scripts/notify.py.
The webhook is read from DISCORD_WEBHOOK_URL, or from the 0600 file
<project root>/.discord_webhook, and is never printed, logged or written into a
report.  Every send is appended (message text only, no URL) to
logs/discord_notifications.jsonl so the notification history is reproducible.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_FILE = ROOT / ".discord_webhook"
LOG_FILE = ROOT / "logs" / "discord_notifications.jsonl"
KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(KST)


def kst(dt: datetime | None = None) -> str:
    return (dt or now_kst()).astimezone(KST).strftime("%Y-%m-%d %H:%M KST")


def _webhook() -> str:
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url and SECRET_FILE.is_file():
        url = SECRET_FILE.read_text().strip()
    return url


def send(message: str) -> bool:
    url = _webhook()
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": now_kst().isoformat(timespec="seconds"), "message": message}
    if not url:
        print("Discord notification skipped: no webhook configured.")
        record["delivered"] = False
        with LOG_FILE.open("a") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return False
    payload = json.dumps({"content": message[:1900]}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "onsesang-exp22-24/1.0"},
        method="POST",
    )
    delivered = False
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status in {200, 204}:
                    delivered = True
                    break
        except (urllib.error.URLError, OSError) as exc:
            if attempt == 2:
                print(f"Discord notification failed after 3 attempts: {type(exc).__name__}")
    record["delivered"] = delivered
    with LOG_FILE.open("a") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return delivered


def main() -> int:
    text = sys.stdin.read() if len(sys.argv) < 2 else " ".join(sys.argv[1:])
    return 0 if send(text) else 1


if __name__ == "__main__":
    raise SystemExit(main())
