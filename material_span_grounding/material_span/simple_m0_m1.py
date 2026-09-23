from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .common import ROOT, load_json, read_jsonl, save_json, sha256_text


TEXTURE_ROOT = Path("/home/user/onsesang/texture_project")
SEOYOUNG_TRAIN = Path("/home/user/onsesang/seoyoung/data/splits/train.json")
SENTENCE_MODEL = "BAAI/bge-small-en-v1.5"

CATEGORY_RULES = [
    ("dress", ("dress", "gown")),
    ("top", ("shirt", "tee", "top", "blouse", "tank")),
    ("sweater", ("sweater", "cardigan", "pullover", "hoodie", "sweatshirt")),
    ("pants", ("pants", "legging", "jean", "trouser", "jogger")),
    ("skirt", ("skirt",)),
    ("outerwear", ("jacket", "coat", "vest")),
    ("sleepwear", ("pajama", "sleepwear", "robe", "nightgown")),
    ("underwear", ("bra", "underwear", "lingerie", "sock")),
    ("swimwear", ("swim", "bikini", "tankini")),
    ("accessory", ("scarf", "hat", "cap", "beanie", "mask", "belt")),
]


def infer_category(title: str) -> str:
    text = (title or "").casefold()
    for category, words in CATEGORY_RULES:
        if any(word in text for word in words):
            return category
    return "other"


def stable_fraction(value: str, seed: int) -> float:
    digest = hashlib.sha256(f"{seed}\x1f{value}".encode()).hexdigest()
    return int(digest[:16], 16) / float(16**16)


def split_name(group: str, seed: int = 4201) -> str:
    fraction = stable_fraction(group, seed)
    return "train" if fraction < 0.70 else "validation" if fraction < 0.85 else "test"


def _human_corrected_claims() -> tuple[list[dict[str, Any]], dict[str, int]]:
    verifications = read_jsonl(ROOT / "data" / "v2" / "semantic_verifications.jsonl")
    audit_path = ROOT / "audit_app" / "data" / "v2_100" / "annotations.json"
    annotations = load_json(audit_path).get("annotations", {}) if audit_path.exists() else {}
    claims = []
    counters: Counter[str] = Counter()
    for row in verifications:
        annotation = annotations.get(row["span_id"])
        if annotation is not None:
            accepted = bool(annotation.get("human_accepted"))
            counters["human_overrides"] += 1
            if accepted != bool(row.get("accepted")):
                counters["human_decision_changes"] += 1
            claim = str(annotation.get("human_claim") or row.get("claim") or row["quote"]).strip()
        else:
            accepted = row.get("accepted") is True
            claim = str(row.get("claim") or row["quote"]).strip()
        if not accepted or not claim:
            counters["rejected"] += 1
            continue
        claims.append(
            {
                "span_id": row["span_id"],
                "review_id": row["review_id"],
                "asin": row["asin"],
                "user_id": row.get("user_id") or f"missing:{row['review_id']}",
                "claim": claim,
                "quote": row["quote"],
                "scope": annotation.get("human_scope") if annotation else row.get("scope"),
                "property_status": annotation.get("human_property_status")
                if annotation
                else row.get("property_status"),
                "visual_observability": annotation.get("human_visual_observability")
                if annotation
                else row.get("visual_observability"),
                "human_audited": annotation is not None,
            }
        )
        counters["accepted"] += 1
    return claims, dict(counters)


def _load_image_features() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    import numpy as np

    cache = np.load(TEXTURE_ROOT / "data" / "probe_features.npz", allow_pickle=True)
    features: dict[str, Any] = {}
    records: dict[str, dict[str, Any]] = {}
    for name in ("train", "val", "test"):
        rows = load_json(TEXTURE_ROOT / "data" / f"texture_{name}.json")
        kept = cache[f"keep_{name}"]
        vectors = cache[f"X_{name}"]
        for vector_i, source_i in enumerate(kept):
            row = rows[int(source_i)]
            features[row["asin"]] = vectors[vector_i].astype("float32")
            records[row["asin"]] = row
    return features, records


def _normalize(array: Any) -> Any:
    import numpy as np

    denom = np.linalg.norm(array, axis=1, keepdims=True)
    return array / np.clip(denom, 1e-12, None)


def _embed_claims(
    claims: list[dict[str, Any]], cache_name: str = "claim_embeddings.npz"
) -> Any:
    import numpy as np
    from sentence_transformers import SentenceTransformer

    texts = [row["claim"] for row in claims]
    fingerprint = sha256_text(
        json.dumps([(row["span_id"], row["claim"]) for row in claims], ensure_ascii=False)
    )
    cache_path = ROOT / "data" / "derived" / "simple_m0_m1" / cache_name
    if cache_path.exists():
        cache = np.load(cache_path)
        if str(cache["fingerprint"].item()) == fingerprint and len(cache["vectors"]) == len(texts):
            return cache["vectors"].astype("float32")
    model = SentenceTransformer(SENTENCE_MODEL, local_files_only=True)
    vectors = model.encode(
        texts,
        batch_size=64,
        show_progress_bar=True,
        normalize_embeddings=True,
    ).astype("float32")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, fingerprint=fingerprint, vectors=vectors)
    return vectors


def _product_targets(
    claims: list[dict[str, Any]], claim_vectors: Any
) -> tuple[dict[str, Any], dict[str, dict[str, int]]]:
    import numpy as np

    by_product_user: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for index, row in enumerate(claims):
        by_product_user[row["asin"]][row["user_id"]].append(index)
    targets: dict[str, Any] = {}
    stats: dict[str, dict[str, int]] = {}
    for asin, users in by_product_user.items():
        user_vectors = []
        for indices in users.values():
            unique_indices = []
            seen = set()
            for index in indices:
                key = claims[index]["claim"].casefold().strip()
                if key not in seen:
                    seen.add(key)
                    unique_indices.append(index)
            user_vector = claim_vectors[unique_indices].mean(axis=0)
            user_vector /= max(float(np.linalg.norm(user_vector)), 1e-12)
            user_vectors.append(user_vector)
        product = np.stack(user_vectors).mean(axis=0)
        product /= max(float(np.linalg.norm(product)), 1e-12)
        targets[asin] = product.astype("float32")
        stats[asin] = {
            "claims": sum(len(indices) for indices in users.values()),
            "users": len(users),
        }
    return targets, stats


def _ndcg(relevance: Any, order: Any, k: int) -> float:
    import numpy as np

    chosen = np.clip(relevance[order[:k]], 0.0, 1.0)
    discounts = 1.0 / np.log2(np.arange(2, len(chosen) + 2))
    dcg = float((chosen * discounts).sum())
    ideal = np.sort(np.clip(relevance, 0.0, 1.0))[::-1][:k]
    idcg = float((ideal * discounts[: len(ideal)]).sum())
    return dcg / idcg if idcg > 0 else 0.0


def _evaluate_scores(
    scores: Any,
    query_targets: Any,
    candidate_targets: Any,
    query_categories: list[str],
    candidate_categories: list[str],
    top_ks: tuple[int, ...] = (1, 5, 10),
) -> tuple[dict[str, float], dict[str, list[float]]]:
    import numpy as np

    material_scores = query_targets @ candidate_targets.T
    per_query: dict[str, list[float]] = defaultdict(list)
    for query_i in range(len(scores)):
        order = np.argsort(-scores[query_i])
        raw_relevance = material_scores[query_i]
        relevance = (raw_relevance - raw_relevance.min()) / max(
            float(raw_relevance.max() - raw_relevance.min()), 1e-12
        )
        relevant = set(np.argsort(-raw_relevance)[: max(1, len(order) // 10)])
        for k in top_ks:
            top = order[:k]
            per_query[f"material_cosine@{k}"].append(float(raw_relevance[top].mean()))
            per_query[f"ndcg@{k}"].append(_ndcg(relevance, order, k))
            per_query[f"recall_top10pct@{k}"].append(len(relevant & set(top)) / len(relevant))
        same = np.array(
            [category == query_categories[query_i] for category in candidate_categories]
        )
        if int(same.sum()) >= 3:
            same_order = np.argsort(-np.where(same, scores[query_i], -np.inf))
            k = min(5, int(same.sum()))
            per_query["same_category_material_cosine@5"].append(
                float(raw_relevance[same_order[:k]].mean())
            )
    metrics = {key: float(np.mean(values)) for key, values in per_query.items() if values}
    return metrics, dict(per_query)


def _bootstrap_delta(
    baseline: list[float], method: list[float], seed: int = 42, samples: int = 5000
) -> dict[str, float]:
    import numpy as np

    base = np.asarray(baseline, dtype="float64")
    other = np.asarray(method, dtype="float64")
    if len(base) != len(other) or not len(base):
        return {"delta": float("nan"), "ci95_low": float("nan"), "ci95_high": float("nan")}
    differences = other - base
    rng = np.random.default_rng(seed)
    draws = differences[rng.integers(0, len(differences), size=(samples, len(differences)))].mean(axis=1)
    return {
        "delta": float(differences.mean()),
        "ci95_low": float(np.quantile(draws, 0.025)),
        "ci95_high": float(np.quantile(draws, 0.975)),
        "probability_positive": float((draws > 0).mean()),
    }


def run_simple_m0_m1() -> dict[str, Any]:
    import joblib
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    claims, correction_stats = _human_corrected_claims()
    claim_vectors = _embed_claims(claims)
    targets, target_stats = _product_targets(claims, claim_vectors)
    image_features, image_records = _load_image_features()
    metadata = {row["asin"]: row for row in load_json(SEOYOUNG_TRAIN)}

    products = []
    for asin in sorted(set(targets) & set(image_features) & set(metadata)):
        meta = metadata[asin]
        group = str(meta.get("_split_group") or meta.get("parent_asin") or asin)
        products.append(
            {
                "asin": asin,
                "title": meta.get("title") or image_records.get(asin, {}).get("title", ""),
                "parent_asin": meta.get("parent_asin") or asin,
                "split_group": group,
                "split": split_name(group),
                "category": infer_category(meta.get("title", "")),
                **target_stats[asin],
            }
        )
    image = np.stack([image_features[row["asin"]] for row in products]).astype("float32")
    material = np.stack([targets[row["asin"]] for row in products]).astype("float32")
    indices = {
        name: np.array([i for i, row in enumerate(products) if row["split"] == name], dtype=int)
        for name in ("train", "validation", "test")
    }
    train, validation, test = (indices[name] for name in ("train", "validation", "test"))
    if min(len(train), len(validation), len(test)) == 0:
        raise RuntimeError(f"Empty split: { {key: len(value) for key, value in indices.items()} }")

    # BGE sentence embeddings have a strong shared mean direction. Remove it using
    # train-only statistics so random product similarities do not look artificially high.
    train_material_mean = material[train].mean(axis=0, keepdims=True)
    centered_for_selection = _normalize(material - train_material_mean)

    # Select ridge strength using validation only.
    scaler = StandardScaler().fit(image[train])
    x_train = scaler.transform(image[train])
    x_validation = scaler.transform(image[validation])
    alpha_rows = []
    best_alpha = None
    best_score = -float("inf")
    for alpha in (0.1, 1.0, 10.0, 100.0, 1000.0, 10_000.0, 100_000.0):
        model = Ridge(alpha=alpha).fit(x_train, centered_for_selection[train])
        prediction = _normalize(model.predict(x_validation))
        score = float(
            (prediction * centered_for_selection[validation]).sum(axis=1).mean()
        )
        alpha_rows.append({"alpha": alpha, "validation_paired_cosine": score})
        if score > best_score:
            best_score, best_alpha = score, alpha
    assert best_alpha is not None

    development = np.concatenate([train, validation])
    development_material_mean = material[development].mean(axis=0, keepdims=True)
    centered_material = _normalize(material - development_material_mean)
    final_scaler = StandardScaler().fit(image[development])
    final_model = Ridge(alpha=best_alpha).fit(
        final_scaler.transform(image[development]), centered_material[development]
    )
    predicted_test = _normalize(final_model.predict(final_scaler.transform(image[test])))
    paired_test_cosine = float(
        (predicted_test * centered_material[test]).sum(axis=1).mean()
    )

    # M0 is the literal no-training baseline: use the frozen Qwen vectors as-is
    # apart from the cosine-search L2 normalization.  Keep the development-fitted
    # standardized variant as a diagnostic, but do not call it the M0 baseline.
    candidate_image = _normalize(image[development])
    query_image = _normalize(image[test])
    candidate_image_standardized = _normalize(final_scaler.transform(image[development]))
    query_image_standardized = _normalize(final_scaler.transform(image[test]))
    candidate_target = centered_material[development]
    query_target = centered_material[test]
    query_categories = [products[i]["category"] for i in test]
    candidate_categories = [products[i]["category"] for i in development]

    rng = np.random.default_rng(42)
    random_scores = rng.random((len(test), len(development)))
    category_scores = random_scores.copy()
    for query_i, category in enumerate(query_categories):
        mask = np.array([candidate == category for candidate in candidate_categories])
        if mask.any():
            category_scores[query_i] = np.where(mask, category_scores[query_i], -np.inf)
    frozen_scores = query_image @ candidate_image.T
    standardized_frozen_scores = (
        query_image_standardized @ candidate_image_standardized.T
    )
    regression_scores = predicted_test @ candidate_target.T

    method_scores = {
        "random": random_scores,
        "category_only": category_scores,
        "m0_frozen_image": frozen_scores,
        "m0_standardized_image_diagnostic": standardized_frozen_scores,
        "m1_ridge_regression": regression_scores,
    }
    methods = {}
    per_query = {}
    for name, scores in method_scores.items():
        methods[name], per_query[name] = _evaluate_scores(
            scores,
            query_target,
            candidate_target,
            query_categories,
            candidate_categories,
        )
    deltas = {
        metric: _bootstrap_delta(
            per_query["m0_frozen_image"][metric],
            per_query["m1_ridge_regression"][metric],
            seed=42,
        )
        for metric in ("material_cosine@5", "ndcg@5", "same_category_material_cosine@5")
    }

    artifact_root = ROOT / "artifacts" / "simple_m0_m1"
    artifact_root.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "scaler": final_scaler,
            "model": final_model,
            "sentence_model": SENTENCE_MODEL,
            "best_alpha": best_alpha,
        },
        artifact_root / "m1_ridge.joblib",
    )
    derived_root = ROOT / "data" / "derived" / "simple_m0_m1"
    derived_root.mkdir(parents=True, exist_ok=True)
    save_json(derived_root / "products.json", products)
    np.savez_compressed(
        derived_root / "product_vectors.npz",
        asins=np.array([row["asin"] for row in products]),
        image=image,
        material=material,
    )

    metrics = {
        "status": "complete",
        "protocol": {
            "purpose": "small M0 vs M1 feasibility experiment before GNN",
            "protected_test_used": False,
            "split": "deterministic group-safe 70/15/15 within official train products",
            "candidate_pool": "train + validation products; test products are queries only",
            "human_overrides_applied": True,
            "one_user_one_vote": True,
            "semantic_deduplication": "exact normalized claim within user",
            "sentence_model": SENTENCE_MODEL,
            "target_postprocessing": "subtract development-only BGE mean and L2 normalize",
            "image_features": "cached frozen Qwen DTD pooled features (1152d)",
            "m0_definition": "raw frozen image features with L2 normalization only",
            "standardized_image_baseline": "diagnostic only; not used for M1-minus-M0 inference",
        },
        "data": {
            "verified_claim_rows": len(claims),
            "target_products": len(targets),
            "usable_products": len(products),
            "split_counts": {key: len(value) for key, value in indices.items()},
            "claim_count_distribution": dict(Counter(row["claims"] for row in products)),
            "user_count_distribution": dict(Counter(row["users"] for row in products)),
            "categories": dict(Counter(row["category"] for row in products)),
            "human_correction_stats": correction_stats,
            "raw_material_off_diagonal_cosine": float(
                (
                    material @ material.T
                )[~np.eye(len(material), dtype=bool)].mean()
            ),
            "centered_material_off_diagonal_cosine": float(
                (
                    centered_material @ centered_material.T
                )[~np.eye(len(centered_material), dtype=bool)].mean()
            ),
        },
        "m1_training": {
            "model": "StandardScaler + multi-output Ridge",
            "alpha_selection": alpha_rows,
            "best_alpha": best_alpha,
            "best_validation_paired_cosine": best_score,
            "test_paired_cosine": paired_test_cosine,
        },
        "methods": methods,
        "m1_minus_m0_bootstrap": deltas,
    }
    result_root = ROOT / "experiments" / "06_simple_m0_m1" / "results"
    save_json(result_root / "metrics.json", metrics)
    return metrics
