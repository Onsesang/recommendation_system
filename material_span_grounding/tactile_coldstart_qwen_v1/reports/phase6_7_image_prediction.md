# Phase 6–7 — Image Prediction and Objective Robustness

## softness

| Method | Spearman mean | std |
|---|---:|---:|
| category_only | 0.084 | 0.008 |
| dino_ridge | 0.075 | 0.073 |
| fashionclip_linear | 0.012 | 0.076 |
| fashionclip_ridge | 0.051 | 0.044 |
| image_category_ridge | 0.047 | 0.034 |
| ordinal | -0.007 | 0.030 |
| pairwise | 0.005 | 0.087 |
| tiny_mlp | 0.022 | 0.110 |

## surface_texture

| Method | Spearman mean | std |
|---|---:|---:|
| category_only | 0.142 | 0.082 |
| dino_ridge | 0.086 | 0.283 |
| fashionclip_linear | -0.211 | 0.098 |
| fashionclip_ridge | -0.175 | 0.123 |
| image_category_ridge | -0.107 | 0.140 |
| ordinal | 0.047 | 0.027 |
| pairwise | -0.235 | 0.134 |
| tiny_mlp | -0.218 | 0.031 |

## elasticity

| Method | Spearman mean | std |
|---|---:|---:|
| category_only | 0.248 | 0.071 |
| dino_ridge | 0.148 | 0.099 |
| fashionclip_linear | 0.184 | 0.134 |
| fashionclip_ridge | 0.280 | 0.135 |
| image_category_ridge | 0.230 | 0.169 |
| ordinal | 0.286 | 0.130 |
| pairwise | 0.188 | 0.127 |
| tiny_mlp | 0.323 | 0.189 |

## thickness

| Method | Spearman mean | std |
|---|---:|---:|
| category_only | -0.130 | 0.088 |
| dino_ridge | 0.270 | 0.042 |
| fashionclip_linear | 0.060 | 0.021 |
| fashionclip_ridge | 0.087 | 0.015 |
| image_category_ridge | 0.126 | 0.079 |
| ordinal | 0.032 | 0.014 |
| pairwise | 0.078 | 0.009 |
| tiny_mlp | 0.136 | 0.120 |

## Interpretation

Category-only and same-category pairwise metrics are mandatory controls. A structured model is not considered visually grounded when it only improves across categories. The 384-dimensional result remains an open-vector baseline and is not physical tactile ground truth.
