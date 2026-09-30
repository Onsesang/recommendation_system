#!/usr/bin/env python3
"""Train / validation / test construction for the three ways of cutting the data.

Picture the interactions as a users x time grid (one row per user, time left to right).

  loo  per-user cut, official 0core/last_out.  Each row is cut separately: its last event
       is the test target, the one before it the validation target, the rest train.
  tsp  vertical cut, official 0core/timestamp.  One global time line t1, t2 cuts every
       row at the same moment: train < t1 <= validation < t2 <= test.  Target = the
       user's first event after the cut; history = everything before the cut.
  uh   horizontal cut, user holdout.  Rows are split into groups: 30% of eligible users
       are test users, 10% validation users, every other user's full row is train.
       A held-out user's last event is the target and the earlier events the history.

``data`` selects which events exist at all:
  all  every event on the full 825,869-item catalog (exp16/17/24 setting)
  rec  only events on recommendable items (recommendable_fashion_v1 rule); split labels
       are kept for loo/tsp, as recommendable_fashion_v1 does.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

import common25 as C

LABEL_COLUMN = {"loo": "loo", "tsp": "tsp"}


@dataclass
class Grouped:
    """Per-user chronological item ids: user u owns flat[offsets[u]:offsets[u+1]]."""
    flat: np.ndarray
    offsets: np.ndarray

    @classmethod
    def from_frame(cls, frame: pd.DataFrame, n_users: int) -> "Grouped":
        counts = np.bincount(frame["uid"].to_numpy(), minlength=n_users)
        offsets = np.zeros(n_users + 1, dtype=np.int64)
        np.cumsum(counts, out=offsets[1:])
        return cls(frame["iid"].to_numpy(dtype=np.int64), offsets)

    def lengths(self) -> np.ndarray:
        return np.diff(self.offsets)

    def row(self, user: int) -> np.ndarray:
        return self.flat[self.offsets[user]:self.offsets[user + 1]]


@dataclass
class EvalSet:
    users: np.ndarray        # uid of every evaluated user
    history: Grouped         # indexed by uid
    target: np.ndarray       # item id per evaluated user, aligned with ``users``


@dataclass
class Split:
    name: str
    n_users: int
    n_items: int
    universe: np.ndarray     # bool mask over items that exist in this setting
    train: Grouped
    refit: Grouped | None    # train + validation events, used for the final test model
    validation: EvalSet
    test: EvalSet


def load_events(data: str) -> tuple[pd.DataFrame, np.ndarray]:
    events = pd.read_parquet(C.EVENTS)
    recommendable = np.load(C.RECOMMENDABLE_MASK)
    if data == "rec":
        events = events[events["rec"]].reset_index(drop=True)
        return events, recommendable
    if data == "all":
        return events, np.ones_like(recommendable)
    raise ValueError(data)


def _first_per_user(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.drop_duplicates("uid", keep="first")   # frame is sorted by uid, ts


def _eval_set(history: Grouped, targets: pd.DataFrame, min_history: int) -> EvalSet:
    users = targets["uid"].to_numpy(dtype=np.int64)
    keep = history.lengths()[users] >= min_history
    return EvalSet(users[keep], history, targets["iid"].to_numpy(dtype=np.int64)[keep])


def build(protocol: str, data: str = "all", min_history: int = C.MIN_HISTORY,
          seed: int = C.SEED) -> Split:
    events, universe = load_events(data)
    n_users = int(pd.read_parquet(C.EVENTS, columns=["uid"])["uid"].max()) + 1
    n_items = universe.size
    name = f"{protocol}-{data}"

    if protocol in LABEL_COLUMN:
        label = events[LABEL_COLUMN[protocol]].to_numpy()
        train_frame = events[label == 0]
        before_test = events[label < 2]
        train = Grouped.from_frame(train_frame, n_users)
        refit_hist = Grouped.from_frame(before_test, n_users)
        validation = _eval_set(train, _first_per_user(events[label == 1]), min_history)
        test = _eval_set(refit_hist, _first_per_user(events[label == 2]), min_history)
        # loo keeps the exp16/17/24 recipe (test model = train-only model); tsp refits on
        # everything before t2 so items first seen between t1 and t2 are not cold at test.
        refit = refit_hist if protocol == "tsp" else None
        return Split(name, n_users, n_items, universe, train, refit, validation, test)

    if protocol == "uh":
        lengths = np.bincount(events["uid"].to_numpy(), minlength=n_users)
        eligible = np.flatnonzero(lengths >= min_history + 1)
        order = np.random.default_rng(seed).permutation(eligible)
        n_test = int(round(0.3 * eligible.size))
        n_val = int(round(0.1 * eligible.size))
        test_users, val_users = np.sort(order[:n_test]), np.sort(order[n_test:n_test + n_val])
        role = np.zeros(n_users, dtype=np.int8)          # 0 train, 1 validation, 2 test
        role[val_users], role[test_users] = 1, 2
        event_role = role[events["uid"].to_numpy()]
        is_last = ~events["uid"].duplicated(keep="last").to_numpy()
        train = Grouped.from_frame(events[event_role == 0], n_users)
        refit = Grouped.from_frame(events[event_role <= 1], n_users)
        held_history = Grouped.from_frame(events[(event_role > 0) & ~is_last], n_users)
        last = events[is_last]
        validation = _eval_set(held_history, last[role[last["uid"].to_numpy()] == 1], min_history)
        test = _eval_set(held_history, last[role[last["uid"].to_numpy()] == 2], min_history)
        return Split(name, n_users, n_items, universe, train, refit, validation, test)

    raise ValueError(protocol)


def trainable_items(grouped: Grouped) -> np.ndarray:
    """Items that occur in a training sequence of length >= 2 (SASRec only learns from
    (input, next) pairs, so an item seen only as a user's single event gets no gradient)."""
    lengths = grouped.lengths()
    owner = np.repeat(np.arange(lengths.size), lengths)
    return np.unique(grouped.flat[lengths[owner] >= 2])
