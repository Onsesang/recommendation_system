"""Synthetic implementation test; never reads official validation/test targets."""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp
import torch

from common import ART, event, save_json


def main() -> None:
    event("synthetic_dry_run", "started")
    rng = np.random.default_rng(20260904)
    n_items = 12
    values = rng.random((n_items, 14), dtype=np.float32)
    available = np.ones(n_items, dtype=bool)
    norm = values / np.maximum(np.linalg.norm(values, axis=1, keepdims=True), 1e-12)
    sim = norm @ norm.T
    np.fill_diagonal(sim, -np.inf)
    top = np.argsort(-sim, axis=1)[:, :3]
    assert top.shape == (n_items, 3)
    row = np.repeat(np.arange(n_items), 3)
    col = top.reshape(-1)
    weight = np.maximum(sim[row, col], 0).astype("float32")
    src = np.concatenate([row, col])
    dst = np.concatenate([col, row])
    val = np.concatenate([weight, weight])
    deg = np.bincount(src, weights=val, minlength=n_items)
    adj = torch.sparse_coo_tensor(
        torch.tensor(np.stack([src, dst]), dtype=torch.long),
        torch.tensor(val / np.sqrt(np.maximum(deg[src], 1e-12) * np.maximum(deg[dst], 1e-12)), dtype=torch.float32),
        (n_items, n_items),
    ).coalesce()
    out = torch.sparse.mm(adj, torch.tensor(values))
    if not torch.isfinite(out).all():
        raise FloatingPointError("synthetic tactile graph produced non-finite values")
    result = {
        "status": "pass",
        "official_validation_metrics_computed": False,
        "official_test_metrics_computed": False,
        "synthetic_items": n_items,
        "synthetic_edges": int(adj._nnz()),
    }
    save_json(ART / "synthetic_dry_run.json", result)
    event("synthetic_dry_run", "complete", synthetic_edges=int(adj._nnz()))


if __name__ == "__main__":
    main()
