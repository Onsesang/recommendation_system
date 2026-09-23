# Tactile System Evaluation

> Generated: 2026-08-13T12:24:14.348268+00:00
> The recommendation ablation is diagnostic because tactile targets are not time-aware and coverage is low.

## Recommendation ablation

| Strategy | Recall@5 | NDCG@5 | Recall@10 | NDCG@10 | MRR@10 |
|---|---:|---:|---:|---:|---:|
| no_tactile | 0.0060 | 0.0043 | 0.0120 | 0.0062 | 0.0180 |
| global_tactile | 0.0060 | 0.0043 | 0.0120 | 0.0062 | 0.0180 |
| category_conditioned | 0.0060 | 0.0043 | 0.0120 | 0.0062 | 0.0180 |
| context_gated | 0.0060 | 0.0043 | 0.0120 | 0.0062 | 0.0180 |

Coverage: {"history_profile_cases": 46, "history_profile_rate": 0.13855421686746988, "target_item_cases": 5, "target_item_rate": 0.015060240963855422, "candidate_item_rate": 0.03247644041512585}

## Feature evaluation

```json
{
  "description": {
    "products": 500,
    "available_products": 495,
    "coverage": 0.99,
    "summary_items": 3213,
    "contradictory_items": 78,
    "evidence_spans": 3859,
    "evidence_support_rate": 1.0,
    "reviewer_count_correctness": 1.0,
    "deterministic_hallucination_rate": 0.0
  },
  "concern": {
    "products_with_concerns": 42,
    "concerns": 48,
    "evidence_support_rate": 1.0,
    "distinct_reviewer_threshold_pass_rate": 1.0,
    "human_label_metrics": "not_available"
  },
  "comparison": {
    "pairs": 50,
    "dimensions": 679,
    "evidence_support_rate": 1.0,
    "unsupported_value_rate": 0.0
  },
  "alternative": {
    "tasks": 47,
    "unsupported_open_vocabulary_tasks": 1,
    "tasks_with_results": 38,
    "results": 175,
    "directional_success_at_5": 1.0,
    "category_preservation": 1.0,
    "evidence_coverage": 1.0,
    "warning": "self-consistency proxy over the same review-derived concept signals; no human relevance labels"
  },
  "agent": {
    "intent_fixtures": 5,
    "intent_exact_constraint_accuracy": 1.0,
    "retrieved_products": 10,
    "catalog_consistency": 1.0,
    "hallucinated_product_rate": 0.0
  }
}
```

## Interpretation limits

- Current tactile targets aggregate all selected reviews; future publishable evaluation needs time-aware targets.
- Concern precision/recall and alternative human relevance are unavailable without independent labels.
- Description/comparison faithfulness metrics verify exact source support, not linguistic usefulness.
