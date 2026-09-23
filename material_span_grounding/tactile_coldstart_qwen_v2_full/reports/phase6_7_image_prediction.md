# Phase 6–7 — Image Prediction and Objective Robustness

## softness

| Method | Spearman mean | std |
|---|---:|---:|
| category_only | 0.071 | 0.000 |
| dino_ridge | -0.058 | 0.000 |
| fashionclip_linear | 0.024 | 0.000 |
| fashionclip_ridge | 0.071 | 0.000 |
| image_category_ridge | 0.079 | 0.000 |
| ordinal | 0.089 | 0.000 |
| pairwise | 0.046 | 0.000 |
| selected_by_development | 0.199 | 0.000 |
| tiny_mlp | 0.019 | 0.000 |

## surface_texture

| Method | Spearman mean | std |
|---|---:|---:|
| category_only | 0.396 | 0.000 |
| dino_ridge | -0.423 | 0.000 |
| fashionclip_linear | -0.040 | 0.000 |
| fashionclip_ridge | -0.066 | 0.000 |
| image_category_ridge | -0.093 | 0.000 |
| ordinal | -0.026 | 0.000 |
| pairwise | -0.053 | 0.000 |
| selected_by_development | 0.441 | 0.000 |
| tiny_mlp | 0.040 | 0.000 |

## elasticity

| Method | Spearman mean | std |
|---|---:|---:|
| category_only | 0.328 | 0.000 |
| dino_ridge | 0.357 | 0.000 |
| fashionclip_linear | 0.340 | 0.000 |
| fashionclip_ridge | 0.356 | 0.000 |
| image_category_ridge | 0.364 | 0.000 |
| ordinal | 0.260 | 0.000 |
| pairwise | 0.192 | 0.000 |
| selected_by_development | 0.369 | 0.000 |
| tiny_mlp | 0.327 | 0.000 |

## thickness

| Method | Spearman mean | std |
|---|---:|---:|
| category_only | 0.086 | 0.000 |
| dino_ridge | 0.249 | 0.000 |
| fashionclip_linear | 0.251 | 0.000 |
| fashionclip_ridge | 0.322 | 0.000 |
| image_category_ridge | 0.318 | 0.000 |
| ordinal | 0.264 | 0.000 |
| pairwise | 0.241 | 0.000 |
| selected_by_development | 0.308 | 0.000 |
| tiny_mlp | 0.303 | 0.000 |

## flexibility

| Method | Spearman mean | std |
|---|---:|---:|
| category_only | -0.297 | 0.000 |
| dino_ridge | 0.314 | 0.000 |
| fashionclip_linear | 0.018 | 0.000 |
| fashionclip_ridge | 0.092 | 0.000 |
| image_category_ridge | 0.129 | 0.000 |
| ordinal | 0.092 | 0.000 |
| pairwise | 0.092 | 0.000 |
| selected_by_development | 0.388 | 0.000 |
| tiny_mlp | 0.351 | 0.000 |

## warmth

| Method | Spearman mean | std |
|---|---:|---:|
| category_only | -0.009 | 0.000 |
| dino_ridge | -0.069 | 0.000 |
| fashionclip_linear | -0.161 | 0.000 |
| fashionclip_ridge | -0.110 | 0.000 |
| image_category_ridge | -0.087 | 0.000 |
| ordinal | 0.018 | 0.000 |
| pairwise | 0.018 | 0.000 |
| selected_by_development | 0.317 | 0.000 |
| tiny_mlp | 0.060 | 0.000 |

## Interpretation

Category-only and same-category pairwise metrics are mandatory controls. A structured model is not considered visually grounded when it only improves across categories. The 384-dimensional result remains an open-vector baseline and is not physical tactile ground truth.
