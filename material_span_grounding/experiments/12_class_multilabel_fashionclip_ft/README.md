# V3 atomic-class experiment

Run in order:

1. `scripts/ground_classes.py`
2. `scripts/build_targets.py`
3. `scripts/train_fashionclip.py`
4. `scripts/make_report.py`

The scripts read v2 inputs without modifying them and write only to this
directory. `class_groundings.jsonl` is append-only and resumable.
