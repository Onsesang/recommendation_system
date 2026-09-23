# FabricVST external validation and taxonomy retraining

Generated 2026-09-16T14:22:59.

All numbers below are fabric-level unless stated otherwise. FabricVST was
never used to train, fine-tune, threshold or calibrate any model.

## 1. FabricVST

- Source: https://sites.google.com/view/multimodalzsl
- Paper: Guanqun Cao et al., Multimodal Zero-Shot Learning for Tactile Texture Recognition, Robotics and Autonomous Systems, 2024
- Archive: `RAS_dataset.zip`, 1,939,640,016 bytes
- Downloaded path: `/home/user/onsesang/material_span_grounding/data/external/FabricVST/RAS_dataset`
- `visual/`: 50 fabrics, 50 images (1-1 per fabric)
- `visual_cropped/`: 50 fabrics, 11250 images (225-225 per fabric)
- `tactile/`: 50 fabrics, 11250 images (225-225 per fabric)
- Fabrics: 50
- Attributes: 24 (stiff, soft, rough, smooth, thick, thin, cool, warm, ...)
- Annotators: 5, all voting on every cell; unanimous on 0.6225 of cells
- Aggregation: strict majority of available annotator votes; ties resolved to negative
- Official split file present: False

The dataset ships no train/validation/test split file, so the paper's 40/5/5
fabric split could not be loaded. Because no model here is trained on
FabricVST, every fabric is held out, and all 50 fabrics form the primary
evaluation set. A deterministic 40/5/5 stand-in is recorded in
`splits/fabricvst_fabric_split.json` and reported only as a secondary view;
with 5 fabrics its per-attribute metrics rest on 5 labels and are noise.

## 2. Existing last2

- Checkpoint: `/home/user/onsesang/material_span_grounding/experiments/12_class_multilabel_fashionclip_ft/models/fashionclip_last2.pt`
- Architecture: FashionCLIP vision encoder -> visual projection -> L2 normalise
  -> single linear head, sigmoid multi-label over 14 classes; last 2 transformer
  blocks plus post-layernorm and projection fine-tuned.
- Original taxonomy: soft, firm, smooth, rough, non_elastic, elastic, thin, thick, flexible, stiff, warm, cool, spongy, crisp
- Thresholds: taken from the checkpoint, selected on our own development
  split, reused unchanged on FabricVST.

### Mapping to FabricVST

| FabricVST attribute | last2 output | mapping | reason |
| --- | --- | --- | --- |
| soft | soft | exact | identical surface form and meaning |
| rough | rough | exact | identical surface form and meaning |
| smooth | smooth | exact | identical surface form and meaning |
| thick | thick | exact | identical surface form and meaning |
| thin | thin | exact | identical surface form and meaning |
| cool | cool | exact | identical surface form and meaning |
| warm | warm | exact | identical surface form and meaning |
| stiff | stiff | exact | Surface form identical and both denote resistance to deformation. Caveat: last2 treats stiff as the exclusive antonym of flexible, whereas FabricVST lists stiff opposite soft. Recorded as exact, flagged in the report. |
| stretchable | elastic | approximate | elastic implies recovery after extension, stretchable implies extensibility; related but not identical, hence approximate. |
| fluffy | spongy | approximate | spongy denotes compressibility, fluffy denotes light raised-fibre loft; related but not identical, hence approximate. |

Unavailable (14): heavy, delicate, durable, absorbent, holey, flat, bumpy, patterned, striped, shinny, hairy, embroidered, jacquard, pigment printed.

`firm` was deliberately not mapped onto FabricVST `stiff`: in the last2
taxonomy `firm` is the exclusive antonym of `soft`, a different axis from
`stiff`/`flexible`. `flexible` was likewise not mapped onto `stretchable`.

### External evaluation of last2

Exact mappings, all 50 fabrics (n_attributes=8):

| metric | value |
| --- | ---: |
| macro_f1 | 0.5661 |
| micro_f1 | 0.6339 |
| macro_precision | 0.5729 |
| macro_recall | 0.7913 |
| macro_balanced_accuracy | 0.5178 |
| macro_auroc | 0.5843 |
| macro_average_precision | 0.5810 |

| attribute | last2 class | F1 | precision | recall | AUROC | positives/50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| soft | soft | 0.864 | 0.760 | 1.000 | 0.601 | 38/50 |
| rough | rough | 0.750 | 0.600 | 1.000 | 0.478 | 30/50 |
| smooth | smooth | 0.455 | 0.417 | 0.500 | 0.475 | 20/50 |
| thick | thick | 0.703 | 0.553 | 0.963 | 0.631 | 27/50 |
| thin | thin | 0.633 | 0.514 | 0.826 | 0.625 | 23/50 |
| cool | cool | 0.080 | 1.000 | 0.042 | 0.651 | 24/50 |
| warm | warm | 0.684 | 0.520 | 1.000 | 0.647 | 26/50 |
| stiff | stiff | 0.361 | 0.220 | 1.000 | 0.566 | 11/50 |

The F1 column overstates the model. Recall reaches 1.000 on several
attributes because the transferred thresholds place nearly every fabric
above the positive boundary, so F1 collapses onto the base rate, while
`cool` shows the mirror failure. Threshold-free AUROC is the honest
signal and sits near chance.

## 3. Qwen pseudo-label rebuilding

- Model: Qwen/Qwen3-VL-32B-Instruct revision `0cfaf48183f594c314753d30a4c4974bc75f3ccb`, bitsandbytes_nf4_double_quant_bfloat16, greedy decoding
- Prompt: `prompts/fabricvst_tactile_pseudolabel.md` (version `fabricvst_tactile_pseudolabel_v1`)
- Reviews labelled: 42158
- Reviews yielding no attribute: 15245
- Parse errors: 1773
- Evidence spans verbatim in the review: 0.9847
- Products: 8498 (8498 with an image)
- Aggregation rule: {"rule": "confidence-weighted vote over known review labels", "min_confidence": 0.55, "min_evidence_count": 1, "margin": 0.0, "note": "fixed before training; never tuned on any test split"}

Labelling ran from raw review text against the 24 FabricVST attributes with
positive / negative / unknown states; the old 14-class pseudo-labels were not
converted. Reviews containing no material vocabulary at all were not sent to
Qwen and are treated as all-unknown, which is the supervision they would have
contributed anyway; the filter is applied identically across all splits.

| attribute | known ratio | positive ratio (known) | product P | product N | product U |
| --- | ---: | ---: | ---: | ---: | ---: |
| stiff | 0.077 | 0.816 | 532 | 120 | 7846 |
| soft | 0.640 | 0.956 | 5197 | 238 | 3063 |
| rough | 0.125 | 0.793 | 840 | 219 | 7439 |
| smooth | 0.134 | 0.865 | 982 | 153 | 7363 |
| thick | 0.273 | 0.800 | 1854 | 462 | 6182 |
| thin | 0.531 | 0.947 | 4276 | 241 | 3981 |
| cool | 0.182 | 0.928 | 1439 | 111 | 6948 |
| warm | 0.194 | 0.949 | 1565 | 85 | 6848 |
| fluffy | 0.045 | 0.836 | 321 | 63 | 8114 |
| heavy | 0.139 | 0.670 | 793 | 390 | 7315 |
| delicate | 0.281 | 0.627 | 1501 | 891 | 6106 |
| durable | 0.292 | 0.651 | 1619 | 866 | 6013 |
| stretchable | 0.368 | 0.859 | 2687 | 442 | 5369 |
| absorbent | 0.073 | 0.519 | 322 | 298 | 7878 |
| holey | 0.267 | 0.877 | 1986 | 279 | 6233 |
| flat | 0.090 | 0.677 | 518 | 247 | 7733 |
| bumpy | 0.038 | 0.664 | 217 | 110 | 8171 |
| patterned | 0.087 | 0.922 | 682 | 58 | 7758 |
| striped | 0.030 | 0.473 | 121 | 135 | 8242 |
| shinny | 0.052 | 0.799 | 351 | 88 | 8059 |
| hairy | 0.022 | 0.674 | 124 | 60 | 8314 |
| embroidered | 0.020 | 0.592 | 100 | 69 | 8329 |
| jacquard | 0.007 | 0.121 | 7 | 51 | 8440 |
| pigment printed | 0.019 | 0.648 | 105 | 57 | 8336 |

Sparse attributes (known on under 5 % of products): fluffy, bumpy, striped, hairy, embroidered, jacquard, pigment printed.
Severely skewed attributes: soft.

## 4. New image model

- Encoder: patrickjohncyh/fashion-clip revision `7e3ba62ce16b379a1ab479346b66f192e76f51b7`
- Regime: last2 (identical to last2)
- Head: single linear layer, independent sigmoid per attribute
- Loss: BCEWithLogits with per-attribute `pos_weight` from the training split,
  masked so `unknown` contributes no gradient
- Attribute group B (tactile subset): 18 attributes
- Split (product-level, family-disjoint): {"train": 6300, "development": 1077, "test": 1121}
- Best epoch: 15, seed 20260915

Internal held-out test (our own review-image data):

| metric | group B | group A |
| --- | ---: | ---: |
| macro_f1 | 0.8731 | 0.8463 |
| micro_f1 | 0.9123 | 0.9124 |
| macro_precision | 0.7905 | 0.7806 |
| macro_recall | 0.9829 | 0.9724 |
| macro_auroc | 0.6010 | 0.6032 |
| mean_average_precision | 0.8469 | 0.8481 |

## 5. FabricVST external evaluation: old vs new

| Model | Macro F1 | Micro F1 | mAP | Macro Recall | Macro AUROC |
| --- | ---: | ---: | ---: | ---: | ---: |
| old last2 | 0.5661 | 0.6339 | 0.5810 | 0.7913 | 0.5843 |
| FabricVST-taxonomy retrained | 0.6513 | 0.6644 | 0.6050 | 1.0000 | 0.5992 |

The retrained model additionally covers 18 FabricVST
attributes directly (macro F1 0.6062, macro AUROC 0.6003), which last2 could not express at all.

## 6. Attribute-level analysis

| Attribute | old last2 F1 | new model F1 | difference | old AUROC | new AUROC | AUROC difference |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| soft | 0.864 | 0.864 | 0.000 | 0.601 | 0.794 | 0.193 |
| rough | 0.750 | 0.750 | 0.000 | 0.478 | 0.432 | -0.047 |
| smooth | 0.455 | 0.571 | 0.117 | 0.475 | 0.670 | 0.195 |
| thick | 0.703 | 0.701 | -0.001 | 0.631 | 0.581 | -0.050 |
| thin | 0.633 | 0.630 | -0.003 | 0.625 | 0.707 | 0.082 |
| cool | 0.080 | 0.649 | 0.569 | 0.651 | 0.764 | 0.114 |
| warm | 0.684 | 0.684 | 0.000 | 0.647 | 0.421 | -0.226 |
| stiff | 0.361 | 0.361 | 0.000 | 0.566 | 0.424 | -0.142 |

## 7. Conclusion

1. **Does last2 generalise to external fabrics?** Macro AUROC 0.5843 across the eight exactly-mapped attributes, against 0.5 for
   chance. It does not generalise in any usable sense: the decision thresholds
   do not transfer, and the ranking signal is close to chance.
2. **Did FabricVST-aligned retraining help? No.** Macro AUROC moved from 0.5843
   to 0.5992, which is not a real improvement: four attributes rose (`soft`
   +0.193, `smooth` +0.195, `cool` +0.114, `thin` +0.082) and four fell (`warm`
   -0.226, `stiff` -0.142, `thick` -0.050, `rough` -0.047) on 50 fabrics. The
   macro F1 gain of +0.085 is an artefact and must not be reported as progress
   - see the degeneracy analysis below.
3. **Can this be presented as external validation?** Yes as a negative or
   partial result, stated carefully. The honest claim is about whether
   review-grounded tactile supervision transfers to an independent fabric
   dataset, not about achieving competitive FabricVST numbers. Fabric-level
   n is 50, the label source is 5 human annotators, and the image domain
   differs sharply from catalogue photography; conclusions should be framed
   as evidence about transfer, not as a benchmark result.

### Degeneracy analysis: why the macro F1 gain is not progress

On all eight comparable attributes the retrained model predicts **positive for
every one of the 50 fabrics** (recall 1.000, predicted positives 50/50). Six of
the eight selected thresholds sit at 0.10, the floor of the threshold search
grid, meaning even the most permissive threshold cannot separate the fabrics:
every output probability is above it.

The consequence is that F1 becomes a pure function of the base rate. For an
all-positive predictor, F1 = 2p/(1+p) where p is the positive rate:

| attribute | positives/50 | base-rate F1 | reported new F1 |
| --- | ---: | ---: | ---: |
| soft | 38/50 | 0.8636 | 0.8636 |
| rough | 30/50 | 0.7500 | 0.7500 |
| warm | 26/50 | 0.6842 | 0.6842 |
| stiff | 11/50 | 0.3607 | 0.3607 |

These match to four decimal places. The apparent improvement over last2 comes
almost entirely from `cool` (0.080 -> 0.649), where last2 failed in the opposite
direction by predicting almost nothing positive. Swapping one degenerate mode
for another is not learning.

The same pathology is visible on our own held-out data, where the model reaches
macro F1 0.8731 but macro AUROC only 0.6010. A model that ranked fabrics well
would not show that gap.

**Root cause: the pseudo-labels are overwhelmingly positive.** Among products
where an attribute is known, the positive share is 0.79 to 0.96 (`soft` 0.956,
`warm` 0.949, `thin` 0.947, `cool` 0.928). Reviewers write about properties they
notice and rarely assert an absence, so negative evidence is scarce. With
`pos_weight` clipped to [0.25, 4.0] the loss cannot compensate, and the model
converges on the class prior instead of on image evidence. Seven of the 24
attributes are additionally known on under 5 % of products.

This is a label-construction problem, not an architecture problem, and it is the
finding that should drive any follow-up work.

### Claims that are NOT supported

- That either model predicts tactile attributes reliably on external fabrics.
- That high F1 on `soft`, `rough` or `warm` reflects skill; those values track
  the base rate under saturated predictions.
- Any per-attribute conclusion from the 5-fabric paper-style test subset.
- That the retrained model improved on last2. Its macro F1 is higher only
  because an all-positive predictor happens to fit these base rates better.
- Any claim built on internal macro F1 0.8731; the matching AUROC is 0.6010.

## 8. Reproducibility

```bash
export HF_HOME=/home/user/onsesang/.cache/huggingface
cd /home/user/onsesang/material_span_grounding/experiments/21_fabricvst_external
PY=/home/user/onsesang/miniconda3/envs/texture/bin/python
$PY scripts/01_analyze_fabricvst.py
$PY scripts/02_eval_last2_external.py
$PY scripts/03a_build_candidate_pool.py
$PY scripts/03_qwen_pseudolabel.py --pool selected --batch-size 96
$PY scripts/07_run_pipeline.py   # aggregation, training, external eval, report
```

- Seed: 20260915
- Split IDs: `splits/` (product split inherited from `/home/user/onsesang/material_span_grounding/tactile_coldstart_qwen_v2_full/manifests/family_split_20260901.json`)
- FabricVST source: https://sites.google.com/view/multimodalzsl
- Qwen prompt: `prompts/fabricvst_tactile_pseudolabel.md`
- Best checkpoint: `checkpoints/fabricvst_taxonomy/B_best.pt`
- Packages:
  - accelerate==1.13.0
  - bitsandbytes==0.49.2
  - numpy==2.2.6
  - pillow==12.2.0
  - scikit-learn==1.7.2
  - torch==2.5.1+cu121

The Discord webhook is read from `DISCORD_WEBHOOK_URL` and is never printed
or stored in this repository.

