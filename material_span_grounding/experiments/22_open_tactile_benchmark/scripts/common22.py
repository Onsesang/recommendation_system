#!/usr/bin/env python3
"""Shared paths, taxonomy, metrics and degeneracy diagnostics for experiment 22.

Everything in this module is fixed *before* any model is scored.  Nothing here
may be edited in response to a result: the taxonomy mapping, the label
binarisation rule, the evaluation unit, the crop subset and the threshold policy
are all decided up front and recorded in ``artifacts/``.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("HF_HOME", "/home/user/onsesang/.cache/huggingface")

import numpy as np

EXP = Path(__file__).resolve().parents[1]
PROJECT = EXP.parents[1]
ARTIFACTS = EXP / "artifacts"
RESULTS = EXP / "results"
PLOTS = EXP / "plots"
CACHE = EXP / "cache"
LOGS = EXP / "logs"
for _d in (ARTIFACTS, RESULTS, PLOTS, CACHE, LOGS):
    _d.mkdir(parents=True, exist_ok=True)

SEED = 20260917

# ---------------------------------------------------------------- input paths
AMAZON_TARGETS = PROJECT / "experiments/12_class_multilabel_fashionclip_ft/artifacts/product_class_targets.npz"
AMAZON_SPLIT = PROJECT / "tactile_coldstart_qwen_v2_full/manifests/family_split_20260901.json"
AMAZON_MASTER = PROJECT / "tactile_coldstart_qwen_v2_full/data/product_master_full_pool.json"
AMAZON_IMAGES = Path("/home/user/onsesang/texture_project/images_train")

FABRICVST_ATTR = PROJECT / "experiments/21_fabricvst_external/artifacts/fabricvst_attributes.npz"
FABRICVST_ROOT = PROJECT / "data/external/FabricVST/RAS_dataset"
FABRICVST_CROPS = FABRICVST_ROOT / "visual_cropped"

CKPT = {
    "last2": PROJECT / "experiments/12_class_multilabel_fashionclip_ft/models/fashionclip_last2.pt",
    "fashionclip_frozen": PROJECT / "experiments/12_class_multilabel_fashionclip_ft/models/fashionclip_frozen.pt",
    "fabricvst_A": PROJECT / "experiments/21_fabricvst_external/checkpoints/fabricvst_taxonomy/best.pt",
    "fabricvst_B": PROJECT / "experiments/21_fabricvst_external/checkpoints/fabricvst_taxonomy/B_best.pt",
    "category_only": PROJECT / "experiments/13_category_only_baseline/models/category_only_best.pt",
}

FASHIONCLIP_ID = "patrickjohncyh/fashion-clip"
FASHIONCLIP_REV = "7e3ba62ce16b379a1ab479346b66f192e76f51b7"

# ------------------------------------------------------------------- taxonomy
# The eight attributes that map EXACTLY between the Last2 14-class taxonomy and
# the FabricVST 24-attribute taxonomy.  Inherited verbatim from
# experiments/21_fabricvst_external/config.json -> mapping.exact, so the mapping
# predates this experiment and was not chosen to favour any model.
COMMON8 = ["soft", "rough", "smooth", "thick", "thin", "cool", "warm", "stiff"]

LAST2_CLASSES = [
    "soft", "firm", "smooth", "rough", "non_elastic", "elastic", "thin",
    "thick", "flexible", "stiff", "warm", "cool", "spongy", "crisp",
]
FABRICVST24 = [
    "stiff", "soft", "rough", "smooth", "thick", "thin", "cool", "warm",
    "fluffy", "heavy", "delicate", "durable", "stretchable", "absorbent",
    "holey", "flat", "bumpy", "patterned", "striped", "shinny", "hairy",
    "embroidered", "jacquard", "pigment printed",
]
FABRICVST18 = FABRICVST24[:17] + ["hairy"]

# ------------------------------------------------------- prompts (frozen v1.0)
PROMPT_VERSION = "v1.0-20260917"

# Natural-language gloss of each attribute, shared by the VLM and CLIP scorers so
# that no model gets a better-worded description than another.
ATTRIBUTE_GLOSS = {
    "soft": "soft — yields pleasantly to the touch, not firm",
    "rough": "rough — coarse or scratchy against the skin, not smooth",
    "smooth": "smooth — even and slick to the touch, without coarseness",
    "thick": "thick — substantial, heavy-gauge fabric",
    "thin": "thin — lightweight, fine-gauge fabric",
    "cool": "cool — feels cool against the skin",
    "warm": "warm — feels warm, insulating against the skin",
    "stiff": "stiff — resists bending, holds its shape",
}

# Paired text prompts for CLIP-family scoring.  Every attribute uses the same
# template, so no attribute is hand-tuned.  The negative pole is the explicit
# negation rather than a hand-picked antonym, because the prompt's rule forbids
# inventing bipolar opposites for attributes that are not guaranteed antonyms.
CLIP_POSITIVE = "a photo of a garment whose fabric feels {gloss}"
CLIP_NEGATIVE = "a photo of a garment whose fabric does not feel {word}"

VLM_PROMPT = (
    "You are shown a photograph of a garment.\n\n"
    "Question: does the visual evidence in this image support the tactile "
    "attribute {word_upper} ({gloss})?\n\n"
    "Judge only from what the image shows about the fabric: weave, pile, sheen, "
    "drape, knit gauge and surface texture. Do not infer the answer from the "
    "garment category alone when the visual evidence is insufficient.\n\n"
    "Answer with exactly one word, YES or NO."
)


# Three fixed paired-prompt templates for CLIP-family scoring.  All three are
# written before any model runs; the one used on test / FabricVST is whichever
# maximises macro AUROC on the Amazon *development* split, selected per model and
# recorded in artifacts/clip_prompt_selection.json.  Test is never consulted.
CLIP_TEMPLATES = {
    # our generic paired template, the same wording the VLM prompt uses
    "paired_generic": (
        "a photo of a garment whose fabric feels {gloss}",
        "a photo of a garment whose fabric does not feel {word}",
    ),
    # the CLIP-Texture protocol (Wu et al., ECCV CVinW 2022, cvl-umass/clip-texture):
    # that work reports no new checkpoint, only stock CLIP with an
    # "a photo of a {c} <noun>" texture prompt; <noun> is specialised to fabric here
    "clip_texture": (
        "a photo of a {word} fabric",
        "a photo of a not {word} fabric",
    ),
    # bare class words, the weakest-prompt control from the same paper
    "bare_word": ("{word}", "not {word}"),
}


def clip_prompts(attribute: str, template: str = "paired_generic") -> tuple[str, str]:
    positive, negative = CLIP_TEMPLATES[template]
    gloss = ATTRIBUTE_GLOSS[attribute]
    return (
        positive.format(gloss=gloss, word=attribute),
        negative.format(gloss=gloss, word=attribute),
    )


def vlm_prompt(attribute: str) -> str:
    return VLM_PROMPT.format(
        word_upper=attribute.upper(), gloss=ATTRIBUTE_GLOSS[attribute]
    )


# ------------------------------------------------------------ evaluation rules
# Track B: FabricVST labels are fabric-level, so 225 crops of one fabric are NOT
# 225 samples.  The evaluation unit is the fabric.  Crop scores are aggregated by
# the mean sigmoid probability -- the same rule experiment 21 pre-registered.
CROP_AGGREGATION = "mean"
CROP_AGGREGATION_SUPPLEMENTARY = "median"
# A VLM cannot afford 11 250 crops, so every model is compared on one identical
# deterministic subset of crops per fabric.  Fixed here, before any scoring.
CROPS_PER_FABRIC = 24

BOOTSTRAP_REPLICATES = 2000


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=float))


def read_json(path: Path):
    return json.loads(Path(path).read_text())


# ------------------------------------------------------------------- data load
def load_amazon(split: str) -> dict:
    """Return the Amazon evaluation block for one split.

    ``labels`` is binarised with the rule inherited from experiment 12
    (``values >= 0.5``) and ``mask`` marks the known cells.  Unknown cells are
    never treated as negative.
    """
    blob = np.load(AMAZON_TARGETS, allow_pickle=True)
    ids = blob["product_ids"].astype(str)
    classes = [str(c) for c in blob["classes"]]
    values = blob["values"].astype(np.float32)
    mask = blob["mask"].astype(bool)
    index = {pid: i for i, pid in enumerate(ids)}

    wanted = read_json(AMAZON_SPLIT)["splits"][split]
    rows, kept = [], []
    for pid in wanted:
        i = index.get(pid)
        if i is None or not mask[i].any():
            continue
        if not (AMAZON_IMAGES / f"{pid}.jpg").is_file():
            continue
        rows.append(i)
        kept.append(pid)
    rows = np.asarray(rows)

    master = read_json(AMAZON_MASTER)
    if isinstance(master, dict):
        master = list(master.values())
    category = {str(r["product_id"]): str(r.get("category", "<UNK>")) for r in master}

    return {
        "split": split,
        "product_ids": kept,
        "classes": classes,
        "labels": (values[rows] >= 0.5).astype(np.int8),
        "mask": mask[rows],
        "categories": [category.get(p, "<UNK>") for p in kept],
        "image_paths": [AMAZON_IMAGES / f"{p}.jpg" for p in kept],
    }


def load_fabricvst() -> dict:
    blob = np.load(FABRICVST_ATTR, allow_pickle=True)
    return {
        "fabric_ids": [str(x) for x in blob["fabric_ids"]],
        "materials": [str(x) for x in blob["materials"]],
        "attributes": [str(x) for x in blob["attributes"]],
        "labels": (blob["values"] >= 0.5).astype(np.int8),
        "mask": blob["mask"].astype(bool),
    }


def fabricvst_crop_subset() -> dict[str, list[Path]]:
    """Deterministic ``CROPS_PER_FABRIC`` crops per fabric, seeded, sorted."""
    rng = np.random.default_rng(SEED)
    chosen: dict[str, list[Path]] = {}
    for fabric_dir in sorted(p for p in FABRICVST_CROPS.iterdir() if p.is_dir()):
        crops = sorted(
            p for p in fabric_dir.iterdir()
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}
        )
        if len(crops) <= CROPS_PER_FABRIC:
            chosen[fabric_dir.name] = crops
        else:
            take = rng.choice(len(crops), size=CROPS_PER_FABRIC, replace=False)
            chosen[fabric_dir.name] = [crops[i] for i in sorted(take)]
    return chosen


# ---------------------------------------------------------------- metrics core
def _safe(fn, truth, score):
    if len(np.unique(truth)) < 2:
        return None
    try:
        return float(fn(truth, score))
    except ValueError:
        return None


def attribute_metrics(truth: np.ndarray, score: np.ndarray, threshold: float) -> dict:
    """Per-attribute metrics plus the Step 22.8 degeneracy diagnostics."""
    from sklearn.metrics import (
        average_precision_score, balanced_accuracy_score, f1_score,
        precision_score, recall_score, roc_auc_score,
    )

    truth = np.asarray(truth).astype(int)
    score = np.asarray(score, dtype=np.float64)
    prediction = (score >= threshold).astype(int)
    n = truth.size
    return {
        "support": int(n),
        "positive": int(truth.sum()),
        "gt_prevalence": float(truth.mean()) if n else None,
        "threshold": float(threshold),
        "predicted_positive": int(prediction.sum()),
        "prediction_positive_rate": float(prediction.mean()) if n else None,
        "score_mean": float(score.mean()) if n else None,
        "score_std": float(score.std()) if n else None,
        "score_min": float(score.min()) if n else None,
        "score_max": float(score.max()) if n else None,
        "auroc": _safe(roc_auc_score, truth, score),
        "auprc": _safe(average_precision_score, truth, score),
        "f1": float(f1_score(truth, prediction, zero_division=0)),
        "precision": float(precision_score(truth, prediction, zero_division=0)),
        "recall": float(recall_score(truth, prediction, zero_division=0)),
        "balanced_accuracy": _safe(balanced_accuracy_score, truth, prediction),
        "accuracy": float((prediction == truth).mean()) if n else None,
    }


def macro_summary(per_attribute: dict[str, dict], micro_pairs=None) -> dict:
    from sklearn.metrics import f1_score

    rows = list(per_attribute.values())

    def mean_of(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return float(np.mean(vals)) if vals else None

    out = {
        "n_attributes": len(rows),
        "macro_auroc": mean_of("auroc"),
        "macro_auprc": mean_of("auprc"),
        "macro_f1": mean_of("f1"),
        "macro_precision": mean_of("precision"),
        "macro_recall": mean_of("recall"),
        "macro_balanced_accuracy": mean_of("balanced_accuracy"),
        "mean_gt_prevalence": mean_of("gt_prevalence"),
        "mean_prediction_positive_rate": mean_of("prediction_positive_rate"),
        "mean_score_std": mean_of("score_std"),
    }
    if micro_pairs is not None:
        truth, prediction = micro_pairs
        out["micro_f1"] = float(f1_score(truth, prediction, zero_division=0))
    return out


def degeneracy_warnings(per_attribute: dict[str, dict], threshold_bounds=(0.05, 0.95)) -> list[str]:
    """Step 22.8: flag the failure modes that make a high F1 meaningless."""
    warnings = []
    low, high = threshold_bounds
    for name, row in per_attribute.items():
        rate = row.get("prediction_positive_rate")
        if rate is not None and rate > 0.95:
            warnings.append(f"{name}: prediction positive rate {rate:.3f} > 0.95 (all-positive collapse)")
        if rate is not None and rate < 0.05:
            warnings.append(f"{name}: prediction positive rate {rate:.3f} < 0.05 (all-negative collapse)")
        if row.get("score_std") is not None and row["score_std"] < 1e-3:
            warnings.append(f"{name}: score std {row['score_std']:.2e} ~ 0 (constant score)")
        t = row.get("threshold")
        if t is not None and (t <= low or t >= high):
            warnings.append(f"{name}: threshold {t:.3f} sits at the search bound")
        auroc, f1 = row.get("auroc"), row.get("f1")
        if auroc is not None and auroc < 0.55 and f1 is not None and f1 > 0.70:
            warnings.append(
                f"{name}: F1 {f1:.3f} is high while AUROC {auroc:.3f} is at chance "
                "(F1 is tracking the base rate, not discrimination)"
            )
    return warnings


def all_positive_f1(prevalence: float) -> float:
    """F1 of a predictor that always says positive: 2p/(1+p)."""
    return 2.0 * prevalence / (1.0 + prevalence) if prevalence > 0 else 0.0


# -------------------------------------------------------------- threshold pick
def choose_threshold(truth: np.ndarray, score: np.ndarray,
                     grid: np.ndarray | None = None) -> float:
    """F1-maximising threshold.  ONLY ever called on a validation split."""
    if grid is None:
        grid = np.round(np.arange(0.05, 0.96, 0.05), 4)
    from sklearn.metrics import f1_score

    truth = np.asarray(truth).astype(int)
    best_t, best_f1 = 0.5, -1.0
    for t in grid:
        f1 = f1_score(truth, (score >= t).astype(int), zero_division=0)
        if f1 > best_f1:
            best_t, best_f1 = float(t), f1
    return best_t


# --------------------------------------------------------------- bootstrap CI
def paired_bootstrap(metric_fn, truth, score_a, score_b, units=None,
                     replicates=BOOTSTRAP_REPLICATES, seed=SEED):
    """Paired bootstrap over evaluation *units* (products or fabrics)."""
    rng = np.random.default_rng(seed)
    n = len(truth) if units is None else len(units)
    deltas = []
    for _ in range(replicates):
        idx = rng.integers(0, n, size=n)
        a = metric_fn(truth[idx], score_a[idx])
        b = metric_fn(truth[idx], score_b[idx])
        if a is None or b is None:
            continue
        deltas.append(a - b)
    if not deltas:
        return {"delta": None, "ci_low": None, "ci_high": None, "replicates": 0}
    deltas = np.asarray(deltas)
    return {
        "delta": float(deltas.mean()),
        "ci_low": float(np.percentile(deltas, 2.5)),
        "ci_high": float(np.percentile(deltas, 97.5)),
        "replicates": int(deltas.size),
    }


def fast_auroc(truth: np.ndarray, score: np.ndarray) -> float | None:
    """Rank-based AUROC (Mann-Whitney U), tie-corrected.  Same value as
    sklearn.roc_auc_score but fast enough for thousands of bootstrap draws."""
    truth = np.asarray(truth)
    n_pos = int(truth.sum())
    n_neg = truth.size - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    order = np.argsort(score, kind="mergesort")
    ranked = score[order]
    ranks = np.empty(score.size, dtype=np.float64)
    i = 0
    while i < ranked.size:
        j = i
        while j + 1 < ranked.size and ranked[j + 1] == ranked[i]:
            j += 1
        ranks[order[i:j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    return float((ranks[truth == 1].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def bootstrap_macro_auroc(labels, mask, scores, attributes, replicates=BOOTSTRAP_REPLICATES,
                          seed=SEED):
    """95 % CI for macro AUROC, resampling evaluation units (rows)."""
    rng = np.random.default_rng(seed)
    n = labels.shape[0]
    draws = []
    for _ in range(replicates):
        idx = rng.integers(0, n, size=n)
        per = []
        for j, _name in enumerate(attributes):
            keep = mask[idx, j]
            t, s = labels[idx, j][keep], scores[idx, j][keep]
            value = fast_auroc(t, s)
            if value is not None:
                per.append(value)
        if per:
            draws.append(float(np.mean(per)))
    if not draws:
        return {"mean": None, "ci_low": None, "ci_high": None}
    draws = np.asarray(draws)
    return {
        "mean": float(draws.mean()),
        "ci_low": float(np.percentile(draws, 2.5)),
        "ci_high": float(np.percentile(draws, 97.5)),
        "replicates": int(draws.size),
    }


def paired_bootstrap_macro_auroc(labels, mask, scores_a, scores_b, attributes,
                                 replicates=BOOTSTRAP_REPLICATES, seed=SEED):
    """Paired bootstrap of macro AUROC difference (a - b) over evaluation units.

    Both models are scored on the SAME resampled units in each replicate, which is
    what makes the comparison paired.  Reporting two overlapping marginal CIs is
    not the same test and is much more conservative.
    """
    rng = np.random.default_rng(seed)
    n = labels.shape[0]
    draws = []
    for _ in range(replicates):
        idx = rng.integers(0, n, size=n)
        per_a, per_b = [], []
        for j, _name in enumerate(attributes):
            keep = mask[idx, j]
            truth = labels[idx, j][keep]
            va = fast_auroc(truth, scores_a[idx, j][keep])
            vb = fast_auroc(truth, scores_b[idx, j][keep])
            if va is not None and vb is not None:
                per_a.append(va)
                per_b.append(vb)
        if per_a:
            draws.append(float(np.mean(per_a) - np.mean(per_b)))
    if not draws:
        return {"delta": None, "ci_low": None, "ci_high": None, "replicates": 0}
    draws = np.asarray(draws)
    return {"delta": float(draws.mean()),
            "ci_low": float(np.percentile(draws, 2.5)),
            "ci_high": float(np.percentile(draws, 97.5)),
            "replicates": int(draws.size),
            "excludes_zero": bool(np.percentile(draws, 2.5) > 0
                                  or np.percentile(draws, 97.5) < 0)}
