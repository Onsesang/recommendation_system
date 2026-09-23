# Repository instructions

## Tactile project rules

- Preserve raw review text and original extracted spans.
- Do not hallucinate tactile evidence.
- Review-derived and image-derived evidence must remain distinguishable.
- Do not collapse the open-vocabulary tactile representation into a fixed taxonomy.
- New recommendation features must expose score breakdowns for debugging and evaluation.
- No recommendation feature may treat purchase history as proof that every tactile attribute was preferred.
- Cross-category tactile preference transfer must never be strong by default.
- All ranking weights must be configurable rather than scattered as magic constants.
- Every new endpoint requires tests.
- Every ranking change requires an offline evaluation path.
- Do not modify raw datasets.
- Do not push, deploy, or modify production data.

