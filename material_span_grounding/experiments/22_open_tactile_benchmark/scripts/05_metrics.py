#!/usr/bin/env python3
"""Turn cached per-image scores into the Exp22 result tables.

Threshold policy (fixed before any test number is read):
  * every model's per-attribute threshold is chosen by F1 on the Amazon
    *development* split, on a 0.05..0.95 grid;
  * that same threshold is transferred unchanged to the Amazon test split and to
    FabricVST.  FabricVST has no validation set of its own, so this is the
    "source-domain validation threshold" option of Step 22.7 and the external
    primary metrics stay AUROC / AUPRC, which need no threshold at all.
  * for the CLIP-family models the prompt template is also selected on
    development, by macro AUROC.

Track B aggregates the 24 fixed crops of each fabric to one fabric-level score by
the mean sigmoid probability (median reported as supplementary), and evaluates 50
fabrics -- never 1 200 crops -- as independent units.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import common22 as C

SCORES = C.CACHE / "scores"

# display name -> (cache key, family, native taxonomy)
REGISTRY = [
    ("Category-only (no pixels)", "category_only", "control", "last2"),
    ("FashionCLIP zero-shot", "fashionclip_zeroshot", "clip", "common8"),
    ("CLIP-Texture protocol (ViT-L/14)", "clip_texture_vitl14", "clip", "common8"),
    ("SigLIP2-so400m", "siglip2_so400m_384", "clip", "common8"),
    ("Qwen3-VL-8B-Instruct", "qwen3vl_8b", "vlm", "common8"),
    ("Qwen3-VL-32B-Instruct", "qwen3vl_32b", "vlm", "common8"),
    ("InternVL3.5-8B", "internvl3_5_8b", "vlm", "common8"),
    ("FashionCLIP frozen head (ours)", "fashionclip_frozen", "ours", "last2"),
    ("Last2 (ours)", "last2", "ours", "last2"),
    ("FabricVST-B 18attr (ours)", "fabricvst_B", "ours", "fabricvst18"),
    ("FabricVST-A 24attr (ours)", "fabricvst_A", "ours", "fabricvst24"),
]

NATIVE = {"last2": C.LAST2_CLASSES, "fabricvst24": C.FABRICVST24,
          "fabricvst18": C.FABRICVST18, "common8": C.COMMON8}


def load_scores(key, track, template=None):
    path = SCORES / f"{key}__{track}.npz"
    if not path.is_file():
        return None
    blob = np.load(path, allow_pickle=True)
    if "probabilities" in blob:
        probabilities = blob["probabilities"]
    else:
        field = f"probabilities__{template or 'paired_generic'}"
        probabilities = blob[field]
    missing = int(np.isnan(probabilities).sum())
    if missing:
        # Refuse to quietly average over NaN: it would corrupt thresholds and AUROC.
        raise RuntimeError(f"{key}/{track}: {missing} NaN scores in {path.name}; "
                           "rescore this model rather than reporting it")
    return probabilities, [str(c) for c in blob["classes"]], blob


def to_common8(probabilities, classes):
    index = {c: i for i, c in enumerate(classes)}
    missing = [a for a in C.COMMON8 if a not in index]
    if missing:
        raise KeyError(f"model is missing common attributes {missing}")
    return probabilities[:, [index[a] for a in C.COMMON8]]


def amazon_block(split):
    data = C.load_amazon(split)
    idx = [data["classes"].index(a) for a in C.COMMON8]
    return data, data["labels"][:, idx].astype(int), data["mask"][:, idx]


def select_clip_template(key, dev_labels, dev_mask):
    """Macro AUROC on development decides the prompt template.  Test is untouched."""
    from sklearn.metrics import roc_auc_score

    best, table = None, {}
    for template in C.CLIP_TEMPLATES:
        got = load_scores(key, "amazon_development", template)
        if got is None:
            return None, {}
        probabilities, classes, _ = got
        scores = to_common8(probabilities, classes)
        per = []
        for j in range(len(C.COMMON8)):
            keep = dev_mask[:, j]
            t, s = dev_labels[keep, j], scores[keep, j]
            if len(np.unique(t)) > 1:
                per.append(roc_auc_score(t, s))
        macro = float(np.mean(per)) if per else None
        table[template] = macro
        if macro is not None and (best is None or macro > table[best]):
            best = template
    return best, table


def fabric_level(key, template, aggregation="mean"):
    got = load_scores(key, "fabricvst_subset", template)
    if got is None:
        return None, None
    probabilities, classes, blob = got
    scores = to_common8(probabilities, classes)
    fabrics = [str(u) for u in blob["unit_ids"]]
    order = sorted(set(fabrics))
    reduce = np.mean if aggregation == "mean" else np.median
    stacked = np.stack([
        reduce(scores[[i for i, f in enumerate(fabrics) if f == fabric]], axis=0)
        for fabric in order
    ])
    return stacked, order


def main() -> int:
    dev_data, dev_labels, dev_mask = amazon_block("development")
    test_data, test_labels, test_mask = amazon_block("test")

    fab = C.load_fabricvst()
    fab_idx = [fab["attributes"].index(a) for a in C.COMMON8]
    fab_order_from_labels = fab["fabric_ids"]

    rows_model, rows_attr, rows_rate, rows_ood = [], [], [], []
    warnings_all = {}
    template_table = {}
    thresholds_all = {}

    for display, key, family, _native in REGISTRY:
        dev = load_scores(key, "amazon_development")
        if dev is None and family == "clip":
            pass
        template = None
        if family == "clip":
            template, table = select_clip_template(key, dev_labels, dev_mask)
            if template is None:
                print(f"skip {display}: no cached scores", flush=True)
                continue
            template_table[key] = {"selected_on": "amazon_development macro AUROC",
                                   "selected": template, "macro_auroc_by_template": table}
        got_dev = load_scores(key, "amazon_development", template)
        if got_dev is None:
            print(f"skip {display}: no cached scores", flush=True)
            continue
        dev_scores = to_common8(*got_dev[:2])

        # --- thresholds from development only
        thresholds = {}
        for j, attribute in enumerate(C.COMMON8):
            keep = dev_mask[:, j]
            thresholds[attribute] = (
                C.choose_threshold(dev_labels[keep, j], dev_scores[keep, j])
                if keep.sum() and len(np.unique(dev_labels[keep, j])) > 1 else 0.5
            )
        thresholds_all[key] = thresholds

        # --- Track A test
        got_test = load_scores(key, "amazon_test", template)
        if got_test is not None:
            test_scores = to_common8(*got_test[:2])
            per_attribute, micro_t, micro_p = {}, [], []
            for j, attribute in enumerate(C.COMMON8):
                keep = test_mask[:, j]
                t, s = test_labels[keep, j], test_scores[keep, j]
                row = C.attribute_metrics(t, s, thresholds[attribute])
                row["all_positive_f1"] = C.all_positive_f1(row["gt_prevalence"] or 0.0)
                per_attribute[attribute] = row
                micro_t += list(t)
                micro_p += list((s >= thresholds[attribute]).astype(int))
                rows_attr.append({"track": "A_amazon_test", "model": display,
                                  "family": family, "attribute": attribute, **row})
                rows_rate.append({"track": "A_amazon_test", "model": display,
                                  "attribute": attribute,
                                  "gt_prevalence": row["gt_prevalence"],
                                  "prediction_positive_rate": row["prediction_positive_rate"],
                                  "threshold": row["threshold"],
                                  "score_mean": row["score_mean"], "score_std": row["score_std"],
                                  "score_min": row["score_min"], "score_max": row["score_max"]})
            summary = C.macro_summary(
                {k: dict(v) for k, v in per_attribute.items()},
                (np.array(micro_t), np.array(micro_p)))
            ci = C.bootstrap_macro_auroc(test_labels, test_mask, test_scores, C.COMMON8)
            rows_model.append({"track": "A_amazon_test", "model": display, "family": family,
                               "prompt_template": template or "", **summary,
                               "macro_auroc_ci_low": ci["ci_low"], "macro_auroc_ci_high": ci["ci_high"]})
            warnings_all[f"A_amazon_test/{display}"] = C.degeneracy_warnings(per_attribute)

        # --- Track B FabricVST (fabric-level)
        for aggregation in ("mean", "median"):
            stacked, order = fabric_level(key, template, aggregation)
            if stacked is None:
                continue
            reindex = [fab_order_from_labels.index(f) for f in order]
            labels = fab["labels"][reindex][:, fab_idx].astype(int)
            mask = fab["mask"][reindex][:, fab_idx]
            per_attribute = {}
            for j, attribute in enumerate(C.COMMON8):
                keep = mask[:, j]
                row = C.attribute_metrics(labels[keep, j], stacked[keep, j], thresholds[attribute])
                row["all_positive_f1"] = C.all_positive_f1(row["gt_prevalence"] or 0.0)
                per_attribute[attribute] = row
                if aggregation == C.CROP_AGGREGATION:
                    rows_attr.append({"track": "B_fabricvst_ood", "model": display,
                                      "family": family, "attribute": attribute, **row})
                    rows_rate.append({"track": "B_fabricvst_ood", "model": display,
                                      "attribute": attribute,
                                      "gt_prevalence": row["gt_prevalence"],
                                      "prediction_positive_rate": row["prediction_positive_rate"],
                                      "threshold": row["threshold"],
                                      "score_mean": row["score_mean"], "score_std": row["score_std"],
                                      "score_min": row["score_min"], "score_max": row["score_max"]})
            summary = C.macro_summary({k: dict(v) for k, v in per_attribute.items()})
            ci = C.bootstrap_macro_auroc(labels, mask, stacked, C.COMMON8)
            rows_ood.append({"model": display, "family": family, "aggregation": aggregation,
                             "n_fabrics": len(order), "prompt_template": template or "",
                             **summary,
                             "macro_auroc_ci_low": ci["ci_low"], "macro_auroc_ci_high": ci["ci_high"]})
            if aggregation == C.CROP_AGGREGATION:
                rows_model.append({"track": "B_fabricvst_ood", "model": display, "family": family,
                                   "prompt_template": template or "", **summary,
                                   "macro_auroc_ci_low": ci["ci_low"],
                                   "macro_auroc_ci_high": ci["ci_high"]})
                warnings_all[f"B_fabricvst_ood/{display}"] = C.degeneracy_warnings(per_attribute)

        print(f"done {display}", flush=True)

    # --- paired contrasts the report's claims rest on ----------------------
    contrasts = {}
    store = {}
    for _display, key, family, _native in REGISTRY:
        template = template_table.get(key, {}).get("selected") if family == "clip" else None
        got = load_scores(key, "amazon_test", template)
        if got is not None:
            store[("A", key)] = to_common8(*got[:2])
        stacked, order = fabric_level(key, template, C.CROP_AGGREGATION)
        if stacked is not None:
            store[("B", key)] = (stacked, order)

    if ("A", "last2") in store and ("A", "category_only") in store:
        contrasts["A_last2_minus_category_only"] = C.paired_bootstrap_macro_auroc(
            test_labels, test_mask, store[("A", "last2")],
            store[("A", "category_only")], C.COMMON8)
    for challenger in ("siglip2_so400m_384", "qwen3vl_32b", "qwen3vl_8b", "internvl3_5_8b"):
        if ("A", challenger) in store and ("A", "last2") in store:
            contrasts[f"A_last2_minus_{challenger}"] = C.paired_bootstrap_macro_auroc(
                test_labels, test_mask, store[("A", "last2")],
                store[("A", challenger)], C.COMMON8)
        if ("B", challenger) in store and ("B", "last2") in store:
            stacked_c, order_c = store[("B", challenger)]
            stacked_l, order_l = store[("B", "last2")]
            reindex = [fab_order_from_labels.index(f) for f in order_l]
            labels_b = fab["labels"][reindex][:, fab_idx].astype(int)
            mask_b = fab["mask"][reindex][:, fab_idx]
            contrasts[f"B_{challenger}_minus_last2"] = C.paired_bootstrap_macro_auroc(
                labels_b, mask_b, stacked_c, stacked_l, C.COMMON8)
    C.write_json(C.RESULTS / "paired_contrasts.json", contrasts)
    for name, value in contrasts.items():
        print(f"  contrast {name}: delta {value['delta']:+.4f} "
              f"[{value['ci_low']:+.4f}, {value['ci_high']:+.4f}] "
              f"{'significant' if value.get('excludes_zero') else 'ns'}", flush=True)

    pd.DataFrame(rows_model).to_csv(C.RESULTS / "model_metrics.csv", index=False)
    pd.DataFrame(rows_attr).to_csv(C.RESULTS / "per_attribute_metrics.csv", index=False)
    pd.DataFrame(rows_rate).to_csv(C.RESULTS / "prediction_rates.csv", index=False)
    pd.DataFrame(rows_ood).to_csv(C.RESULTS / "fabricvst_ood_metrics.csv", index=False)
    C.write_json(C.RESULTS / "degeneracy_warnings.json", warnings_all)
    C.write_json(C.ARTIFACTS / "clip_prompt_selection.json", template_table)
    C.write_json(C.ARTIFACTS / "thresholds_from_development.json", thresholds_all)

    show = pd.DataFrame(rows_model)
    for track in show["track"].unique():
        block = show[show["track"] == track].sort_values("macro_auroc", ascending=False)
        print(f"\n===== {track} =====")
        print(block[["model", "macro_auroc", "macro_auprc", "macro_f1",
                     "mean_prediction_positive_rate", "mean_gt_prevalence"]]
              .to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
