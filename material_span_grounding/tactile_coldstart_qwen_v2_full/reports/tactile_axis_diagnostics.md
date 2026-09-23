# Phase 3 — Tactile Axis Feasibility Report

Active axes: `softness, surface_texture, elasticity, thickness, flexibility, warmth`
Selection scope: `train` (primary seed only; 6300 products / 5295 parent families); every evaluated test split remains hidden.
Unmappable among upstream Qwen-accepted claims: 33.9%

| Axis | Spans | Products | ≥2 reviewers | Missing | Pole products | Top category | Selected |
|---|---:|---:|---:|---:|---|---:|:---:|
| softness | 488 | 476 | 12 | 92.4% | soft=422, firm=55 | 30.7% | Y |
| surface_texture | 160 | 152 | 8 | 97.6% | smooth=66, rough=86 | 35.0% | Y |
| elasticity | 2001 | 1928 | 73 | 69.4% | non_elastic=1468, elastic=459 | 28.9% | Y |
| thickness | 1167 | 1139 | 28 | 81.9% | thin=718, thick=417 | 37.0% | Y |
| flexibility | 98 | 91 | 7 | 98.6% | flexible=31, stiff=60 | 35.7% | Y |
| warmth | 317 | 293 | 24 | 95.3% | warm=167, cool=139 | 28.4% | Y |
| sponginess | 2 | 2 | 0 | 100.0% | spongy=0, crisp=2 | 100.0% | N |

## Interpretation boundary

No mention is REVIEW_UNOBSERVED, not neutral. Counts and distributions are based on Qwen pseudo-labels. Reviewer disagreement remains supervision and is not converted into UNKNOWN.
Material composition diagnostics are unavailable because the frozen product master has no composition field.
Mean Qwen mapping confidence is only a proxy. Human axis-confusion validation was explicitly skipped and remains pending.
