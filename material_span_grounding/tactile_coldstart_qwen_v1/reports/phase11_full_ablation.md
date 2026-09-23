# Phase 11 — Full Ablations and Paper Tables

## Image prediction (Spearman mean over family splits)

| Method | softness | surface_texture | elasticity | thickness |
|---|---:|---:|---:|---:|
| category_only | 0.084 | 0.142 | 0.248 | -0.130 |
| dino_ridge | 0.075 | 0.086 | 0.148 | 0.270 |
| fashionclip_linear | 0.012 | -0.211 | 0.184 | 0.060 |
| fashionclip_ridge | 0.051 | -0.175 | 0.280 | 0.087 |
| image_category_ridge | 0.047 | -0.107 | 0.230 | 0.126 |
| ordinal | -0.007 | 0.047 | 0.286 | 0.032 |
| pairwise | 0.005 | -0.235 | 0.188 | 0.078 |
| tiny_mlp | 0.022 | -0.218 | 0.323 | 0.136 |

## Qwen VLM image-only zero-shot (visually assessable pairs only)

| Axis | Samples | Spearman | MAE | Direction accuracy |
|---|---:|---:|---:|---:|
| softness | 41 | 0.162 | 0.931 | 0.854 |
| surface_texture | 15 | -0.093 | 2.150 | 0.467 |
| elasticity | 18 | 0.133 | 1.463 | 0.556 |
| thickness | 43 | 0.159 | 1.529 | 0.615 |

## Selective prediction

| Method | AURC ↓ |
|---|---:|
| confidence_only | 0.809 |
| recoverability_only | 1.095 |
| product | 1.067 |
| learned_calibrator | 0.671 |

## Cold-start retrieval

| Method | NDCG@10 | 95% bootstrap CI |
|---|---:|---:|
| category_only | 0.769 | [0.710, 0.826] |
| confidence_selective_u0 | 0.739 | [0.684, 0.795] |
| fashionclip_taxonomy_zero_shot | 0.750 | [0.696, 0.805] |
| open_384d_current_split | 0.766 | [0.708, 0.818] |
| product_selective_u0 | 0.729 | [0.670, 0.787] |
| proposed_calibrator_u0 | 0.755 | [0.697, 0.812] |
| proposed_calibrator_u1 | 0.749 | [0.690, 0.804] |
| proposed_unknown_coverage_u2 | 0.749 | [0.690, 0.807] |
| qwen_vlm_zero_shot_u0 | 0.765 | [0.713, 0.819] |
| random | 0.784 | [0.731, 0.839] |
| recoverability_selective_u0 | 0.730 | [0.673, 0.787] |
| structured_no_abstention | 0.730 | [0.676, 0.783] |

## Paired query bootstrap differences (NDCG@10)

| Comparison | Mean difference | 95% CI | Win rate |
|---|---:|---:|---:|
| proposed_unknown_coverage_u2_minus_structured_no_abstention | 0.019 | [0.002, 0.040] | 0.365 |
| proposed_unknown_coverage_u2_minus_confidence_selective_u0 | 0.009 | [-0.015, 0.042] | 0.154 |
| structured_no_abstention_minus_open_384d_current_split | -0.036 | [-0.095, 0.023] | 0.462 |

## Falsifiable hypotheses

| Hypothesis | Status | Evidence |
|---|---|---|
| H1 | falsified | `{"structured_axis_mean": 0.060825669218267694, "category_axis_mean": 0.08590558274244667, "structured_ndcg@10": 0.7298292193668611, "open_vector_ndcg@10": 0.7660250671961953}` |
| H2 | supported | `{"external_pairwise_mean": 0.5132343093930841, "axes": 4}` |
| H3 | supported | `{"confidence_only_aurc": 0.8086023085120609, "learned_calibrator_aurc": 0.6714998145118738}` |
| H4 | supported | `{"full_risk": 0.836233913898468, "selective_risk": 0.732701301574707, "actual_coverage": 0.816}` |
| H5 | supported | `{"forced_structured_ndcg@10": 0.7298292193668611, "proposed_ndcg@10": 0.7486523584406508}` |

## Limitations

- The current Amazon family splits are feasibility splits and not a never-inspected final test set.
- Human-audit rows were exported, but human annotation was not fabricated; pseudo-label quality metrics remain pending.
- Leeds raw image-plus-rating access/licensing was not verified, so Leeds was reported unavailable.
- Qwen VLM zero-shot uses symbolic image-only axis scores with explicit abstention; it is not a direct prompt-to-ranked-list evaluator.
- Held-out reviews are subjective selective evidence, never described as physical tactile ground truth.
