# Phase 3 — Tactile Axis Feasibility Report

Active axes: `softness, surface_texture, elasticity, thickness`
Selection scope: `train, development` intersection across all evaluated seeds (285 families); every seed's test reviews remain hidden.
Unmappable among upstream Qwen-accepted claims: 42.4%

| Axis | Spans | Products | ≥2 reviewers | Missing | Pole products | Top category | Selected |
|---|---:|---:|---:|---:|---|---:|:---:|
| softness | 499 | 164 | 102 | 42.5% | soft=154, firm=23 | 25.5% | Y |
| surface_texture | 102 | 47 | 10 | 83.5% | smooth=21, rough=31 | 29.4% | Y |
| elasticity | 223 | 98 | 32 | 65.6% | non_elastic=45, elastic=77 | 30.9% | Y |
| thickness | 549 | 184 | 102 | 35.4% | thin=146, thick=68 | 26.0% | Y |
| flexibility | 70 | 31 | 6 | 89.1% | flexible=2, stiff=30 | 31.4% | N |
| warmth | 117 | 58 | 23 | 79.6% | warm=44, cool=25 | 29.9% | N |
| sponginess | 9 | 3 | 0 | 98.9% | spongy=0, crisp=3 | 88.9% | N |

## Interpretation boundary

No mention is REVIEW_UNOBSERVED, not neutral. Counts and distributions are based on Qwen pseudo-labels. Reviewer disagreement remains supervision and is not converted into UNKNOWN.
Material composition diagnostics are unavailable because the frozen product master has no composition field.
Mean Qwen mapping confidence is only a pre-audit proxy; human axis-confusion metrics remain pending Phase 4 annotation.
