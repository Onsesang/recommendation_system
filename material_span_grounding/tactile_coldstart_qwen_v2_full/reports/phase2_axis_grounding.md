# Phase 2 — Qwen Review-Span Axis Grounding

- Model: `Qwen/Qwen3-VL-8B-Instruct` / `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b`
- Prompt/schema: `tactile_axis_grounding_v2_conservative_numeric_local_context` / `tactile_axis_mapping_v2_numeric6`
- Schema success: 8,641/8,641
- Mappable: 5,710
- Unmappable preserved: 2,931

Qwen produced symbolic axis/pole/intensity labels only. Numeric scores are created later by deterministic config conversion. Original exact spans and local review contexts remain in every output record.
