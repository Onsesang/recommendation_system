# Tactile Evaluation Plan

## Leakage boundary

The current 495-product targets aggregate all selected reviews and are suitable for feature demos
and deterministic functional evaluation. They must not be presented as leakage-free temporal
recommendation targets. Ranking evaluation reports this limitation. A future publishable run must
build targets using only reviews available before each evaluation timestamp.

## Recommendation ablation

Use the existing chronological fixed-candidate protocol and report Recall@5/10, NDCG@5/10, MRR,
coverage, and paired deltas for:

1. no tactile / popularity baseline
2. global tactile history (research ablation only)
3. category-conditioned tactile history
4. explicit/context-gated tactile

All strategies rank identical stored candidate sets. Coverage accompanies tactile metrics.

## Feature-level evaluation

- Description: evidence faithfulness, reviewer-count correctness, support rate, hallucination rate,
  coverage, empty state
- Comparison: supported dimensions, unsupported-difference rate, evidence traceability
- Concern: precision-oriented deterministic fixture, false-alert rate, distinct-reviewer threshold,
  evidence support
- Alternative: Directional Success@K, Precision@K, anchor/category preservation, tactile
  improvement, evidence coverage
- Agent: intent extraction accuracy, constraint/follow-up preservation, catalog consistency, zero
  hallucinated product IDs

Each evaluator writes machine-readable JSON plus a Markdown report. Small deterministic fixtures
cover negation, ambiguity, contradiction, one-review wording, low confidence, missing evidence, and
category mismatch. Real-catalog descriptive statistics are reported separately from labeled fixture
metrics.

