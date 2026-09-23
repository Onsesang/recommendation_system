# Class multi-label + FashionCLIP fine-tuning protocol

This is a new v3 experiment. It does not modify or rerun the preserved v2
Phase 0--11 artifacts.

## Locked decisions

- Use all 8,498 eligible products through the existing family-disjoint split:
  6,300 train, 1,077 development, and 1,121 locked test products.
- Preserve raw review text, original spans, and open-vocabulary claims.
- Add atomic tactile classes as a derived representation; never replace the
  open-vocabulary evidence with the class representation.
- Use official `Qwen/Qwen3-VL-32B-Instruct` revision
  `0cfaf48183f594c314753d30a4c4974bc75f3ccb` loaded with bitsandbytes NF4
  4-bit double quantization and BF16 compute.
- Treat an unmentioned class as unobserved, not negative. A present class gives
  negative supervision only to its explicitly configured incompatible class.
- Aggregate span evidence reviewer-first, then product-class.
- Select thresholds, hyperparameters, and fine-tuning depth only on development.
  The locked test split is evaluated after selection.
- Compare frozen, projection-only, last-1-block, last-2-block, and full
  FashionCLIP fine-tuning.

## Primary metrics

- macro and micro F1 on observed product-class pairs
- macro average precision and AUROC where both labels exist
- exact class-level precision/recall/F1
- calibration and coverage
- category-stratified results

Every script is checkpointed and safe to resume. Intermediate output is written
only inside this experiment directory.
