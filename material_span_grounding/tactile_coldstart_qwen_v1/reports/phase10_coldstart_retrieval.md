# Phase 10 — Review-Cold-Start Tactile Retrieval

Data-generated queries: 52 (single=40, multi=12). All candidates are held-out test families from the same category.

| Method | NDCG@10 | Recall@10 | Pairwise |
|---|---:|---:|---:|
| random | 0.784 | 0.979 | 0.515 |
| category_only | 0.769 | 0.978 | 0.000 |
| fashionclip_taxonomy_zero_shot | 0.750 | 0.986 | 0.469 |
| structured_no_abstention | 0.730 | 0.970 | 0.461 |
| confidence_selective_u0 | 0.739 | 0.978 | 0.462 |
| recoverability_selective_u0 | 0.730 | 0.970 | 0.461 |
| product_selective_u0 | 0.729 | 0.970 | 0.470 |
| proposed_calibrator_u0 | 0.755 | 0.978 | 0.461 |
| proposed_calibrator_u1 | 0.749 | 0.978 | 0.452 |
| proposed_unknown_coverage_u2 | 0.749 | 0.978 | 0.452 |
| open_384d_current_split | 0.766 | 0.972 | 0.458 |
| qwen_vlm_zero_shot_u0 | 0.765 | 0.983 | 0.257 |

## UNKNOWN boundary

U0 assigns zero contribution to abstained constraints, U1 uses the configured mild penalty, and U2 additionally scales by supported-constraint coverage. UNKNOWN is never scored as a confirmed mismatch.
