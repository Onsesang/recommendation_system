# Phase 9 — Confidence and Recoverability Calibration

Property recoverability and instance confidence remain separate inputs. Thresholds and the generic cross-axis calibrator use only the development split.

| Method | AURC ↓ | confidence/error Spearman | ECE ↓ | risk @ nominal 80% |
|---|---:|---:|---:|---:|
| confidence_only | 0.601 | -0.208 | 0.224 | 0.659 |
| recoverability_only | 0.763 | 0.089 | 0.461 | 0.672 |
| product | 0.717 | 0.013 | 0.542 | 0.670 |
| learned_calibrator | 0.621 | -0.241 | 0.092 | 0.648 |

VISUAL_ABSTAIN is an inference decision. It is never used as a target class and never converts REVIEW_UNOBSERVED to neutral.
