# Tactile Decisions

## D001 — Coexist with legacy M0/M1

Keep the working 438-item RecommendationStore unchanged and add a separate 495-item TactileStore.
Reason: the new target artifact has no aligned 1,152-dimensional image features, and inventing or
silently mixing rows would break the existing model contract.

## D002 — No database migration

Use validated immutable JSON/JSONL/NPZ startup caches. Reason: the repository has no DB or ORM and
495 products fit comfortably in memory. This avoids an unjustified infrastructure change.

## D003 — Conservative normalization

Use traceable lexical/phrase rules for common presentation concepts and retain unknown open-
vocabulary claims as their own normalized labels. Never force every claim into a small taxonomy.

## D004 — Deterministic runtime

Avoid request-time LLM calls. Intent parsing uses deterministic phrase rules with explicit JSON as
the highest-confidence path. This makes tests reproducible and provides a fallback if an LLM is
added later.

## D005 — Prototype-only temporal interpretation

The v2.1 target uses all dense reviews. It is valid for the requested recommendation prototype and
feature testing, but its offline ranking results are diagnostic until time-aware targets exist.

## D006 — Feature flags default safely

Descriptions, comparison, concerns, alternatives, and agent may be enabled for the demo. General
tactile reranking does not replace legacy ranking by default; callers select a strategy explicitly.

## D007 — Catalog-first UI and honest design similarity (superseded by D008)

The first screen renders the 500 source records as 465 deduplicated visible products through
30-item server-side pages. Product identity combines normalized exact titles with guarded
same-image/category/title-overlap grouping, and the same rule applies to search and related lists.
Natural-language search returns the same page contract. Related-product design ranking uses
same-category title/style metadata across the catalog and adds frozen visual cosine only when both
products are among the 21 items aligned with legacy image features. It never labels missing visual
features as an image-model score.

This was the safe initial implementation before the full-catalog FashionCLIP artifact existed.
D008 replaces the partial visual path for the current demo while preserving the no-fabrication
rule.

## D008 — Full-catalog image retrieval and explicit cold-start provenance

All 465 visible product families receive a frozen 512-dimensional FashionCLIP vector. Design
ranking uses image cosine as its primary signal. A Ridge model selected on development data maps
FashionCLIP plus category features into the existing 384-dimensional review target space. Review
and predicted vectors are blended according to evidence strength; review-free products are marked
`image_predicted`. Image predictions may affect recommendation ordering but never generate or
replace buyer quotes, concerns, or material descriptions.
