# Phase 9 — Confidence and Recoverability Calibration

Property recoverability and instance confidence remain separate inputs. Thresholds and the generic cross-axis calibrator use only the development split.

| Method | AURC ↓ | confidence/error Spearman | ECE ↓ | risk @ nominal 80% |
|---|---:|---:|---:|---:|
| confidence_only | 0.809 | -0.062 | 0.177 | 0.829 |
| recoverability_only | 1.095 | 0.537 | 0.498 | 0.836 |
| product | 1.067 | 0.486 | 0.530 | 0.930 |
| learned_calibrator | 0.671 | -0.279 | 0.091 | 0.733 |

VISUAL_ABSTAIN is an inference decision. It is never used as a target class and never converts REVIEW_UNOBSERVED to neutral.
