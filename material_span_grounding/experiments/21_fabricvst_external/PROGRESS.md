# FabricVST experiment progress

Resumable state log. Each stage records its artifacts so an interrupted run can
restart at the next unfinished stage.

## Stage status

| # | Stage | Status | Key artifact |
|---|-------|--------|--------------|
| 0 | Repository analysis | done | this file, `config.json` |
| 1 | FabricVST download | done | `data/external/FabricVST/RAS_dataset.zip` (1,939,640,016 B) |
| 2 | FabricVST structure validation | done | `artifacts/fabricvst_audit.json` |
| 3 | Taxonomy confirmation | done | `artifacts/fabricvst_attributes.npz` |
| 4 | last2 label-space analysis + mapping | done | `results/fabricvst_last2_external/mapping.csv` |
| 5-7 | PART A external evaluation of last2 | done | `results/fabricvst_last2_external/` |
| 8-10 | Qwen FabricVST-taxonomy pseudo-labelling | running | `artifacts/qwen_fabricvst_labels.jsonl` |
| 11-13 | Label grouping, aggregation, quality audit | queued | `results/fabricvst_taxonomy_retraining/` |
| 14-17 | New multi-label model training | queued | `checkpoints/fabricvst_taxonomy/` |
| 18-19 | PART D external evaluation of new model | queued | `results/fabricvst_newmodel_external/` |
| 20-25 | Final report | queued | `FINAL_REPORT.md` |

## Running processes

- `03_qwen_pseudolabel.py --pool selected --batch-size 96` labels 42,060 reviews
  (`logs_qwen_pseudolabel.log`). Append-only and resumable: rerun the same
  command and it skips completed `review_id`s.
- `scripts/run_after_labeling.sh <pid>` waits for that process, resumes any
  stragglers, then runs `07_run_pipeline.py`
  (`logs_pipeline_driver.log`), which chains aggregation, both training groups,
  the external evaluation and the final report, and sends exactly one Discord
  notification at the end.

To restart everything by hand after an interruption:

```bash
export HF_HOME=/home/user/onsesang/.cache/huggingface
cd /home/user/onsesang/material_span_grounding/experiments/21_fabricvst_external
PY=/home/user/onsesang/miniconda3/envs/texture/bin/python
$PY scripts/03_qwen_pseudolabel.py --pool selected --batch-size 96
DISCORD_WEBHOOK_URL="$(cat .discord_webhook)" $PY scripts/07_run_pipeline.py
```

## Environment notes

- Model snapshots live in `/home/user/onsesang/.cache/huggingface`, not the
  default `~/.cache`; `HF_HOME` must point there.
- The `material_vllm312` environment cannot run here: its torch build requires a
  newer driver than the installed 12.6, so labelling uses HF transformers in the
  `texture` environment. Its libstdc++ also needs
  `LD_LIBRARY_PATH=$CONDA_PREFIX/lib` to import at all.

## Stage 8-10 design decisions

- Labelling starts from raw review text, not from the old 14-class pseudo-labels.
- Reviews with no material vocabulary at all (28,883 of 70,943) are not sent to
  Qwen and count as all-unknown, the same supervision Qwen would have produced.
  The lexicon is in `scripts/03a_build_candidate_pool.py`, covers all 24
  attributes, and is applied identically to train, development and test.
  8,492 of 8,498 products keep at least one labelled review.
- First 928 labelled rows: 2.2 % parse errors, 99.35 % of evidence spans appear
  verbatim in their review, 45 % of reviews yield no attribute (these are the
  shortest reviews, processed first).
- Early signal to watch: positive labels dominate heavily (`soft` 0.97 positive
  among known). Reviewers describe properties they notice, rarely their absence,
  so negatives are scarce. `pos_weight` is clipped to [0.25, 4.0] as in
  experiment 12, and the final label-quality table reports this explicitly.

## Stage 1-3 findings

- Official source: <https://sites.google.com/view/multimodalzsl> -> Google Drive
  file id `12RWPLMesmpvsfIjUBxjAID7eQ0nUxv8v` -> `RAS_dataset.zip`, 1.94 GB.
- 50 fabrics (`Material_0` .. `Material_49`), 24 attributes, 5 annotator CSVs.
- All 1,200 fabric x attribute cells carry all 5 annotator votes. Unanimous on
  62.25 % of cells. Aggregated by strict majority, ties negative (rule fixed
  before any model was run).
- Images: `visual/` 1 per fabric (50), `visual_cropped/` 225 per fabric
  (11,250), `tactile/` 225 per fabric (11,250).
- **No split file ships with the dataset.** The paper's 40/5/5 fabric split is
  not distributed, so a deterministic stand-in is stored at
  `splits/fabricvst_fabric_split.json` (seed 20260915) and used only for the
  secondary comparison.
- Attribute name in the data is `shinny`, not `shiny`; dataset spelling is kept
  as authoritative. The data ships glosses for `absorbent`, `embroidered`,
  `jacquard`, `pigment printed` only.

### Why all 50 fabrics are the primary evaluation set

No model in this project has ever seen FabricVST, so every fabric is external.
Restricting to 5 test fabrics would leave 5 labels per attribute, which cannot
support per-attribute metrics. Fabric identity is still never split across
train and evaluation, because FabricVST contributes no training data at all.

## Stage 4-7 findings (PART A)

`last2` = `experiments/12_class_multilabel_fashionclip_ft/models/fashionclip_last2.pt`,
FashionCLIP vision encoder -> visual projection -> L2 norm -> linear head over
14 classes, last-2 blocks fine-tuned, selected on development macro F1 (0.6975;
own test macro F1 0.6010, micro 0.8216). Thresholds stored in the checkpoint
were reused unchanged; no FabricVST label informed any prediction.

Mapping: 8 exact (soft, rough, smooth, thick, thin, cool, warm, stiff),
2 approximate (stretchable<-elastic, fluffy<-spongy), 14 unavailable.
`firm` was deliberately not mapped to `stiff`, and `flexible` not to
`stretchable`.

### Headline result: last2 does not generalise to FabricVST

Fabric-level, exact mappings, all 50 fabrics:

- macro F1 0.5661, micro F1 0.6339
- **macro AUROC 0.5843**, macro AP 0.5810

The F1 values are inflated by degenerate behaviour rather than skill. Recall is
1.000 for soft, rough, thick, warm and stiff because the transferred thresholds
put almost every fabric above the positive boundary, so F1 collapses onto the
base rate. `cool` is the mirror image (precision 1.000, recall 0.042).
Threshold-free AUROC is the honest signal, and it sits near chance, with
`rough` (0.478) and `smooth` (0.475) below chance.

On the 5 paper-style test fabrics macro AUROC is 0.7778, but with 5 labels per
attribute this is noise and is reported as secondary only.
