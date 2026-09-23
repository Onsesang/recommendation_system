# Phase 4 — Provisional AI Consistency Audit

> This is not a human audit. It uses the same Qwen checkpoint with an independent conservative prompt and only measures label consistency.

## Summary

- Rows: 600
- Schema success: 600
- Full symbolic agreement: 0.3016666666666667
- Core semantic agreement (mappability/axis/polarity; ignores intensity and scope): 0.6933333333333334
- Score-equivalent agreement (strong vs non-strong; ignores scope): 0.4483333333333333
- Rows flagged for future human review: 419
- Review priority counts: {'high': 184, 'medium': 235, 'none': 181}
- Disagreement fields: {'axis_id': 22, 'direction': 49, 'intensity': 217, 'mappability': 135, 'scope': 91}
- Axis macro-F1 on jointly mappable rows: 0.9531441951503007
- Polarity accuracy on jointly mappable rows: 0.8855140186915887
- Intensity weighted kappa: 0.10743876026661714
- Scope accuracy: 0.7873831775700935

## Original-label axis breakdown

| Original Qwen axis | Sampled | Agree | Disagree | Audit failure |
|---|---:|---:|---:|---:|
| elasticity | 126 | 32 | 94 | 0 |
| flexibility | 43 | 8 | 35 | 0 |
| softness | 106 | 30 | 76 | 0 |
| sponginess | 9 | 2 | 7 | 0 |
| surface_texture | 66 | 16 | 50 | 0 |
| thickness | 138 | 48 | 90 | 0 |
| unmappable | 39 | 37 | 2 | 0 |
| warmth | 73 | 8 | 65 | 0 |

## Limitation

This result cannot be reported as human validation or physical tactile ground truth. It is a temporary triage artifact for v2 planning. The source `human_axis_audit.csv` remains unmodified and still requires independent annotation.
