# Phase 0 — Protocol Freeze

- Reviews: 4,158
- Exact span verification rows: 6,345
- Qwen-accepted claims: 4,527
- Deduplicated visible product families: 465
- Qwen: `Qwen/Qwen3-VL-8B-Instruct` / `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b`
- Taxonomy: `tactile_axes_v1`

## Leakage boundary

Current family splits are feasibility splits. The prior 70-product test has already been inspected, and all current families existed during prototype development. A paper-level independent Amazon test requires newly sampled, previously unused product families. Test reviews in these feasibility splits are nevertheless hidden from model training, calibration, and query construction.
