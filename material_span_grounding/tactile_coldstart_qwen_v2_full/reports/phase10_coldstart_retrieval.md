# Phase 10 — Review-Cold-Start Tactile Retrieval

Data-generated queries: 10 (single=10, multi=0). All candidates are held-out test families from the same category.

| Method | NDCG@10 | Recall@10 | Pairwise |
|---|---:|---:|---:|
| random | 0.567 | 0.197 | 0.506 |
| category_only | 0.504 | 0.172 | 0.000 |
| fashionclip_taxonomy_zero_shot | 0.535 | 0.172 | 0.509 |
| structured_no_abstention | 0.656 | 0.228 | 0.643 |
| confidence_selective_u0 | 0.616 | 0.208 | 0.616 |
| recoverability_selective_u0 | 0.656 | 0.228 | 0.643 |
| product_selective_u0 | 0.627 | 0.230 | 0.613 |
| proposed_calibrator_u0 | 0.642 | 0.196 | 0.526 |
| proposed_calibrator_u1 | 0.635 | 0.192 | 0.530 |
| proposed_unknown_coverage_u2 | 0.635 | 0.192 | 0.530 |

## UNKNOWN boundary

U0 assigns zero contribution to abstained constraints, U1 uses the configured mild penalty, and U2 additionally scales by supported-constraint coverage. UNKNOWN is never scored as a confirmed mismatch.
