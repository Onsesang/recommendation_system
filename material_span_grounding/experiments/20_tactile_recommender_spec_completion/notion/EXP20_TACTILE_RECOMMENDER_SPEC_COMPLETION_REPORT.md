# Experiment 20 — Tactile Recommender Spec Completion Final Report

Generated from locked Exp20 artifacts. This report is intentionally conservative: Track A reuses the Amazon_Fashion official test split that was already opened during Exp16, so the result is a locked post-hoc exploratory follow-up, not a fresh confirmatory test.

## Bottom line

The proposed true-in-model tactile variant `I_VX_T` did not improve over the generic multimodal control `I_VX` on exploratory test NDCG@10: `0.005786` vs `0.005794` (delta `-0.000008`). The shuffled tactile control scored `0.005786`, making the aligned-vs-shuffled delta `-0.000000`.

## Scientific status

- Track A status: `locked_posthoc_exploratory_followup`; confirmatory claims are forbidden because the Exp16 official test was already opened before Exp20.
- No Exp20 test metric was used for training, learning-rate selection, epoch selection, candidate budget selection, class selection, graph construction, or architecture selection.
- The test/report orchestration scripts were added after validation work began, but they only call the frozen `evaluate_exact()` metric implementation and locked checkpoints; no metric core or training/selection code was changed.

## Test metrics

| Variant | selected LR | selected epoch | NDCG@10 | HR@10 | MRR@10 | Recall@30000 | selected candidate budget |
|---|---:|---:|---:|---:|---:|---:|---|
| `I` — Interaction only | 0.001000 | 20 | 0.005725 | 0.009377 | 0.004591 | 0.236005 | 30000 / retrieval_bottleneck_unresolved |
| `I_T` — Interaction + tactile | 0.000300 | 20 | 0.005732 | 0.009391 | 0.004595 | 0.235737 | 30000 / retrieval_bottleneck_unresolved |
| `I_VX` — Interaction + generic image + text | 0.001000 | 20 | 0.005794 | 0.009503 | 0.004642 | 0.237170 | 30000 / retrieval_bottleneck_unresolved |
| `I_VX_T` — Interaction + generic image + text + tactile | 0.001000 | 20 | 0.005786 | 0.009482 | 0.004638 | 0.237045 | 30000 / retrieval_bottleneck_unresolved |
| `I_VX_T_SHUFFLE` — Interaction + generic image + text + shuffled tactile | 0.001000 | 20 | 0.005786 | 0.009475 | 0.004640 | 0.237160 | 30000 / retrieval_bottleneck_unresolved |

## Paired exploratory contrasts

| Contrast | ΔNDCG@10 | mean rank improvement | median rank improvement | improved / worse / unchanged users | top10 gains / losses |
|---|---:|---:|---:|---:|---:|
| `primary_I_VX_T_minus_I_VX` | -0.000008 | 25.455 | 0.000 | 38038 / 38558 / 1958894 | 166 / 209 |
| `aligned_tactile_minus_shuffle` | -0.000000 | -0.473 | 0.000 | 38263 / 38327 / 1958900 | 186 / 173 |
| `tactile_ablation_I_T_minus_I` | 0.000006 | 160.189 | 0.000 | 38646 / 38064 / 1958780 | 189 / 160 |

## Validation selection

| Variant | selected LR | selected epoch | validation NDCG@10 | validation Recall@30000 | checkpoint sha256 |
|---|---:|---:|---:|---:|---|
| `I` | 0.001000 | 20 | 0.004466 | 0.240630 | `1174a911756bd25c...` |
| `I_T` | 0.000300 | 20 | 0.004637 | 0.236976 | `830f2411e90acd97...` |
| `I_VX` | 0.001000 | 20 | 0.005545 | 0.254567 | `fbfe0727f790bd8d...` |
| `I_VX_T` | 0.001000 | 20 | 0.005437 | 0.254308 | `9511a2b4ab6b6963...` |
| `I_VX_T_SHUFFLE` | 0.001000 | 20 | 0.005448 | 0.253921 | `5eccb2378be9f3e2...` |

Full validation run table: `artifacts/validation_results.csv`.

## Protocol and lock evidence

- Protocol state: `complete_locked_posthoc_exploratory`
- Implementation lock sha256: `1f745399c2e63e74d0a591d8c76761fbfb58539dd30cad2559dc1f135b6522b3`
- Validation selection sha256: `1d6aa69be0ff7e1c759dcb92b40a371d613634425c48a7a8aa2f3e240198a51b`
- Test results sha256: `6058b1ce5fc3ab3b0903cfa37f38711f558a5872924c4fc18c30f59a38371bff`
- Frozen protocol sha256 in lock: `d42e83f73564fb1ea10ecc2d585de46487026a0628791f90d73ba33e1b8b3409`
- Frozen model-variants sha256 in lock: `d4a2d64f1b8075e705fd15ccac77817a59170d022db2581545c99d55105b9e26`
- Frozen input manifest sha256 in lock: `8fbd5f90eaeacaa2d5d7ade25baf70345c28bb1f1a17ea374b5057bd4741fe33`
- Frozen metric source hashes include `models_exp20.py`: `c16ee35ba077fa169463d310737412fdfb37771f2ca2996c5f8a56ad0cb0410b`

## Tactile feature and graph provenance

- Frozen input manifest entries: `18`
- Tactile graph artifact sha256: `3148d8f9413a52f34bb4bef74645cbfc4ea87b04f44132e07260dbee0af6a93b`
- Tactile graph selected nprobe: `32`
- Tactile graph exact-recall audit mean/min: `0.99875` / `0.925`

## Limitations

- This is not an official SMORE reproduction; it is a local, pinned Amazon_Fashion adaptation.
- Dedicated tactile signal is interpreted only as incremental Last2 tactile information beyond generic image/text; generic visual/text features may already encode tactile cues implicitly.
- Candidate retrieval recall did not reach the preregistered threshold for these sparse Amazon_Fashion settings, so the fallback full reported budget is retained where applicable.
- Human preference/provenance work remains separate unless a prospective annotation protocol is frozen and executed before labels are opened.

## Artifact inventory

- `artifacts/test_results.json` — final exploratory test metrics and paired contrasts.
- `artifacts/test_*_per_user.parquet` — per-target exact ranks for each selected variant.
- `artifacts/validation_selection.json` — locked learning-rate/epoch/candidate-budget choices.
- `artifacts/checkpoints/*.complete.json` and `*.pt` — selected and completed validation checkpoints.
- `artifacts/events.jsonl` / `artifacts/notifications.jsonl` — execution and Discord notification audit trail.

