#!/usr/bin/env python3
"""Regression tests for Exp24 rank computation.

These exist because a real bug shipped here and was caught only by an implausible
result: padding the candidate array with -inf and then selecting the target score
with (scores * hit).sum() evaluates -inf * 0 = NaN, which silently gave padded rows
rank 1 and inflated validation NDCG@10 roughly fivefold.

Run: <texture python> tests/test_rank_computation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import numpy as np
from importlib import import_module

rerank = import_module("05_rerank")
ranks_from_scores = rerank.ranks_from_scores

CANDIDATES = np.array([[11, 12, 13, 14, 0, 0],      # two padded slots
                       [21, 22, 23, 24, 25, 26]],   # no padding
                      dtype=np.int64)
SCORES = np.array([[0.9, 0.8, 0.7, 0.6, 0.5, 0.5],
                   [0.9, 0.8, 0.7, 0.6, 0.5, 0.4]], dtype=np.float64)


def check(name, got, expected):
    got = list(np.asarray(got))
    assert got == expected, f"{name}: got {got}, expected {expected}"
    print(f"  ok  {name}: {got}")


def main() -> int:
    print("rank computation:")
    check("target third best, padding present",
          ranks_from_scores(SCORES, CANDIDATES, np.array([13, 23])), [3, 3])
    check("target best",
          ranks_from_scores(SCORES, CANDIDATES, np.array([11, 21])), [1, 1])
    check("target worst real slot",
          ranks_from_scores(SCORES, CANDIDATES, np.array([14, 26])), [4, 6])
    check("target absent -> past the end",
          ranks_from_scores(SCORES, CANDIDATES, np.array([99, 99])),
          [CANDIDATES.shape[1] + 1] * 2)

    # padding must never displace the target, however many slots there are
    wide = np.concatenate([CANDIDATES, np.zeros((2, 4), dtype=np.int64)], axis=1)
    wide_scores = np.concatenate([SCORES, np.full((2, 4), 0.95)], axis=1)
    check("many padded slots with high scores cannot displace the target",
          ranks_from_scores(wide_scores, wide, np.array([13, 23])), [3, 3])

    # ties break by ascending candidate id, the exp17b rule
    tie_candidates = np.array([[30, 20, 10]], dtype=np.int64)
    tie_scores = np.array([[0.5, 0.5, 0.5]], dtype=np.float64)
    check("ties break by ascending id (target 20 sits behind 10)",
          ranks_from_scores(tie_scores, tie_candidates, np.array([20])), [2])

    print("\nall rank-computation tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
