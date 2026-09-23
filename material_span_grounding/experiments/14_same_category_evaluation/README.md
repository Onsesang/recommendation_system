# Same-category evaluation

Post-hoc diagnostic of the frozen official v3 FashionCLIP `last2` checkpoint.
No model training, threshold selection, target generation, or Qwen grounding is
performed. The existing experiment 13 Category-only checkpoint is evaluated as
an empirical constant-score baseline within each category.

```bash
PY=/home/user/onsesang/miniconda3/envs/texture/bin/python
$PY scripts/extract_predictions.py
$PY -m unittest discover -s tests -v
$PY scripts/evaluate_same_category.py
$PY scripts/extract_predictions.py --verify-only
$PY scripts/evaluate_same_category.py --verify-only
```

The pinned FashionCLIP snapshot is loaded directly from the workspace cache
path recorded in `config.json`; no network lookup or download is used.

The primary reliable-support definition (at least 10 positives and 10
negatives per category/class cell) and 1,000 family-bootstrap replicates are
fixed in `config.json`.
