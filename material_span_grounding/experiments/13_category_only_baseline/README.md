# Category-only baseline

This experiment measures how much of the v3 14-class tactile performance can
be explained by the existing product `category` field alone. It does not read
images, FashionCLIP representations, titles, descriptions, reviews, or brands.

The locked-test protocol is intentionally split into three commands:

```bash
PY=/home/user/onsesang/miniconda3/envs/texture/bin/python
$PY scripts/prepare.py
$PY scripts/train_select.py
$PY scripts/evaluate_locked_test.py
```

`prepare.py` creates a train/development-only artifact. `train_select.py`
performs optimization, early stopping, and threshold selection without locked
test labels. `evaluate_locked_test.py` consumes the frozen checkpoint and
thresholds once; subsequent calls require `--verify-only` and do not evaluate
the test again.
