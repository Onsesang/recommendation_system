from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .common import ROOT, load_json, read_jsonl, save_json
from .simple_m0_m1 import (
    SENTENCE_MODEL,
    SEOYOUNG_TRAIN,
    _bootstrap_delta,
    _embed_claims,
    _evaluate_scores,
    _load_image_features,
    _normalize,
    _product_targets,
    infer_category,
    stable_fraction,
)


DEFAULT_DENSE_ROOT = ROOT / "data" / "dense" / "simple_100x5" / "v2"


def _fold_for_group(group: str, folds: int = 5, seed: int = 7301) -> int:
    return min(int(stable_fraction(group, seed) * folds), folds - 1)


def _dense_claims(root: Path) -> list[dict[str, Any]]:
    claims = []
    for row in read_jsonl(root / "semantic_verifications.jsonl"):
        if row.get("status") != "success" or row.get("accepted") is not True:
            continue
        claim = str(row.get("claim") or row.get("quote") or "").strip()
        if not claim:
            continue
        claims.append(
            {
                "span_id": row["span_id"],
                "review_id": row["review_id"],
                "asin": row["asin"],
                "user_id": row.get("user_id") or f"missing:{row['review_id']}",
                "claim": claim,
                "quote": row["quote"],
            }
        )
    return claims


def run_dense_m0_m1(
    root: Path | None = None, *, augment_sparse: bool = False
) -> dict[str, Any]:
    import joblib
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import StandardScaler

    root = root or DEFAULT_DENSE_ROOT
    claims = _dense_claims(root)
    if not claims:
        raise RuntimeError(f"No accepted semantic verifications in {root}")
    claim_vectors = _embed_claims(claims, "dense_100x5_claim_embeddings.npz")
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
                "fold": _fold_for_group(group),
                "category": infer_category(meta.get("title", "")),
                **target_stats[asin],
            }
        )
    image = np.stack([image_features[row["asin"]] for row in products]).astype("float32")
    material = np.stack([targets[row["asin"]] for row in products]).astype("float32")
    augmentation_products: list[dict[str, Any]] = []
    augmentation_image = np.empty((0, image.shape[1]), dtype="float32")
    augmentation_material = np.empty((0, material.shape[1]), dtype="float32")
    if augment_sparse:
        sparse_product_path = ROOT / "data" / "derived" / "simple_m0_m1" / "products.json"
        sparse_vector_path = (
            ROOT / "data" / "derived" / "simple_m0_m1" / "product_vectors.npz"
        )
        sparse_products = load_json(sparse_product_path)
        sparse_vectors = np.load(sparse_vector_path)
        sparse_asins = [str(value) for value in sparse_vectors["asins"]]
        vector_index = {asin: i for i, asin in enumerate(sparse_asins)}
        dense_asins = {row["asin"] for row in products}
        kept_indices = []
        for row in sparse_products:
            asin = row["asin"]
            if asin in dense_asins or asin not in vector_index or asin not in metadata:
                continue
            meta = metadata[asin]
            augmentation_products.append(
                {
                    "asin": asin,
                    "split_group": str(
                        meta.get("_split_group") or meta.get("parent_asin") or asin
                    ),
                }
            )
            kept_indices.append(vector_index[asin])
        augmentation_image = sparse_vectors["image"][kept_indices].astype("float32")
        augmentation_material = sparse_vectors["material"][kept_indices].astype(
            "float32"
        )
    alphas = (0.1, 1.0, 10.0, 100.0, 1000.0, 10_000.0, 100_000.0)
    combined_per_query: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    fold_rows = []
    artifact_name = "dense_m0_m1_augmented" if augment_sparse else "dense_m0_m1"
    artifact_root = ROOT / "artifacts" / artifact_name
    artifact_root.mkdir(parents=True, exist_ok=True)

    for fold in range(5):
        test = np.array([i for i, row in enumerate(products) if row["fold"] == fold], dtype=int)
        development = np.array(
            [i for i, row in enumerate(products) if row["fold"] != fold], dtype=int
        )
        validation = np.array(
            [
                i
                for i in development
                if stable_fraction(products[i]["split_group"], 9100 + fold) < 0.20
            ],
            dtype=int,
        )
        train = np.array([i for i in development if i not in set(validation)], dtype=int)
        if min(len(train), len(validation), len(test)) == 0:
            raise RuntimeError(
                f"Empty fold partition fold={fold}: train={len(train)}, "
                f"validation={len(validation)}, test={len(test)}"
            )

        test_groups = {products[i]["split_group"] for i in test}
        validation_groups = {products[i]["split_group"] for i in validation}
        augmentation_selection = np.array(
            [
                i
                for i, row in enumerate(augmentation_products)
                if row["split_group"] not in test_groups
                and row["split_group"] not in validation_groups
            ],
            dtype=int,
        )
        augmentation_final = np.array(
            [
                i
                for i, row in enumerate(augmentation_products)
                if row["split_group"] not in test_groups
            ],
            dtype=int,
        )
        selection_image = np.concatenate(
            [image[train], augmentation_image[augmentation_selection]], axis=0
        )
        selection_material_raw = np.concatenate(
            [material[train], augmentation_material[augmentation_selection]], axis=0
        )
        # Keep the evaluation coordinate system fixed to the dense development
        # corpus.  Otherwise merely adding training-only sparse targets changes
        # every relevance score, including the untouched M0 baseline.
        train_mean = material[train].mean(axis=0, keepdims=True)
        centered_selection = _normalize(material - train_mean)
        centered_selection_train = _normalize(selection_material_raw - train_mean)
        selection_scaler = StandardScaler().fit(selection_image)
        x_train = selection_scaler.transform(selection_image)
        x_validation = selection_scaler.transform(image[validation])
        best_alpha = None
        best_score = -float("inf")
        alpha_rows = []
        for alpha in alphas:
            model = Ridge(alpha=alpha).fit(x_train, centered_selection_train)
            prediction = _normalize(model.predict(x_validation))
            score = float(
                (prediction * centered_selection[validation]).sum(axis=1).mean()
            )
            alpha_rows.append({"alpha": alpha, "validation_paired_cosine": score})
            if score > best_score:
                best_score, best_alpha = score, alpha
        assert best_alpha is not None

        final_image = np.concatenate(
            [image[development], augmentation_image[augmentation_final]], axis=0
        )
        final_material_raw = np.concatenate(
            [material[development], augmentation_material[augmentation_final]], axis=0
        )
        development_mean = material[development].mean(axis=0, keepdims=True)
        centered = _normalize(material - development_mean)
        centered_final_train = _normalize(final_material_raw - development_mean)
        scaler = StandardScaler().fit(final_image)
        model = Ridge(alpha=best_alpha).fit(
            scaler.transform(final_image), centered_final_train
        )
        predicted_test = _normalize(model.predict(scaler.transform(image[test])))
        paired_cosine = float((predicted_test * centered[test]).sum(axis=1).mean())
        # The primary M0 must match the stated zero-training baseline.  Scaling
        # fitted on development data is useful as a diagnostic, but it is not
        # "the frozen embedding as-is" and is therefore reported separately.
        candidate_image = _normalize(image[development])
        query_image = _normalize(image[test])
        candidate_image_standardized = _normalize(scaler.transform(image[development]))
        query_image_standardized = _normalize(scaler.transform(image[test]))
        query_categories = [products[i]["category"] for i in test]
        candidate_categories = [products[i]["category"] for i in development]
        rng = np.random.default_rng(42 + fold)
        random_scores = rng.random((len(test), len(development)))
        category_scores = random_scores.copy()
        for query_i, category in enumerate(query_categories):
            mask = np.array([value == category for value in candidate_categories])
            if mask.any():
                category_scores[query_i] = np.where(
                    mask, category_scores[query_i], -np.inf
                )
        score_sets = {
            "random": random_scores,
            "category_only": category_scores,
            "m0_frozen_image": query_image @ candidate_image.T,
            "m0_standardized_image_diagnostic": (
                query_image_standardized @ candidate_image_standardized.T
            ),
            "m1_ridge_regression": predicted_test @ centered[development].T,
        }
        fold_methods = {}
        for name, scores in score_sets.items():
            fold_methods[name], per_query = _evaluate_scores(
                scores,
                centered[test],
                centered[development],
                query_categories,
                candidate_categories,
            )
            for metric, values in per_query.items():
                combined_per_query[name][metric].extend(values)
        joblib.dump(
            {
                "scaler": scaler,
                "model": model,
                "material_mean": development_mean,
                "sentence_model": SENTENCE_MODEL,
                "best_alpha": best_alpha,
            },
            artifact_root / f"fold_{fold}.joblib",
        )
        fold_rows.append(
            {
                "fold": fold,
                "train": len(train) + len(augmentation_selection),
                "train_dense": len(train),
                "train_augmentation": len(augmentation_selection),
                "final_augmentation": len(augmentation_final),
                "validation": len(validation),
                "test": len(test),
                "best_alpha": best_alpha,
                "best_validation_paired_cosine": best_score,
                "test_paired_cosine": paired_cosine,
                "alpha_selection": alpha_rows,
                "methods": fold_methods,
            }
        )

    methods = {
        name: {
            metric: float(np.mean(values))
            for metric, values in metrics.items()
            if values
        }
        for name, metrics in combined_per_query.items()
    }
    deltas = {
        metric: _bootstrap_delta(
            combined_per_query["m0_frozen_image"][metric],
            combined_per_query["m1_ridge_regression"][metric],
            seed=73,
        )
        for metric in ("material_cosine@5", "ndcg@5", "same_category_material_cosine@5")
    }
    source_reviews = read_jsonl(root.parent / "reviews_product_dense.jsonl")
    accepted_users = defaultdict(set)
    for claim in claims:
        accepted_users[claim["asin"]].add(claim["user_id"])
    metrics = {
        "status": "complete",
        "protocol": {
            "purpose": "review-dense 5-fold M0 vs M1 follow-up; GNN excluded",
            "protected_test_used": False,
            "outer_split": "5-fold deterministic split_group holdout",
            "inner_selection": "group-safe validation for ridge alpha",
            "one_user_one_vote": True,
            "sentence_model": SENTENCE_MODEL,
            "target_postprocessing": "outer-development BGE mean removal and L2 normalization",
            "image_features": "cached frozen Qwen DTD pooled features (1152d)",
            "m0_definition": "raw frozen image features with L2 normalization only",
            "standardized_image_baseline": "diagnostic only; not used for M1-minus-M0 inference",
            "label_source": "Qwen v2 accepted pseudo-labels; human-audited precision estimate 93.8%",
            "training_augmentation": (
                "human-corrected sparse pilot products, fold-group filtered; dense products only evaluated"
                if augment_sparse
                else "none"
            ),
        },
        "data": {
            "source_reviews": len(source_reviews),
            "source_products": len({row["asin"] for row in source_reviews}),
            "accepted_claims": len(claims),
            "target_products": len(targets),
            "usable_products": len(products),
            "accepted_user_count_distribution": dict(
                Counter(len(accepted_users[row["asin"]]) for row in products)
            ),
            "claim_count_distribution": dict(Counter(row["claims"] for row in products)),
            "categories": dict(Counter(row["category"] for row in products)),
            "fold_test_counts": dict(Counter(row["fold"] for row in products)),
            "augmentation_products": len(augmentation_products),
        },
        "folds": fold_rows,
        "methods": methods,
        "m1_minus_m0_bootstrap": deltas,
        "mean_test_paired_cosine": float(
            np.average(
                [row["test_paired_cosine"] for row in fold_rows],
                weights=[row["test"] for row in fold_rows],
            )
        ),
    }
    experiment_name = "08_dense_m0_m1_augmented" if augment_sparse else "07_dense_m0_m1"
    result_root = ROOT / "experiments" / experiment_name / "results"
    save_json(result_root / "metrics.json", metrics)
    save_json(ROOT / "data" / "derived" / "dense_m0_m1" / "products.json", products)
    return metrics
