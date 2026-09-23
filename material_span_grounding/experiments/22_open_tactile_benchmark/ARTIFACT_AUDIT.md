# Experiment 22 — Step 22.0 Artifact Audit

Audited 2026-09-17 01:28–01:40 KST, before any new code was executed.
Nothing in `experiments/01..21` was modified, moved or deleted.

---

## 1. Environment

| item | value |
|---|---|
| host path | `/home/user/onsesang/material_span_grounding` |
| git repository | **none** (`/home/user/onsesang` is not a git repo; `git status` / `git log` unavailable) |
| GPU | 1 × NVIDIA A100 80GB PCIe, driver 560.35.03, CUDA 12.6 |
| **GPU occupancy at audit time** | **67.4 GB / 80 GB already in use, 100 % util, by two pre-existing user jobs** (`pred.py --model Mistral-7B-Instruct-v0.3 --task gov_report`, PIDs 83996 / 84693). Only ≈13.7 GB was free. These jobs belong to the same account and were **not** killed. |
| CPU RAM | 503 GiB total, 486 GiB available |
| disk | `/` 1.8 T, 457 G free (74 % used) |
| internet | reachable (huggingface.co, discord.com both 200) |

### Python environments

| env | python | torch | transformers | notes |
|---|---|---|---|---|
| `/home/user/onsesang/miniconda3/envs/texture` | 3.10.20 | 2.5.1+cu121 | 5.7.0.dev0 | **canonical project env** — used by exp21 driver; has sklearn 1.7.2, matplotlib, pandas, bitsandbytes 0.49.2 |
| `/home/user/onsesang/miniconda3/envs/material_vllm312` | 3.12.13 | 2.13.0+cu130 | 5.15.0 | vLLM 0.27.1, bitsandbytes 0.50.0; **no sklearn / matplotlib** |
| `/home/user/바탕화면/anaconda3` (login default) | 3.12.2 | 2.5.1+cu121 | 5.16.1 | not used by the project pipelines |

Missing everywhere: `open_clip`, `timm`, `faiss`, `qwen_vl_utils`. Any of these needed for Exp22
baselines will be installed **into a separate venv**, never into `texture`, per the fail-safe rule.

---

## 2. Our tactile predictors (all verified by loading the checkpoint)

Raw metadata: `artifacts/checkpoint_audit.json`.

| name | path | size | SHA-256 (prefix) | classes | regime | best epoch |
|---|---|---:|---|---:|---|---:|
| **Last2** | `experiments/12_class_multilabel_fashionclip_ft/models/fashionclip_last2.pt` | 58.3 MB | `073b542a9d6bd445…` | 14 | last2 | 28 |
| Frozen FashionCLIP head | `…/models/fashionclip_frozen.pt` | 30.9 KB | `b8666ba97fd225a6…` | 14 | frozen | 7 |
| **FabricVST-A (24 attr)** | `experiments/21_fabricvst_external/checkpoints/fabricvst_taxonomy/best.pt` | 58.3 MB | `f3b820e977c44101…` | 24 | last2 | 6 |
| **FabricVST-B (18 attr)** | `…/fabricvst_taxonomy/B_best.pt` | 58.3 MB | `ff7cd65eb1d15666…` | 18 | last2 | 15 |
| Category-only | `experiments/13_category_only_baseline/models/category_only_best.pt` | 11.2 KB | `85989f5f7ebd8fc5…` | 14 | — | 3 |

The `last2` SHA-256 matches the value recorded in `GPT_HANDOFF_20260917.md`
(`073b542a9d6bd4450aa1f48596c756cc0812b1b5d914945e8f94f7c3fda1934a`) — the official checkpoint is intact.

`A` was **not** at a guessed path: the prompt's suggested `B_best.pt` exists, but the 24-attribute
model is stored as plain `best.pt` (sibling `last.pt` / `B_last.pt` are final-epoch copies, not best).

### Architecture (input/output dimensions)

All four CLIP-based heads share one definition:

```
pixel_values (3,224,224)
  → CLIPModel.vision_model            (ViT-B/32, patrickjohncyh/fashion-clip
                                       rev 7e3ba62ce16b379a1ab479346b66f192e76f51b7)
  → visual_projection                 (768 → 512)
  → F.normalize(dim=-1)               ← L2 normalisation IS part of the model
  → nn.Linear(512 → n_classes)        → independent sigmoids
```

Checkpoints store trainable tensors only (37 for last2: last-2 encoder blocks + post_layernorm +
projection + head), prefixed `vision.* / projection.* / head.*`, and are reloaded on top of the
pretrained FashionCLIP snapshot.

> **Checked and cleared:** two training scripts exist —
> `experiments/12_.../train_fashionclip.py` (top level) uses `clip.get_image_features(...)`, which
> does **not** L2-normalise, whereas `experiments/12_.../scripts/train_fashionclip.py` normalises.
> If the shipped checkpoint had come from the top-level script, exp21's reloader (`common.py`,
> which normalises) would have silently mismatched the training-time feature scale and could have
> manufactured the exp21 external-generalisation failure. It did not: the shipped
> `models/fashionclip_last2.pt` carries per-class thresholds and a `regime` field that only the
> `scripts/` variant writes, and its `vision./projection./head.` key prefixes match the `scripts/`
> module. **Exp21's PART A evaluation used the correct architecture; the 0.5843 AUROC is not a
> reload artifact.** Exp22 reuses the same `common.py` loader for consistency.

---

## 3. Datasets

### 3.1 Amazon review-derived tactile labels (Track A ground truth)

- `experiments/12_class_multilabel_fashionclip_ft/artifacts/product_class_targets.npz`
  - `product_ids` (8 498,) · `classes` (14,) · `values` (8 498, 14) float32 · `mask` (8 498, 14) uint8 · `support` · `agreement`
- Split: `tactile_coldstart_qwen_v2_full/manifests/family_split_20260901.json`
  - unit = `parent_product_family`, prediction unit = `asin`, seed 20260901
  - **train 6 300 / development 1 077 / test 1 121**
- Images: `/home/user/onsesang/texture_project/images_train/{asin}.jpg` — 21 059 files;
  **all 8 498 split products have an image present (6300/1077/1121, 100 %).**
- Binarisation convention inherited from exp12, *not* chosen for this experiment:
  `label = values >= 0.5`, evaluated only where `mask == 1`. `mask == 0` is UNKNOWN and is
  dropped from every denominator.

### 3.2 FabricVST (Track B, external OOD)

- Root `data/external/FabricVST/RAS_dataset`, images in `visual_cropped` (50 fabrics × 225 crops = 11 250).
- `experiments/21_fabricvst_external/artifacts/fabricvst_attributes.npz`
  - `fabric_ids` (50,) · `materials` (50,) · `attributes` (24,) · `values` (50,24) · `mask` (50,24)
  - aggregation: strict majority of 5 annotators, ties → negative; unanimous fraction 0.6225.
- No official split ships with the dataset; **no model of ours was ever trained on it**, so all 50
  fabrics are held out. Primary evaluation unit = **fabric** (50), never the 11 250 crops.

### 3.3 Recommendation data (Exp24)

- `experiments/16_strong_recommender_tactile/data/`: `events.parquet`, `users.parquet`,
  `catalog.parquet`, `validation_targets.parquet`, `test_targets.parquet`, `item_metadata.parquet`,
  `child_parent_mapping.parquet`, plus 825 840 catalog images.
- **Full-catalog tactile prediction cache exists**:
  `experiments/16_strong_recommender_tactile/artifacts/product_tactile_profiles.parquet` —
  (825 840, 16) = `iid`, `parent_asin` + the 14 Last2 probabilities. No re-inference needed for Last2.
- exp17 config: `experiments/17_history3_recommender_refresh/configs/experiment.json`
  (seed 20260904, history_min 3, dim 64, maxlen 50, 2 layers/2 heads, candidate K grid
  [100,300,500,1000,3000], alpha grid 0→1 step 0.05, 1000 bootstrap replicates,
  `reliable_classes` = smooth, rough, thin, thick, flexible, stiff, warm, cool).
- Per-user test metrics for every backbone are stored as parquet in both exp16b and exp17 artifacts,
  so R0/R1 can be re-derived without retraining.

---

## 4. Discord notifier

`experiments/21_fabricvst_external/scripts/notify.py` already exists and reads
`DISCORD_WEBHOOK_URL`, never printing it. Exp22–24 reuse its delivery logic through a shared
`utils/discord_notify.py`, which additionally
(a) falls back to the 0600 file `<root>/.discord_webhook` (same pattern exp21 used), and
(b) appends the **message text only** to `logs/discord_notifications.jsonl` for reproducibility.
The webhook is not written into any script, report, log line or `ps` argument.
`.discord_webhook` was added to `.gitignore`.

---

## 5. Existing evaluation code reused

| purpose | file |
|---|---|
| model reload + inference + per-attribute metrics | `experiments/21_fabricvst_external/scripts/common.py` |
| Last2 → FabricVST external protocol | `…/scripts/02_eval_last2_external.py` |
| retrained model external protocol | `…/scripts/06_eval_newmodel_external.py` |
| taxonomy mapping of record | `experiments/21_fabricvst_external/config.json` → `mapping` |

---

## 6. Constraints this audit imposes on the Exp22 plan

1. **GPU is shared and mostly full.** 13.7 GB free cannot hold Qwen3-VL-32B-Instruct (cached
   locally) or even an 8B VLM in BF16. Order of work is therefore: CPU/small-GPU models first
   (our four heads, category-only, CLIP-family), VLMs last, with GPU polled in between.
   If the GPU never frees, VLMs run NF4-quantised and the precision difference is recorded
   as a limitation, per the prompt's quantisation rule.
2. **No git.** `git_commit.txt` cannot be produced; each experiment instead stores
   `environment.txt` and a SHA-256 manifest of every input artifact it reads.
3. `open_clip` is absent from every env → the texture/material specialist track uses either a
   `transformers`-native SigLIP/CLIP checkpoint or a dedicated venv; `texture` is left untouched.
