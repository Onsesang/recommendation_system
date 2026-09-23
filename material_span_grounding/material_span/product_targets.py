from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import ROOT, load_json, read_jsonl, save_json, sha256_file, sha256_text, write_jsonl
from .simple_m0_m1 import SEOYOUNG_TRAIN, SENTENCE_MODEL, infer_category


DEFAULT_INPUT_ROOT = ROOT / "data" / "vllm" / "dense_500" / "v2_1_ai_recall"
DEFAULT_OUTPUT_ROOT = ROOT / "data" / "derived" / "dense_500_v2_1_targets"
DEFAULT_SOURCE_REVIEWS = ROOT / "data" / "dense" / "reviews_product_dense.jsonl"


def _accepted_claims(input_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    run_path = input_root / "verification_run.json"
    run = load_json(run_path)
    if run.get("status") != "complete":
        raise RuntimeError(f"Semantic verification is not complete: {run.get('status')}")
    source_path = input_root / "semantic_verifications.jsonl"
    rows = read_jsonl(source_path)
    if len(rows) != int(run["input_spans"]):
        raise RuntimeError("Verification row count does not match verification_run.json")
    if sha256_file(source_path) != run["output_sha256"]:
        raise RuntimeError("Verification output SHA-256 does not match its manifest")
    failures = [row["span_id"] for row in rows if row.get("status") != "success"]
    if failures:
        raise RuntimeError(f"Schema failures remain: {failures[:5]}")

    claims = []
    for row in rows:
        if row.get("accepted") is not True:
            continue
        claim = str(row.get("claim") or row.get("quote") or "").strip()
        if not claim:
            raise RuntimeError(f"Accepted span has an empty claim: {row['span_id']}")
        claims.append(
            {
                "span_id": row["span_id"],
                "review_id": row["review_id"],
                "asin": row["asin"],
                "user_id": row.get("user_id") or f"missing:{row['review_id']}",
                "claim": claim,
                "quote": row["quote"],
                "scope": row.get("scope") or "unknown",
                "property_status": row.get("property_status") or "unknown",
                "intensity": row.get("intensity") or "unknown",
                "sentiment": row.get("sentiment") or "unknown",
                "evidence_basis": row.get("evidence_basis") or "unspecified",
                "visual_observability": row.get("visual_observability") or "unknown",
                "semantic_guardrail": row.get("semantic_guardrail"),
            }
        )
    if len(claims) != int(run["accepted"]):
        raise RuntimeError("Accepted claim count does not match verification_run.json")
    return claims, run


def _embed_claims(
    claims: list[dict[str, Any]], cache_path: Path
) -> tuple[Any, str, bool]:
    import numpy as np
    from sentence_transformers import SentenceTransformer

    texts = [row["claim"] for row in claims]
    fingerprint = sha256_text(
        json.dumps(
            [(row["span_id"], row["claim"]) for row in claims],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    if cache_path.is_file():
        cache = np.load(cache_path, allow_pickle=False)
        if (
            str(cache["fingerprint"].item()) == fingerprint
            and len(cache["vectors"]) == len(claims)
        ):
            return cache["vectors"].astype("float32"), fingerprint, True

    model = SentenceTransformer(SENTENCE_MODEL, local_files_only=True)
    vectors = model.encode(
        texts,
        batch_size=64,
        show_progress_bar=True,
        normalize_embeddings=True,
    ).astype("float32")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, fingerprint=fingerprint, vectors=vectors)
    return vectors, fingerprint, False


def aggregate_product_targets(
    claims: list[dict[str, Any]], claim_vectors: Any
) -> tuple[dict[str, Any], dict[str, dict[str, int]]]:
    import numpy as np

    if len(claims) != len(claim_vectors):
        raise ValueError("Claim metadata and vector counts do not match")
    by_product_user: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for index, row in enumerate(claims):
        by_product_user[str(row["asin"])][str(row["user_id"])].append(index)

    targets: dict[str, Any] = {}
    stats: dict[str, dict[str, int]] = {}
    for asin, users in by_product_user.items():
        user_vectors = []
        deduplicated_claims = 0
        review_ids: set[str] = set()
        for indices in users.values():
            unique_indices = []
            seen: set[str] = set()
            for index in indices:
                review_ids.add(str(claims[index]["review_id"]))
                key = str(claims[index]["claim"]).casefold().strip()
                if key in seen:
                    continue
                seen.add(key)
                unique_indices.append(index)
            deduplicated_claims += len(unique_indices)
            user_vector = np.asarray(claim_vectors[unique_indices]).mean(axis=0)
            user_vector /= max(float(np.linalg.norm(user_vector)), 1e-12)
            user_vectors.append(user_vector)
        product_vector = np.stack(user_vectors).mean(axis=0)
        product_vector /= max(float(np.linalg.norm(product_vector)), 1e-12)
        targets[asin] = product_vector.astype("float32")
        stats[asin] = {
            "raw_claims": sum(len(indices) for indices in users.values()),
            "deduplicated_user_claims": deduplicated_claims,
            "users": len(users),
            "reviews": len(review_ids),
        }
    return targets, stats


def _build_evidence(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in claims:
        asin = str(row["asin"])
        key = row["claim"].casefold().strip()
        entry = grouped[asin].setdefault(
            key,
            {
                "claim": row["claim"],
                "scope": row["scope"],
                "property_status": row["property_status"],
                "intensity": row["intensity"],
                "sentiment": row["sentiment"],
                "evidence_basis": row["evidence_basis"],
                "visual_observability": row["visual_observability"],
                "quotes": [],
                "review_ids": [],
                "span_ids": [],
                "_users": set(),
            },
        )
        for field, value in (
            ("quotes", row["quote"]),
            ("review_ids", row["review_id"]),
            ("span_ids", row["span_id"]),
        ):
            if value not in entry[field]:
                entry[field].append(value)
        entry["_users"].add(str(row["user_id"]))

    output = []
    for asin in sorted(grouped):
        evidence = []
        for entry in grouped[asin].values():
            users = entry.pop("_users")
            evidence.append(
                {
                    **entry,
                    "user_count": len(users),
                    "evidence_count": len(entry["review_ids"]),
                }
            )
        evidence.sort(
            key=lambda row: (
                -row["user_count"],
                -row["evidence_count"],
                row["claim"].casefold(),
            )
        )
        output.append({"asin": asin, "evidence": evidence})
    return output


def build_product_targets(
    input_root: Path = DEFAULT_INPUT_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    source_reviews_path: Path = DEFAULT_SOURCE_REVIEWS,
) -> dict[str, Any]:
    import numpy as np

    input_root = input_root.resolve()
    output_root = output_root.resolve()
    source_reviews_path = source_reviews_path.resolve()
    claims, verification_run = _accepted_claims(input_root)
    vectors, fingerprint, cache_reused = _embed_claims(
        claims, output_root / "claim_embeddings.npz"
    )
    targets, target_stats = aggregate_product_targets(claims, vectors)

    source_reviews = read_jsonl(source_reviews_path)
    source_products = {str(row["asin"]) for row in source_reviews}
    target_products = set(targets)
    unexpected = target_products - source_products
    if unexpected:
        raise RuntimeError(f"Targets outside dense source corpus: {sorted(unexpected)[:5]}")

    metadata = {str(row["asin"]): row for row in load_json(SEOYOUNG_TRAIN)}
    asins = sorted(targets)
    products = []
    reviews_per_product = Counter(str(row["asin"]) for row in source_reviews)
    for index, asin in enumerate(asins):
        meta = metadata.get(asin, {})
        stats = target_stats[asin]
        products.append(
            {
                "asin": asin,
                "vector_index": index,
                "title": meta.get("title", ""),
                "parent_asin": meta.get("parent_asin") or asin,
                "category": infer_category(str(meta.get("title") or "")),
                "source_reviews": reviews_per_product[asin],
                **stats,
            }
        )

    material = np.stack([targets[asin] for asin in asins]).astype("float32")
    norms = np.linalg.norm(material, axis=1)
    if not np.isfinite(material).all() or not np.allclose(norms, 1.0, atol=1e-5):
        raise RuntimeError("Product material targets are not finite unit vectors")

    output_root.mkdir(parents=True, exist_ok=True)
    products_path = output_root / "products.json"
    vectors_path = output_root / "product_material_targets.npz"
    evidence_path = output_root / "evidence.jsonl"
    save_json(products_path, products)
    np.savez_compressed(vectors_path, asins=np.asarray(asins), material=material)
    write_jsonl(evidence_path, _build_evidence(claims))

    user_distribution = Counter(row["users"] for row in products)
    manifest = {
        "status": "complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Review-derived product material targets for recommendation prototype; no M0/M1 evaluation performed.",
        "protected_test_used": False,
        "label_source": "Qwen v2.1 accepted pseudo-labels informed by Codex AI development audit; not independent human gold.",
        "sentence_model": SENTENCE_MODEL,
        "target_formula": "deduplicate normalized claims within user -> mean claim vectors and L2 normalize per user -> equal-weight mean users and L2 normalize per product",
        "input": {
            "verification_path": str(input_root / "semantic_verifications.jsonl"),
            "verification_sha256": verification_run["output_sha256"],
            "verification_prompt_version": verification_run["prompt_version"],
            "accepted_claims": len(claims),
            "source_reviews_path": str(source_reviews_path),
            "source_reviews_sha256": sha256_file(source_reviews_path),
            "source_reviews": len(source_reviews),
            "source_products": len(source_products),
        },
        "targets": {
            "products": len(products),
            "products_without_target": len(source_products - target_products),
            "product_asins_without_target": sorted(source_products - target_products),
            "dimension": int(material.shape[1]),
            "user_count_distribution": {
                str(key): value for key, value in sorted(user_distribution.items())
            },
            "min_users": min(row["users"] for row in products),
            "max_users": max(row["users"] for row in products),
            "multi_user_products": sum(row["users"] >= 2 for row in products),
        },
        "embedding_cache": {
            "path": str(output_root / "claim_embeddings.npz"),
            "fingerprint": fingerprint,
            "reused": cache_reused,
        },
        "outputs": {
            "products": str(products_path),
            "products_sha256": sha256_file(products_path),
            "vectors": str(vectors_path),
            "vectors_sha256": sha256_file(vectors_path),
            "evidence": str(evidence_path),
            "evidence_sha256": sha256_file(evidence_path),
        },
    }
    save_json(output_root / "manifest.json", manifest)
    return manifest

