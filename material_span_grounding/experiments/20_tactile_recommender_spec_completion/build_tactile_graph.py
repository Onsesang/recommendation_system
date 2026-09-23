"""Build the dedicated frozen Last2 tactile graph with an exact-neighbor audit."""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import torch

from common import ART, CLASSES, DATA, EXP16, ROOT, SEED, event, load_json, save_json, sha


def l2_normalize(x: np.ndarray, mask: np.ndarray) -> np.ndarray:
    out = np.zeros_like(x, dtype=np.float32)
    denom = np.linalg.norm(x[mask], axis=1, keepdims=True)
    out[mask] = x[mask] / np.maximum(denom, 1e-12)
    return out


def load_tactile_features(shuffle: bool = False) -> tuple[np.ndarray, np.ndarray]:
    catalog = pd.read_parquet(EXP16 / "data/catalog.parquet")
    profiles = pd.read_parquet(EXP16 / "artifacts/product_tactile_profiles.parquet")
    values = np.zeros((len(catalog), len(CLASSES)), dtype=np.float32)
    available = np.zeros(len(catalog), dtype=bool)
    ids = profiles.iid.to_numpy(dtype=np.int64)
    values[ids] = profiles[CLASSES].to_numpy(dtype=np.float32)
    available[ids] = True
    if not shuffle:
        return values, available
    mapping = pd.read_parquet(ART / "tactile_shuffle_mapping.parquet")
    shuffled = np.zeros_like(values)
    shuffled[mapping.target_iid.to_numpy()] = values[mapping.source_iid.to_numpy()]
    return shuffled, available


def make_shuffle_mapping() -> dict:
    catalog = pd.read_parquet(EXP16 / "data/catalog.parquet", columns=["iid", "train_count"])
    meta = pd.read_parquet(EXP16 / "data/item_metadata.parquet", columns=["iid", "category"])
    _, available = load_tactile_features(False)
    frame = catalog.merge(meta, on="iid", how="left")
    bins = pd.cut(
        frame.train_count,
        bins=[-1, 0, 5, 10, np.inf],
        labels=["0", "1_to_5", "6_to_10", "11_plus"],
    ).astype(str)
    rows = []
    fixed = 0
    for (cat, bucket), g in frame[available].assign(bucket=bins[available]).groupby(["category", "bucket"], sort=True):
        target = np.sort(g.iid.to_numpy(dtype=np.int64))
        material = f"{SEED}|{cat}|{bucket}".encode()
        seed = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
        source = target[np.random.default_rng(seed).permutation(len(target))]
        fixed += int((source == target).sum())
        rows.append(pd.DataFrame({"target_iid": target, "source_iid": source, "category": cat, "train_count_bucket": bucket}))
    mapping = pd.concat(rows, ignore_index=True)
    path = ART / "tactile_shuffle_mapping.parquet"
    tmp = path.with_suffix(path.suffix + ".tmp")
    mapping.to_parquet(tmp, index=False)
    tmp.replace(path)
    return {"rows": int(len(mapping)), "fixed_points": fixed, "sha256": sha(path)}


def exact_recall_audit(vectors: np.ndarray, ids: np.ndarray, nprobe: int) -> dict:
    import faiss

    dim = vectors.shape[1]
    rng = np.random.default_rng(SEED)
    sample = np.sort(rng.choice(ids, size=min(1000, len(ids)), replace=False))
    exact = faiss.IndexFlatIP(dim)
    exact.add(vectors[ids])
    exact_score, exact_local = exact.search(vectors[sample], 41)
    exact_ids = ids[exact_local]
    exact_ids = np.array([row[row != q][:40] for q, row in zip(sample, exact_ids)])
    nlist = min(7270, max(256, int(np.sqrt(len(ids)) * 8)))
    index = faiss.IndexIVFFlat(faiss.IndexFlatIP(dim), dim, nlist, faiss.METRIC_INNER_PRODUCT)
    train_sample = ids[rng.choice(len(ids), size=min(150000, len(ids)), replace=False)]
    index.train(vectors[train_sample])
    index.nprobe = nprobe
    for start in range(0, len(ids), 50000):
        index.add_with_ids(vectors[ids[start : start + 50000]], ids[start : start + 50000])
    approx_score, approx = index.search(vectors[sample], 41)
    recalls = []
    for q, want, got in zip(sample, exact_ids, approx):
        got = got[got != q][:40]
        recalls.append(len(set(map(int, want)).intersection(map(int, got))) / 40)
    return {
        "nprobe": nprobe,
        "mean_recall_at_40": float(np.mean(recalls)),
        "min_recall_at_40": float(np.min(recalls)),
        "query_sample": int(len(sample)),
        "nlist": int(nlist),
        "index_training_sample": int(len(train_sample)),
        "faiss_version": faiss.__version__,
    }


def build_graph(vectors: np.ndarray, available: np.ndarray, nprobe: int, dest: str) -> dict:
    import faiss

    ids = np.flatnonzero(available).astype("int64")
    dim = vectors.shape[1]
    nlist = min(7270, max(256, int(np.sqrt(len(ids)) * 8)))
    index = faiss.IndexIVFFlat(faiss.IndexFlatIP(dim), dim, nlist, faiss.METRIC_INNER_PRODUCT)
    rng = np.random.default_rng(SEED)
    train_sample = ids[rng.choice(len(ids), size=min(150000, len(ids)), replace=False)]
    index.train(vectors[train_sample])
    index.nprobe = nprobe
    for start in range(0, len(ids), 50000):
        index.add_with_ids(vectors[ids[start : start + 50000]], ids[start : start + 50000])
    src = []
    dst = []
    weight = []
    for start in range(0, len(ids), 10000):
        qids = ids[start : start + 10000]
        score, neighbor = index.search(vectors[qids], 41)
        for j, q in enumerate(qids):
            keep = neighbor[j] != q
            nn = neighbor[j][keep][:40]
            ss = score[j][keep][:40]
            valid = nn >= 0
            src.append(np.full(valid.sum(), q, dtype="int64"))
            dst.append(nn[valid])
            weight.append(np.maximum(ss[valid], 0).astype("float32"))
        if start % 100000 == 0:
            event("tactile_graph", "progress", done=int(min(start + 10000, len(ids))), total=int(len(ids)))
    src = np.concatenate(src)
    dst = np.concatenate(dst)
    weight = np.concatenate(weight)
    src2 = np.concatenate([src, dst])
    dst2 = np.concatenate([dst, src])
    weight2 = np.concatenate([weight, weight])
    deg = np.bincount(src2, weights=weight2, minlength=len(vectors))
    norm = weight2 / np.sqrt(np.maximum(deg[src2], 1e-12) * np.maximum(deg[dst2], 1e-12))
    graph = torch.sparse_coo_tensor(
        torch.tensor(np.stack([src2, dst2]), dtype=torch.long),
        torch.tensor(norm, dtype=torch.float32),
        (len(vectors), len(vectors)),
    ).coalesce()
    path = DATA / dest
    tmp = path.with_suffix(".tmp")
    torch.save(graph, tmp)
    tmp.replace(path)
    return {
        "path": str(path),
        "sha256": sha(path),
        "nodes": int(len(vectors)),
        "feature_items": int(available.sum()),
        "directed_edges_before_symmetrization": int(len(src)),
        "nprobe": int(nprobe),
        "nlist": int(nlist),
        "k": 40,
        "self_edges_removed": True,
        "negative_cosine_clamped_to_zero": True,
        "reverse_edges_added": True,
        "symmetric_renormalization": True,
    }


def main() -> None:
    manifest = load_json(ART / "input_manifest.json")
    if manifest.get("status") != "complete":
        raise RuntimeError("freeze_inputs.py must complete first")
    event("tactile_graph", "started")
    DATA.mkdir(parents=True, exist_ok=True)
    values, available = load_tactile_features(False)
    vectors = l2_normalize(values, available)
    np.save(DATA / "tactile_feat_14.npy", values)
    np.save(DATA / "tactile_available.npy", available)
    audit_rows = []
    selected = None
    for nprobe in load_json(ROOT / "configs/protocol.json")["tactile_graph"]["exact_recall_audit"]["nprobe_escalation"]:
        row = exact_recall_audit(vectors, np.flatnonzero(available).astype("int64"), int(nprobe))
        audit_rows.append(row)
        event("tactile_graph_audit", "progress", nprobe=int(nprobe), mean_recall_at_40=row["mean_recall_at_40"])
        if row["mean_recall_at_40"] >= 0.95 and selected is None:
            selected = int(nprobe)
            break
    if selected is None:
        save_json(ART / "tactile_graph_audit.json", {"status": "blocked", "attempts": audit_rows})
        event("tactile_graph", "blocked", reason="exact_recall_below_0.95")
        raise SystemExit("tactile graph blocked: exact recall below threshold")
    graph = build_graph(vectors, available, selected, "tactile_adj_40_True.pt")
    shuffle = make_shuffle_mapping()
    shuffled, _ = load_tactile_features(True)
    np.save(DATA / "tactile_feat_14_shuffled.npy", shuffled)
    result = {
        "status": "complete",
        "input": "frozen continuous 14D Last2 probability",
        "feature_sha256": sha(DATA / "tactile_feat_14.npy"),
        "available_sha256": sha(DATA / "tactile_available.npy"),
        "shuffled_feature_sha256": sha(DATA / "tactile_feat_14_shuffled.npy"),
        "audit": audit_rows,
        "selected_nprobe": selected,
        "graph": graph,
        "shuffle_mapping": shuffle,
    }
    save_json(ART / "tactile_graph_report.json", result)
    event("tactile_graph", "complete", selected_nprobe=selected, feature_items=int(available.sum()))


if __name__ == "__main__":
    main()
