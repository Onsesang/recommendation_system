# Tactile atomic-class Qwen32B + FashionCLIP fine-tuning

- Completed: 2026-09-03T14:06:18+09:00
- Status: complete
- Existing v2 Phase 0–11: preserved and not rerun

## Research change

The original open-vocabulary review spans are preserved, while a derived atomic tactile class representation is added. The prediction task is masked multi-label classification rather than numeric axis regression. Unmentioned classes remain unobserved rather than negative.

## Data and semantic labeling

- Products: 8,498
- Candidate spans processed: 26,126
- Observed product-class pairs: 34,168
- Classes: soft, firm, smooth, rough, non_elastic, elastic, thin, thick, flexible, stiff, warm, cool, spongy, crisp
- Qwen model: `Qwen/Qwen3-VL-32B-Instruct`
- Revision: `0cfaf48183f594c314753d30a4c4974bc75f3ccb`
- Quantization: `bitsandbytes_nf4_double_quant_bfloat16`

## FashionCLIP ablation

| Regime | Dev macro-F1 | Test macro-F1 | Test micro-F1 | Test macro-AP |
|---|---:|---:|---:|---:|
| frozen | 0.6294 | 0.5784 | 0.7621 | 0.5607 |
| projection | 0.6631 | 0.6166 | 0.7824 | 0.6143 |
| last1 | 0.6922 | 0.6050 | 0.8145 | 0.6412 |
| last2 | 0.6975 | 0.6010 | 0.8216 | 0.6232 |
| full | 0.6736 | 0.5801 | 0.8066 | 0.6073 |

## Selected method

`last2` was selected using development macro-F1 only. Its locked-test macro-F1 is 0.6010.

## Per-class locked-test results

| Class | Observed | Positive | Precision | Recall | F1 | AP |
|---|---:|---:|---:|---:|---:|---:|
| soft | 656 | 618 | 0.9421 | 1.0000 | 0.9702 | 0.9541 |
| firm | 631 | 12 | 0.0000 | 0.0000 | 0.0000 | 0.0538 |
| smooth | 154 | 88 | 0.5915 | 0.9545 | 0.7304 | 0.7303 |
| rough | 159 | 64 | 0.4406 | 0.9844 | 0.6087 | 0.6064 |
| non_elastic | 419 | 21 | 0.1000 | 0.0476 | 0.0645 | 0.0891 |
| elastic | 463 | 390 | 0.8423 | 1.0000 | 0.9144 | 0.8923 |
| thin | 667 | 461 | 0.7303 | 0.9458 | 0.8242 | 0.8716 |
| thick | 667 | 197 | 0.5593 | 0.5025 | 0.5294 | 0.5519 |
| flexible | 109 | 49 | 0.5385 | 0.8571 | 0.6614 | 0.6533 |
| stiff | 117 | 54 | 0.4649 | 0.9815 | 0.6310 | 0.6488 |
| warm | 221 | 157 | 0.8122 | 0.9363 | 0.8698 | 0.9037 |
| cool | 216 | 64 | 0.6047 | 0.8125 | 0.6933 | 0.7718 |
| spongy | 13 | 1 | 0.1667 | 1.0000 | 0.2857 | 0.2000 |
| crisp | 14 | 10 | 0.6667 | 0.6000 | 0.6316 | 0.7974 |

## Reproducibility

- Config SHA-256: `53c522998b844aac55fefacad14d7f23b59283318248920d6a52d5b378a580f5`
- Groundings SHA-256: `7a43d29f51e272b6f23bb42bb8b9108f967811e298de542e88b5ac7f6232a691`
- Targets SHA-256: `6329a65e11e1845fb527845e17c0b7e5fda3760813d0510693c549a192737db1`
- Family-disjoint train/development/test split was reused without modification.
- Raw reviews, original spans, image-derived evidence, and review-derived evidence remain distinguishable.

## Interpretation cautions

- Labels are Qwen-derived pseudo-labels unless separately human-audited.
- A missing class mention is not evidence that the class is absent.
- Fine-tuning improvements must be interpreted against the frozen baseline and category shortcuts.
