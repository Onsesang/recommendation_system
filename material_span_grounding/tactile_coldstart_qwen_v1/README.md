# Review-Cold-Start Tactile Retrieval — Qwen v1

This directory is an isolated, reproducible implementation of phases 0–11 in
`../TACTILE_REVIEW_COLDSTART_EXPERIMENT_PLAN_QWEN.md`. The parent repository's raw
reviews, Qwen outputs, product metadata, images, and frozen image embeddings are
read-only inputs. Generated files stay below this directory.

The experiment distinguishes review-unobserved targets, reviewer disagreement,
and visual abstention. It never treats missing review mentions as neutral and it
never trains UNKNOWN as a tactile class.

Run commands are exposed through `scripts/run_phase.py`. Every phase writes a JSON
manifest and a Markdown report even when a research gate fails or an external
dataset is unavailable.

## Environments and commands

Qwen text/image inference uses the existing repository-compatible environment:

```bash
PYTHONPATH=src:/home/user/onsesang/material_span_grounding \
  /home/user/onsesang/miniconda3/envs/material_vllm312/bin/python scripts/run_phase.py 2
PYTHONPATH=src:/home/user/onsesang/material_span_grounding \
  /home/user/onsesang/miniconda3/envs/material_vllm312/bin/python scripts/run_phase.py 6-vlm
```

Statistical analysis, frozen visual encoders, and tests use the `texture` environment:

```bash
PYTHONPATH=src:/home/user/onsesang/material_span_grounding \
  /home/user/onsesang/miniconda3/envs/texture/bin/python scripts/run_phase.py 0
PYTHONPATH=src:/home/user/onsesang/material_span_grounding \
  /home/user/onsesang/miniconda3/envs/texture/bin/python scripts/run_phase.py 1
PYTHONPATH=src:/home/user/onsesang/material_span_grounding \
  /home/user/onsesang/miniconda3/envs/texture/bin/python scripts/run_phase.py 3
```

Continue with `4`, `4-eval`, `5`, `6-dino`, `6-7`, `8`, `9`, `10`, and `11`.
`4-eval` intentionally reports a pending state until a human fills the exported
annotation sheet. All model selection and abstention thresholds use development
data; test reviews are evaluation-only.
