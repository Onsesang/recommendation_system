# Tactile Architecture

## Target structure

```text
v2.1 accepted exact spans + review metadata + product target vectors
                           |
                           v
               TactileStore (startup cache)
                           +---------------------------+
                                                       |
product master + FashionCLIP image vectors             |
             |                                         |
             v                                         v
    MultimodalProductIndex <---- image-to-tactile Ridge
             |                 review/image hybrid target
                           |
              normalization + typed models
                           |
                 TactileService
          +----------+------+---------+
          |          |                |
     description  comparison       concerns
          |          |                |
          +----------+-------+--------+
                             |
                  alternatives / reranking
                             |
                    intent / agent facade
                             |
                    HTTP API + static UI
```

The agent never owns catalog lookup or ranking. It only converts language to a typed intent,
maintains explicit session context, calls deterministic retrieval/ranking, and formats grounded
reasons from returned evidence.

## Modules

- `recommendation_api/tactile_models.py`: typed dataclasses and serialization contracts
- `recommendation_api/tactile_normalization.py`: conservative, traceable semantic presentation
  grouping; unknown phrases remain open vocabulary
- `recommendation_api/tactile_store.py`: validated, immutable startup cache over the v2.1 artifacts
- `recommendation_api/multimodal_index.py`: validated product-master, full-catalog FashionCLIP,
  image-predicted tactile, and hybrid target cache
- `recommendation_api/tactile_service.py`: descriptions, concerns, comparison, alternatives,
  context-gated reranking, intent and agent orchestration
- `configs/tactile_ranking.json`: feature flags and all ranking/concern thresholds and weights
- `recommendation_api/server.py`: versioned routes while preserving existing `/api/*` routes
- `recommendation_api/static/`: dependency-free demo UI integrated into the same service
- `offline_eval/tactile_evaluation.py`: deterministic fixtures and quantitative feature evaluation

## Catalog coexistence

The legacy 438-product M0/M1 store remains intact for regression compatibility. The public catalog
uses 465 deduplicated product families with complete 512-dimensional FashionCLIP vectors. Product
detail evidence still comes only from `TactileStore`; design retrieval uses image cosine and tactile
related retrieval uses the 384-dimensional review/image hybrid index. Four visible products without
accepted review targets use explicit `image_predicted` recommendation vectors and never display
invented buyer claims.

## Runtime and performance

All profiles, evidence, 465 FashionCLIP vectors, and 465 hybrid tactile vectors are hash-validated
and loaded once at startup. Requests do not scan raw reviews, run FashionCLIP/Ridge, or invoke an
LLM. Exact NumPy scoring is sufficient at this catalog size.

## Evidence safety

- Every display claim links to exact quotes and review/span IDs.
- Distinct reviewer support is computed before public serialization; raw reviewer IDs are not
  returned by public endpoints.
- `review_qwen`, `review_human_verified`, and `image_estimated` remain distinguishable.
- Missing evidence returns `insufficient_evidence`; absent dimensions never receive an invented
  `medium` value.
- The current v2.1 artifact is prototype data, not independent human gold.
