"""Experiment 20 utilities.

All generated files stay under this experiment root. External inputs are read
only through the frozen manifest/protocol allowlist.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import time

import numpy as np

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent
EXP16 = PROJECT / "experiments/16_strong_recommender_tactile"
ART = ROOT / "artifacts"
DATA = ROOT / "data"
CONFIG = ROOT / "configs"
SEED = 20260904

CLASSES = [
    "soft",
    "firm",
    "smooth",
    "rough",
    "non_elastic",
    "elastic",
    "thin",
    "thick",
    "flexible",
    "stiff",
    "warm",
    "cool",
    "spongy",
    "crisp",
]
RELIABLE = ["smooth", "rough", "thin", "thick", "flexible", "stiff", "warm", "cool"]


def resolve_project_path(path: str | Path) -> Path:
    path = Path(path)
    if not path.is_absolute():
        path = PROJECT / path
    return path.resolve()


def sha(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha_many(paths: list[Path]) -> dict[str, str]:
    return {str(path.relative_to(ROOT)): sha(path) for path in sorted(paths)}


def save_json(path: str | Path, value) -> None:
    path = Path(path)
    assert path.resolve().is_relative_to(ROOT), path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    os.replace(tmp, path)


def load_json(path: str | Path):
    return json.loads(Path(path).read_text())


def event(stage: str, status: str, **extra) -> None:
    ART.mkdir(parents=True, exist_ok=True)
    row = {
        "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stage": stage,
        "status": status,
        **extra,
    }
    with open(ART / "events.jsonl", "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps(row, ensure_ascii=False), flush=True)
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if url and status in ("started", "complete", "failed", "blocked"):
        import urllib.request

        body = "[Exp20 tactile completion] " + stage + ": " + status + "\n"
        body += json.dumps(extra, ensure_ascii=False)[:1200]
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps({"content": body, "allowed_mentions": {"parse": []}}).encode(),
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                code = r.status
            with open(ART / "notifications.jsonl", "a") as f:
                f.write(json.dumps({"time_utc": row["time_utc"], "stage": stage, "status": status, "http": code}) + "\n")
        except Exception as exc:
            with open(ART / "notifications.jsonl", "a") as f:
                f.write(json.dumps({"stage": stage, "error_type": type(exc).__name__}) + "\n")


def metric_dict(ranks: np.ndarray) -> dict[str, float | int | None]:
    ranks = np.asarray(ranks)
    out: dict[str, float | int | None] = {"users": int(len(ranks))}
    if not len(ranks):
        for key in ("ndcg_at_5", "hr_at_5", "ndcg_at_10", "hr_at_10", "mrr_at_10"):
            out[key] = None
        for k in (100, 300, 500, 1000, 3000, 10000, 30000):
            out[f"recall_at_{k}"] = None
        return out
    for k in (5, 10):
        ok = (ranks > 0) & (ranks <= k)
        out[f"ndcg_at_{k}"] = float(np.where(ok, 1 / np.log2(np.maximum(ranks, 1) + 1), 0).mean())
        out[f"hr_at_{k}"] = float(ok.mean())
    out["mrr_at_10"] = float(np.where((ranks > 0) & (ranks <= 10), 1 / np.maximum(ranks, 1), 0).mean())
    for k in (100, 300, 500, 1000, 3000, 10000, 30000):
        out[f"recall_at_{k}"] = float(((ranks > 0) & (ranks <= k)).mean())
    return out


def require_state(*allowed: str) -> dict:
    path = ART / "protocol_state.json"
    if not path.exists():
        raise RuntimeError("protocol_state.json is missing")
    state = load_json(path)
    if state.get("state") not in allowed:
        raise RuntimeError(f"state {state.get('state')} not in {allowed}")
    return state


def transition_state(expected: str, new_state: str, **extra) -> None:
    path = ART / "protocol_state.json"
    state = load_json(path) if path.exists() else {"state": "implemented_not_scored", "history": []}
    if state.get("state") != expected:
        raise RuntimeError(f"cannot transition from {state.get('state')} to {new_state}; expected {expected}")
    state.setdefault("history", []).append(
        {
            "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "from": expected,
            "to": new_state,
            **extra,
        }
    )
    state["state"] = new_state
    save_json(path, state)
