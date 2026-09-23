# Tactile-aware Fashion Recommendation System — Final Report

Completed: 2026-08-13 (Asia/Seoul)

## 1. Final Architecture

The v2.1 accepted exact spans, dense review metadata, and 384-dimensional product targets are
validated once at process startup and cached by `TactileStore`. Typed models and conservative
semantic presentation normalization feed one shared service layer for description, concern,
comparison, alternatives, reranking, and the Agent facade. The HTTP API and static demo contain no
duplicated tactile business logic.

The working 438-product legacy M0/M1 store remains intact. The new tactile layer independently uses
the 500-product source catalog, with 495 evidence-backed profiles and five explicit empty states.

## 2. Implemented Features

### Backend

- Typed claim, evidence, profile, intent, and recommendation candidate contracts
- Traceable open-vocabulary semantic presentation grouping and negation handling
- Validated product profile/vector/evidence startup cache
- Product tactile profile, Korean summary, concern detection, and multi-product comparison
- Configurable feature flags, ranking weights, concern thresholds, and full score breakdowns

### Frontend

- Integrated dependency-free responsive demo at `/tactile-demo`
- Catalog-first product cards with image/title: 500 source records deduplicated into 465 visible
  products, 30 per page across 16 pages
- A sticky natural-language search field available on catalog and detail screens
- Product detail, tactile summary and exact evidence dialog
- Concern cards linked to supported alternatives
- Ranked design/style-related and review-tactile-related products below details
- Full-catalog FashionCLIP design cards and explicit review/image tactile provenance badges
- Explicit empty, malformed-request, and insufficient-evidence states

### ML / Retrieval

- Same-category tactile alternatives with directional improvement, evidence confidence, and MMR
- Baseline, global-history ablation, category-conditioned, and explicit context-gated reranking
- Cross-category history gate limited to 0.02; explicit gate is 1.0
- General reranking is opt-in and does not replace the legacy default
- FashionCLIP 512-dimensional embeddings for all 465 visible product families
- Product-family cold-start Ridge from image/category input to the 384-dimensional tactile space
- Evidence-weighted hybrid targets: 461 review+image, four image-predicted only

### Agent

- Deterministic Korean/English tactile intent extraction with structured output
- Explicit `previous_intent` follow-up contract
- Real catalog retrieval and context-gated ranking only; invented product IDs are rejected
- Cross-category anchor similarity is not used
- Matched tactile constraints include exact evidence in returned reasons

## 3. Important Design Decisions

- No DB/vector DB was introduced: 495 product vectors fit an immutable in-memory NumPy index.
- Raw reviews, original spans, source datasets, and legacy M0/M1 behavior were preserved.
- Unknown claims remain open vocabulary instead of being forced into a small taxonomy.
- Unsupported open-vocabulary directional actions are disabled rather than guessed.
- No request-time LLM is required; deterministic parsing is the failure-safe default.
- Current full-review targets are prototype-only for temporal recommendation analysis.

See `DECISIONS.md` for the complete decision log.

## 4. Files Added

- `AGENTS.md`
- `configs/tactile_ranking.json`
- `recommendation_api/tactile_models.py`
- `recommendation_api/tactile_normalization.py`
- `recommendation_api/tactile_store.py`
- `recommendation_api/tactile_description.py`
- `recommendation_api/tactile_comparison.py`
- `recommendation_api/tactile_concerns.py`
- `recommendation_api/tactile_ranking.py`
- `recommendation_api/tactile_agent.py`
- `recommendation_api/static/index.html`, `app.css`, `app.js`
- Seven tactile API/service test modules
- `offline_eval/tactile_system_eval.py` and its test
- Required design documents under `docs/tactile/`
- Evaluation JSON, Markdown, and four prediction JSONL files under
  `data/recommendation_eval/tactile_v1/`

## 5. Files Modified

- `recommendation_api/server.py`
- `recommendation_api/tests/test_tactile_store.py`
- `recommendation_api/README.md`
- root `README.md`
- `docs/tactile/EXEC_PLAN.md` throughout execution

## 6. DB Changes

None. This repository has no database or ORM. Raw data was not modified.

## 7. API Endpoints

```text
GET  /v1/tactile/health
GET  /v1/tactile/evaluation
GET  /v1/products
POST /v1/products/search
GET  /v1/products/{asin}/tactile
GET  /v1/products/{asin}/tactile-summary
GET  /v1/products/{asin}/tactile-concerns
GET  /v1/products/{asin}/related
POST /v1/products/tactile-compare
POST /v1/recommendations/tactile-alternatives
POST /v1/recommendations/tactile-rerank
POST /v1/tactile/intent
POST /v1/tactile/agent
GET  /tactile-demo
```

All legacy `/api/*` endpoints remain available.

## 8. Tests

Final commands ran on 2026-08-13:

```bash
/home/user/onsesang/miniconda3/envs/texture/bin/python -m unittest discover -s tests -v
/home/user/onsesang/miniconda3/envs/texture/bin/python -m unittest discover -s recommendation_api/tests -v
/home/user/onsesang/miniconda3/envs/texture/bin/python -m unittest discover -s audit_app/tests -v
/home/user/onsesang/miniconda3/envs/texture/bin/python -m unittest discover -s offline_eval/tests -v
/home/user/onsesang/miniconda3/envs/texture/bin/python -m compileall -q material_span recommendation_api audit_app offline_eval scripts
```

Results: core 20/20, recommendation API 67/67, audit app 9/9, offline evaluation 7/7;
total 103/103 passed. Python compilation and JSON config/artifact validation passed. The restarted
systemd service passed live catalog pagination, natural-language search, product detail, related
design/tactile products, description, concern, and demo HTTP checks. Node is unavailable and there
is no frontend package/build configuration, so no frontend build/typecheck was claimed.

## 9. Evaluation

- Dataset/protocol: existing 332-case chronological leave-two-out protocol, fixed 100 negatives,
  identical candidates for all models
- Strategies: no tactile, global tactile, category-conditioned tactile, context-gated tactile
- All strategies: Recall@5 0.0060, NDCG@5 0.0043, Recall@10 0.0120, NDCG@10 0.0062
- No Recall/NDCG improvement was observed.
- Coverage: tactile history 46/332 (13.86%), tactile test target 5/332 (1.51%), candidate target
  coverage 3.25%
- Context-gated equals baseline because the interaction protocol contains no explicit tactile
  intent. This is the intended gate behavior.
- Description: 99% product coverage, 3,859 displayed evidence spans, exact support 100%, reviewer
  count correctness 100%, deterministic hallucination 0%
- Concern: 48 concerns over 42 products; exact support and reviewer-threshold compliance 100%
- Comparison: 50 pairs / 679 dimensions; exact support 100%, unsupported-value rate 0%
- Alternative: 47 supported tasks, 38 with results, 175 results; directional/category/evidence
  self-consistency 100%; one open-vocabulary task safely unsupported
- Agent: 5/5 intent fixtures, 10/10 retrieved products in catalog, hallucinated product rate 0%
- Image cold-start (70 held-out product families): Ridge centered cosine 0.2006 versus category-only
  0.0998; same-category Recall@5 0.2657 versus category-only 0.1400 and raw image 0.2171; NDCG@5
  0.8093 versus 0.7367 and 0.7762 respectively

Results: `data/recommendation_eval/tactile_v1/metrics.json` and `report.md`.

## 10. Demo Flow

1. Open `http://127.0.0.1:8877/tactile-demo` and browse the complete catalog, 30 products per page.
2. Use the persistent prompt bar, for example `세탁 후 잘 늘어나지 않는 치마를 찾아줘.`, to
   rerank the catalog by the parsed category and tactile constraint.
3. Open a product to inspect its details, buyer-reported materials, material-related opinions,
   repeated concerns, and exact supporting evidence.
4. Continue to separately ranked design-similar and tactile-similar products shown below the
   detail view.

## 11. Remaining Limitations

- Targets aggregate all selected reviews and are not time-aware; recommendation results are
  diagnostic, not leakage-free publication evidence.
- Only five evaluation test items have current tactile targets, preventing a useful ranking-power
  conclusion.
- Concern precision/recall and alternative human relevance have no independent labels.
- Qwen v2.1 labels were informed by Codex development auditing and are not independent human gold.
- The deterministic Agent supports a bounded Korean/English phrase set, not arbitrary language.
- Cold-start image-to-tactile evaluation contains only 70 held-out families and requires broader,
  independent validation before a production-quality tactile claim.
- No automated browser framework or frontend compiler exists in the repository.

## 12. Recommended Next Work

1. Keep this prototype and demo stable; do not rerun M0/M1 merely to expose these features.
2. Expand tactile targets into the recommendation item universe using a time-aware cutoff.
3. Create independent human-labeled description, concern, comparison, and alternative tasks.
4. Re-run the four-strategy temporal ablation only after useful target/test coverage is reached.
5. Add aligned visual/metadata retrieval for stronger anchor preservation.
6. Extend the deterministic intent fixture before considering an optional structured-output LLM.
