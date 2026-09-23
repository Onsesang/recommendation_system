"""Sanity checks for Exp20 final artifacts."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from common import ART, EXP16, ROOT, load_json, sha


VARIANT_ORDER = ["I", "I_T", "I_VX", "I_VX_T", "I_VX_T_SHUFFLE"]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    state = load_json(ART / "protocol_state.json")
    selection = load_json(ART / "validation_selection.json")
    tests = load_json(ART / "test_results.json")
    report = ROOT / "notion" / "EXP20_TACTILE_RECOMMENDER_SPEC_COMPLETION_REPORT.md"
    test_targets = pd.read_parquet(EXP16 / "data/test_targets.parquet", columns=["uid", "iid"])

    check(state["state"] == "complete_locked_posthoc_exploratory", "protocol state is not final")
    check(selection["status"] == "validation_locked", "validation selection is not locked")
    check(tests["status"] == "complete_locked_posthoc_exploratory", "test result status is not complete")
    check(tests["confirmatory"] is False, "Track A must not be marked confirmatory")
    check(set(selection["model_selections"]) == set(VARIANT_ORDER), "missing validation selection variant")
    check(set(tests["results"]) == set(VARIANT_ORDER), "missing test result variant")
    for variant in VARIANT_ORDER:
        item = tests["results"][variant]
        p = Path(item["per_user_path"])
        check(p.exists(), f"missing per-user ranks for {variant}")
        check(sha(p) == item["per_user_sha256"], f"per-user sha mismatch for {variant}")
        frame = pd.read_parquet(p, columns=["uid", "iid", "rank", "variant"])
        check(len(frame) == len(test_targets), f"wrong row count for {variant}")
        check((frame[["uid", "iid"]].to_numpy() == test_targets[["uid", "iid"]].to_numpy()).all(), f"target order mismatch for {variant}")
        check((frame["rank"].to_numpy() >= 1).all(), f"non-positive rank for {variant}")
        check((frame["variant"] == variant).all(), f"variant column mismatch for {variant}")
    check("primary_I_VX_T_minus_I_VX" in tests["contrasts"], "missing primary contrast")
    check(report.exists(), "missing final report")
    print("Exp20 sanity checks passed")


if __name__ == "__main__":
    main()
