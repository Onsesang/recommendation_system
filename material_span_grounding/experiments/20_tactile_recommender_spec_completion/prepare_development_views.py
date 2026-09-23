"""Create audited train-only development views from the shared Exp16 split file."""
from __future__ import annotations

import pandas as pd

from common import ART, DATA, EXP16, event, load_json, save_json, sha


def main() -> None:
    manifest = load_json(ART / "input_manifest.json")
    if manifest.get("status") != "complete":
        raise RuntimeError("freeze_inputs.py must complete first")
    event("prepare_development_views", "started")
    source = EXP16 / "data/events.parquet"
    events = pd.read_parquet(source)
    if set(events["split"].unique()) != {"train", "validation", "test"}:
        raise RuntimeError("unexpected split labels in mixed events source")
    train = events[events.split == "train"].copy()
    validation = events[events.split == "validation"].copy()
    DATA.mkdir(parents=True, exist_ok=True)
    outputs = {
        "train_events.parquet": train,
        "validation_events.parquet": validation,
        "validation_targets.parquet": pd.read_parquet(EXP16 / "data/validation_targets.parquet"),
    }
    summary = {
        "source": str(source.resolve()),
        "source_sha256": sha(source),
        "rows": {},
        "sha256": {},
        "mixed_source_reader": "prepare_development_views.py",
    }
    for name, frame in outputs.items():
        path = DATA / name
        tmp = path.with_suffix(path.suffix + ".tmp")
        frame.to_parquet(tmp, index=False)
        tmp.replace(path)
        summary["rows"][name] = int(len(frame))
        summary["sha256"][name] = sha(path)
    save_json(ART / "development_views_manifest.json", summary)
    event("prepare_development_views", "complete", train_rows=len(train), validation_rows=len(validation))


if __name__ == "__main__":
    main()
