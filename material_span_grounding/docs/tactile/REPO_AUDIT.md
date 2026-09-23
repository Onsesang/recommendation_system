# Repository Audit

Audit date: 2026-08-13 (Asia/Seoul)

## Runtime and repository

- Root: `/home/user/onsesang/material_span_grounding`
- Python: 3.10.20 in conda environment `texture`
- Important libraries: NumPy 2.2.6, joblib 1.5.3, sentence-transformers 5.6.1,
  PyTorch 2.5.1+cu121
- The directory is not a Git worktree. No commit/push workflow is available here.
- No Python packaging manifest, requirements lock, Docker file, or deployment container exists.

## Backend

- Framework: Python standard-library `ThreadingHTTPServer` and `BaseHTTPRequestHandler`
- Entry point: `recommendation_api/server.py`
- Business/index layer: `recommendation_api/store.py`
- Local service: user systemd unit `material-recommendation.service`, port 8877
- API is read-only apart from request processing; it has no application DB.
- Existing routes expose health, stats, evaluation, products, M0/M1 search, images,
  HTML docs, and OpenAPI.

## Frontend

- There is no product/recommendation frontend build project or `package.json` in this repository.
- `audit_app/static` is a separate human-audit UI written in plain HTML/CSS/JavaScript.
- Tactile demo UI should therefore follow the existing dependency-free static convention and be
  served by the recommendation API, without rewriting the audit app.

## Storage, DB, ORM, vector index

- No SQL/NoSQL database, ORM, migration tool, FAISS, or vector DB is used.
- JSON/JSONL/NPZ/joblib files are loaded into memory at service startup.
- Similarity search is exact NumPy matrix multiplication; 495 items do not require an external
  vector database.

## Data contracts found

- Dense review source: `data/dense/reviews_product_dense.jsonl`
  - 4,158 rows / 500 products
  - fields: `asin`, `review_id`, `user_id`, `rating`, `timestamp`, `verified_purchase`,
    `text`, `text_chars`, `selection_hash`
- v2.1 verified spans:
  `data/vllm/dense_500/v2_1_ai_recall/semantic_verifications.jsonl`
  - 6,345 schema-valid span rows; 4,527 semantic accepted
  - preserves original quote, normalized claim, scope, property status, intensity, sentiment,
    evidence basis, visual observability, review/product/user provenance
- Human/AI audit inputs and results: `audit_app/data/*` and
  `data/regression/codex_ai_audit_v2_1/`
- Current prototype product target:
  `data/derived/dense_500_v2_1_targets/`
  - 495 products, 384-dimensional BGE vectors
  - `products.json`, `product_material_targets.npz`, `evidence.jsonl`, `manifest.json`
- Product metadata: `/home/user/onsesang/seoyoung/data/splits/train.json`
- Product images: `/home/user/onsesang/texture_project/images_train` (21,059 files)
- Recommendation interactions:
  `/home/user/onsesang/seoyoung/data/interim/recommendation_interactions.parquet`

Raw/external datasets remain read-only inputs.

## Existing recommendation and embeddings

- Existing recommendation catalog: 438-product sparse pilot
- M0: frozen 1,152-dimensional Qwen image-feature cosine
- M1: StandardScaler + multi-output Ridge from image features to 384-dimensional review target
- Existing recommendation target file includes image and material arrays; the new 495-product target
  intentionally includes material only.
- Offline evaluator provides chronological leave-two-out cases, fixed negatives, ranking metrics,
  cohorts, and paired bootstrap.

## Tests and commands

Baseline on 2026-08-13:

- Core: 20/20 passed
- Recommendation API: 6/6 passed
- Audit app: 9/9 passed
- Offline evaluation: 6/6 passed
- Total: 41/41 passed
- `compileall` passed for all Python packages
- Live `/api/health` returned HTTP 200 with 438 catalog products

Commands:

```bash
/home/user/onsesang/miniconda3/envs/texture/bin/python -m unittest discover -s tests -v
/home/user/onsesang/miniconda3/envs/texture/bin/python -m unittest discover -s recommendation_api/tests -v
/home/user/onsesang/miniconda3/envs/texture/bin/python -m unittest discover -s audit_app/tests -v
/home/user/onsesang/miniconda3/envs/texture/bin/python -m unittest discover -s offline_eval/tests -v
/home/user/onsesang/miniconda3/envs/texture/bin/python -m compileall -q material_span recommendation_api audit_app offline_eval
./recommendation_api/start.sh
./recommendation_api/status.sh
/home/user/onsesang/miniconda3/envs/texture/bin/python -m offline_eval.cli all
```

There is no configured lint command or frontend build/typecheck command. Static JavaScript will be
syntax-checked with `node --check` only if Node is available; browser/API integration tests remain
the authoritative baseline.

