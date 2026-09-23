# Tactile Data Contracts

All public contracts use `asin` as `product_id`. Original claim text and exact evidence spans are
preserved even when presentation concepts are normalized.

## TactileClaim

```text
claim_id: str              # span_id
product_id: str            # ASIN
review_id: str
reviewer_id: str | null    # internal only; omitted from public JSON
original_span: str         # exact source quote
normalized_text: str       # accepted semantic claim
sentiment: str
intensity: str
scope: str
property_status: str
confidence: float
source: review_qwen | review_human_verified | image_estimated | metadata
human_verified: bool
rating: float | null
verified_purchase: bool | null
```

## TactileEvidence

Public evidence contains product, claim, exact quote, review ID, optional rating and verified-
purchase status, confidence, and source. It never returns raw reviewer ID.

## ProductTactileProfile

```text
product_id, title, category
claims[]
representative_claims[]
embedding_ref and optional embedding (internal by default)
reviewer_count, review_count, claim_count
evidence_strength
source_breakdown
status: available | insufficient_evidence
```

## TactileIntent

```text
current_product_id?: str
category?: str
query_text?: str
desired_more: str[]
desired_less: str[]
avoid: str[]
must_have: str[]
source: explicit_structured | deterministic_nlp | agent_context
confidence: float
```

An empty intent is valid. Purchase history alone does not produce must-have or avoid constraints.

## RecommendationCandidate

```text
product_id
base_score
tactile_score
constraint_score
confidence_score
diversity_score
final_score
score_breakdown: object
reason: grounded object
```

Scores are diagnostic similarities, not calibrated probabilities. Every component is returned for
debugging and offline evaluation.

## HTTP error and empty-state contract

- Unknown product: HTTP 404, structured `error.code=not_found`
- Malformed/invalid request: HTTP 400, `error.code=invalid_request`
- Disabled feature: HTTP 404, `error.code=feature_disabled`
- Known product without evidence: HTTP 200 with `status=insufficient_evidence`
- No qualifying recommendation: HTTP 200 with empty `results` and explicit message

## CatalogPage

```text
total: int
page: int                  # 1-based
page_size: int             # UI default 30
total_pages: int
has_previous, has_next: bool
items[]: product_id, title, category, image_url, tactile_status, reviewer_count, claim_count,
         tactile_target_source, review_weight, image_weight,
         image_prediction_confidence, tactile_target_confidence
```

The public catalog is deduplicated by visible product family. Exact normalized-title duplicates
are grouped; exact-image matches are grouped only when category matches and title-token overlap is
at least 0.4, which avoids merging unrelated records that share a placeholder image. The current
500 source records resolve to 465 visible products. Search and related-product lists apply the same
identity rule.

Natural-language search reuses this contract and adds `query_text`, structured `intent`,
`relevance_score`, score breakdown, matched tactile constraints, and exact matched evidence.

## RelatedProducts

`design_similar` and `tactile_similar` remain separate ranked lists. Design similarity uses
same-category full-catalog FashionCLIP cosine as the primary signal and title/style tokens as a
secondary signal. Tactile similarity uses a 384-dimensional hybrid target: reviewer-equal-weight
review targets are blended with an image-to-tactile Ridge prediction according to evidence
strength. Every result exposes its score breakdown and target source. `image_predicted` is a
recommendation signal, never fabricated buyer evidence.
