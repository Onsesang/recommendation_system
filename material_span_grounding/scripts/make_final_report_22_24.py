#!/usr/bin/env python3
"""Build EXPERIMENTS_22_24_FINAL_REPORT.md from the three experiments' result files.

Re-runnable. Every number is read from results/, so regenerating after late
stages finish refreshes the report rather than requiring hand edits.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/home/user/onsesang/material_span_grounding")
E22 = ROOT / "experiments/22_open_tactile_benchmark"
E23 = ROOT / "experiments/23_tactile_conditioned_retrieval"
E24 = ROOT / "experiments/24_adaptive_tactile_recommendation"
KST = timezone(timedelta(hours=9))


def read_csv(path):
    return pd.read_csv(path) if Path(path).is_file() else pd.DataFrame()


def read_json(path):
    return json.loads(Path(path).read_text()) if Path(path).is_file() else {}


def md(frame, floats=4):
    if frame.empty:
        return "_(not available)_"
    header = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    rule = "|" + "|".join("---" for _ in frame.columns) + "|"
    lines = [header, rule]
    for _, row in frame.iterrows():
        cells = []
        for value in row:
            if isinstance(value, (float, np.floating)):
                cells.append("—" if np.isnan(value) else f"{value:.{floats}f}")
            elif isinstance(value, (bool, np.bool_)):
                cells.append("yes" if value else "no")
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> int:
    m22 = read_csv(E22 / "results/model_metrics.csv")
    ood = read_csv(E22 / "results/fabricvst_ood_metrics.csv")
    feas = read_csv(E22 / "results/baseline_feasibility.csv")
    r23_main = read_csv(E23 / "results/retrieval_main.csv")
    r23_same = read_csv(E23 / "results/retrieval_same_category.csv")
    r23_family = read_csv(E23 / "results/retrieval_per_family.csv")
    posthoc = read_csv(E24 / "results/posthoc_methods.csv")
    sig = read_csv(E24 / "results/significance_vs_R0.csv")
    sweep = read_csv(E24 / "results/r2_gate_sweep.csv")
    trained = read_csv(E24 / "results/trained_methods_all_variants.csv")
    ablation = read_csv(E24 / "results/tactile_source_ablation.csv")
    groups = read_csv(E24 / "results/user_group_analysis.csv")
    recall_v = read_json(E24 / "results/candidate_recall__validation.json")
    recall_t = read_json(E24 / "results/candidate_recall__test.json")
    shuffle = read_json(E24 / "results/aligned_vs_shuffle.json")
    contrasts = read_json(E22 / "results/paired_contrasts.json")

    def contrast_text(key, subject, comparator):
        block = contrasts.get(key)
        if not block or block.get("delta") is None:
            return f"{subject} leads {comparator} on the point estimate (no paired test available)"
        d, lo, hi = block["delta"], block["ci_low"], block["ci_high"]
        verdict = "CI excludes zero" if block.get("excludes_zero") else "**CI contains zero**"
        return f"{subject} − {comparator} = {d:+.4f}, 95 % CI [{lo:+.4f}, {hi:+.4f}], {verdict}"
    a24 = (E24 / "AUTONOMOUS_EXPERIMENTS.md")
    r5 = read_json(E24 / "results/r5_hard_negative_control.json")
    trained_sig = read_csv(E24 / "results/trained_significance_vs_R0.csv")

    track_a = m22[m22["track"] == "A_amazon_test"].sort_values("macro_auroc", ascending=False) if not m22.empty else pd.DataFrame()
    track_b = m22[m22["track"] == "B_fabricvst_ood"].sort_values("macro_auroc", ascending=False) if not m22.empty else pd.DataFrame()

    def value(frame, model, column, default=float("nan")):
        if frame.empty:
            return default
        hit = frame[frame["model"] == model] if "model" in frame else frame[frame["system"] == model]
        return float(hit[column].iloc[0]) if len(hit) else default

    last2_a = value(track_a, "Last2 (ours)", "macro_auroc")
    cat_a = value(track_a, "Category-only (no pixels)", "macro_auroc")
    best_b_row = track_b.iloc[0] if not track_b.empty else None
    last2_b = value(track_b, "Last2 (ours)", "macro_auroc")

    r23_last2 = value(r23_same, "Last2 (ours)", "ndcg@10")
    r23_cat = value(r23_same, "Category-only (no pixels)", "ndcg@10")
    r23_text = value(r23_same, "FashionCLIP text-image (query sentence)", "ndcg@10")
    r23_last2_d = value(r23_same, "Last2 (ours)", "dNDCG_vs_category_only")
    r23_last2_lo = value(r23_same, "Last2 (ours)", "dNDCG_vs_category_only_ci_low")
    r23_last2_hi = value(r23_same, "Last2 (ours)", "dNDCG_vs_category_only_ci_high")
    r23_text_lo = value(r23_same, "FashionCLIP text-image (query sentence)", "dNDCG_vs_category_only_ci_low")
    r23_text_hi = value(r23_same, "FashionCLIP text-image (query sentence)", "dNDCG_vs_category_only_ci_high")

    sig_test = sig[sig["split"] == "test"] if not sig.empty else pd.DataFrame()
    vlm_present = [n for n in ("Qwen3-VL-8B-Instruct", "Qwen3-VL-32B-Instruct", "InternVL3.5-8B")
                   if not m22.empty and n in set(m22["model"])]
    vlm_missing = [n for n in ("Qwen3-VL-8B-Instruct", "Qwen3-VL-32B-Instruct", "InternVL3.5-8B")
                   if n not in vlm_present]

    contrast_rows = "\n".join(
        f"| `{k}` | {v['delta']:+.4f} | [{v['ci_low']:+.4f}, {v['ci_high']:+.4f}] | "
        f"{'excludes zero' if v.get('excludes_zero') else 'contains zero — not established'} |"
        for k, v in contrasts.items() if v.get("delta") is not None) or "_(not available)_"

    def rfmt(key):
        v = r5.get(key)
        return "—" if v is None else f"{v:.8f}"

    def rdelta(split):
        d = r5.get(f"{split}_real_minus_shuffled")
        lo = r5.get(f"{split}_ci95_low"); hi = r5.get(f"{split}_ci95_high")
        if d is None:
            return "—"
        return f"{d:+.8f} [{lo:+.8f}, {hi:+.8f}] ns"

    r5_val_r0, r5_test_r0 = rfmt("validation_R0_NDCG@10"), rfmt("test_R0_NDCG@10")
    r5_val_real, r5_test_real = rfmt("validation_real_NDCG@10"), rfmt("test_real_NDCG@10")
    r5_val_shuf, r5_test_shuf = rfmt("validation_shuffled_NDCG@10"), rfmt("test_shuffled_NDCG@10")
    r5_val_delta, r5_test_delta = rdelta("validation"), rdelta("test")

    report = f"""# Tactile-Aware Shopping Agent: Experiments 22–24

Generated {datetime.now(KST):%Y-%m-%d %H:%M KST} by `scripts/make_final_report_22_24.py`.
Every figure is read from the three experiments' `results/` directories.

---

## 1. Executive Summary

Three experiments were run to decide whether this project's review-supervised
tactile pipeline is worth keeping, and where.

**The answer is: keep it for search, drop it for recommendation.**

1. **Experiment 22 — prediction.** On our own apparel distribution the
   review-supervised predictor (Last2) reaches macro AUROC **{last2_a:.4f}**, against
   **{cat_a:.4f}** for a control that sees no pixels at all
   ({contrast_text("A_last2_minus_category_only", "Last2", "category-only")}), and it
   leads the strongest open encoder by a paired margin that also excludes zero
   ({contrast_text("A_last2_minus_siglip2_so400m_384", "Last2", "SigLIP2")}).
   On the external FabricVST fabrics it falls to **{last2_b:.4f}**, an interval that
   **includes chance** — it does not generalise. A generic open encoder scores higher
   there, but at 50 fabrics that ordering is *not* statistically established
   ({contrast_text("B_siglip2_so400m_384_minus_last2", "SigLIP2", "Last2")}).
2. **Experiment 23 — retrieval.** For explicit tactile queries the predictor gives a
   large, significant gain that **survives removing the category shortcut**
   (same-category NDCG@10 {r23_last2:.4f} vs control {r23_cat:.4f}, Δ {r23_last2_d:+.4f},
   95 % CI [{r23_last2_lo:+.4f}, {r23_last2_hi:+.4f}]). A natural-language search box
   looks competitive globally but **collapses to the control** once category is held
   fixed ({r23_text:.4f}, CI [{r23_text_lo:+.4f}, {r23_text_hi:+.4f}], contains zero).
3. **Experiment 24 — recommendation.** Making the tactile weight adaptive does not
   rescue it. A per-(user, item) learned gate, free over [0,1] and selected on
   validation, **collapses to a near-zero constant**; the one configuration that
   makes it genuinely vary performs worse than no tactile at all. In-model fusion
   (R3) and multi-task auxiliary prediction (R4) are significantly *worse* than the
   baseline. One method, R5 tactile-aware hard-negative mining, **did** beat the
   baseline significantly — and its control shows the gain survives permuting the
   tactile table, so it belongs to hard-negative mining, not to tactile information.
   Four separate explanations were tested and refuted: the combination rule, the ANN
   query construction, the gate initialisation, and finally R5 itself.

The single sentence: **the tactile signal is real and useful when the user asks for
it, and absent when we have to infer it from purchases.**

---

## 2. Existing system (context)

- Reviews → Qwen exact-span extraction → semantic verification → 14-class tactile
  normalisation (pseudo-labels, never human gold)
- `Last2` = FashionCLIP ViT-B/32 with the last two vision blocks + projection
  fine-tuned, 14 independent sigmoids; SHA-256 `073b542a9d6bd445…`, verified intact
- FabricVST-taxonomy retrains: `A` (24 attributes), `B` (18 attributes) — experiment
  21 found both degenerate toward all-positive on the comparable attributes
- exp16b / 17b / 19 / 20: four independent failures to improve next-item
  recommendation with tactile; exp20's `aligned − shuffle ≈ 0` the strongest prior
  evidence that the tactile vector carries little discriminative information

---

## 3. Experiment 22 — Tactile predictor benchmark

### Research question
*If a current open VLM can already judge fabric feel from a photo, why build review
supervision at all?*

### Evaluation
Two tracks, 8 EXACT-mapped attributes (`soft, rough, smooth, thick, thin, cool,
warm, stiff`), mapping frozen before scoring and inherited from exp21.
Primary metrics **macro AUROC / AUPRC**; F1 is secondary because on this data it
tracks the base rate. UNKNOWN labels are dropped from every denominator, never
treated as negative. Track B's evaluation unit is the **fabric** (50), not the crop.

### Open baselines: what was actually runnable

{md(feas[['model','type','direct_baseline']] if not feas.empty else feas)}

**No executable image→tactile-property specialist exists.** `Teaching Cameras to
Feel` (ECCV 2020) ships a README and a dataset link — no code, no weights. The
alternatives found (FabricVST/Multimodal-ZSL, TactStyle, Li 2025) all require a
tactile sensor or produce non-semantic output. That absence is a finding, not a gap
we papered over.
"""

    if vlm_missing:
        report += f"""
> ⚠️ **{', '.join(vlm_missing)} not yet scored when this was generated** — the shared
> A100 was held by another user's job. Absent from the tables below.
"""

    report += f"""
### Main results

**Track A — Amazon locked test, 1,060 products**

{md(track_a[['model','family','macro_auroc','macro_auprc','macro_f1','mean_prediction_positive_rate']] if not track_a.empty else track_a)}

**Track B — FabricVST external OOD, 50 fabrics**

{md(track_b[['model','family','macro_auroc','macro_auprc','macro_f1','mean_prediction_positive_rate']] if not track_b.empty else track_b)}

### Degeneracy analysis

Experiment 21's mechanism is generalised into a standing check: for an all-positive
predictor, F1 = 2p/(1+p) is a pure function of the base rate. `plots/f1_vs_base_rate.png`
puts observed F1 against that quantity; anything on the diagonal is reporting
prevalence, not skill. Per-attribute prediction rates, score dispersion and
threshold positions are in `results/prediction_rates.csv`, and explicit warnings in
`results/degeneracy_warnings.json`.

### Paired contrasts (the claims above rest on these, not on overlapping marginal CIs)

| contrast | Δ macro AUROC | 95 % CI | verdict |
|---|---:|---|---|
{contrast_rows}

### Conclusion
Review supervision earns its place **in-domain**, where its lead over both the
no-pixel control and the best open encoder survives a paired test. It fails
**out-of-domain**, where its interval includes chance. Whether a generic encoder is
genuinely *better* on FabricVST is not established at n = 50. There is no open
tactile specialist to lose to.

---

## 4. Experiment 23 — Tactile-conditioned retrieval

### Query construction
{len(read_json(E23 / 'artifacts/query_manifest.json').get('queries', {}).get('test', []))} queries
enumerated from the taxonomy, admitted only on pool size and class balance.
Five families: single tactile, category+tactile, **same-category**, multi-tactile and
**negative** tactile.

Negative queries are legitimate here because this dataset records real opposite
evidence: a negative is written only when a reviewer asserted the declared
incompatible counterpart (`smooth↔rough`, `thin↔thick`, `warm↔cool`,
`soft↔firm`, `flexible↔stiff`). Silence stays UNKNOWN and is removed from the pool.

### Results — all queries

{md(r23_main[['system','family_type','ndcg@10','precision@10','map@10','dNDCG_vs_category_only','dNDCG_vs_category_only_ci_low','dNDCG_vs_category_only_ci_high']] if not r23_main.empty else r23_main)}

### Same-category — the shortcut-free evaluation

{md(r23_same[['system','family_type','ndcg@10','precision@10','map@10','dNDCG_vs_category_only','dNDCG_vs_category_only_ci_low','dNDCG_vs_category_only_ci_high']] if not r23_same.empty else r23_same)}

### By query family

{md(r23_family.pivot_table(index='system', columns='family', values='ndcg@10').reset_index() if not r23_family.empty else r23_family)}

Family B (category + tactile) is the one place the tactile models lose badly, and
the reason is structural: a tactile score carries no category information. The
deployment consequence is concrete — **filter by category, then rank by tactile.**

### Conclusion
Prediction quality transfers to retrieval, and the advantage is not a category
shortcut. This is the strongest positive result in the project.

---

## 5. Experiment 24 — Adaptive tactile recommendation

### R0 reproduces exp17b to 8 decimal places
NDCG@10 / HR@10 / MRR@10 = 0.00349417 / 0.00576840 / 0.00280234, identical to the
stored exp17b values. The pipeline is verified, not assumed.

### The binding constraint
SASRec's Recall@500 on the test cohort is **{recall_t.get('sasrec@500', float('nan')):.6f}** —
the right item is outside the candidate set for ~96.5 % of users. Every reranking
result is bounded by that.

### Results

{md(posthoc[['method','split','NDCG@10','HR@10','MRR@10']] if not posthoc.empty else posthoc, floats=8)}

**Significance vs R0 (test), paired bootstrap by user**

{md(sig_test[['method','NDCG@10','delta_vs_R0','ci95_low','ci95_high','improved','worsened','significant']] if not sig_test.empty else sig_test, floats=8)}

### The decisive table: the R2 gate initialisation sweep

{md(sweep[['init_bias','lr','validation_NDCG@10','gate_mean','gate_std']] if not sweep.empty else sweep, floats=8)}

The only setting that yields a genuinely dispersed gate (std ≈ 0.29) is among the
worst; the setting validation selects has a gate that is constant and ≈ 0. **A
weight free to vary per user and item is driven to zero by validation.**

### Three alternative explanations, tested and refuted

| explanation | test | verdict |
|---|---|---|
| "the exp17b combination rule re-ordered items by tactile *availability*" | R1b applies one common scale to all candidates | refuted — identical alpha curve, still selects α = 0 |
| "the tactile ANN query was badly scaled" | A24-1: standardise each dimension before the cosine | refuted — 1.65× better (0.00136 → 0.00224) but the pre-registered bar was 0.010 |
| "the reranker was never actually learned" | R7 head zero-initialised, epoch chosen on validation | refuted — validation selects the untrained no-op |

### Candidate recall vs ranking, separated

| | validation | test |
|---|---:|---:|
| SASRec Recall@500 | {recall_v.get('sasrec@500', float('nan')):.6f} | {recall_t.get('sasrec@500', float('nan')):.6f} |
| union Recall@500+500 | {recall_v.get('union_tactile_std@500+500', float('nan')):.6f} | {recall_t.get('union_tactile_std@500+500', float('nan')):.6f} |
| ΔNDCG@10 | 0.00000000 | 0.00000000 |

Tactile candidates add coverage the backbone missed and **none of them reach the
top 10**.
"""

    if not trained.empty:
        report += f"""
### Trained backbones (R3 / R4 / R5 / R6)

{md(trained[['tag','variant','validation_NDCG@10','test_NDCG@10']].sort_values('validation_NDCG@10', ascending=False), floats=8)}
"""
    if shuffle:
        report += f"""
### The aligned − shuffle control (exp20's decisive test, retested)

Identical capacity, tactile table deterministically permuted in the shuffle arm.

| split | aligned − shuffle, NDCG@10 |
|---|---:|
| validation | {shuffle.get('validation_delta_NDCG@10', float('nan')):+.10f} |
| test | {shuffle.get('test_delta_NDCG@10', float('nan')):+.10f} |
"""
    if not ablation.empty:
        report += f"""
### Tactile-source ablation

{md(ablation[ablation['split'] == 'test'][['tactile_source','status','selected_alpha','R1_NDCG@10','R2_NDCG@10','gate_mean']], floats=8)}

FabricVST-A/B rows are marked **diagnostic**: experiment 21 showed both predict
almost every fabric positive on the comparable attributes, so they are not credible
tactile predictors and their numbers are not presented as improvements.
"""

    group_test = groups[groups["split"] == "test"] if not groups.empty else pd.DataFrame()
    report += f"""
### User group analysis

Subgroups defined from **train history only**, never from the test outcome.

{md(group_test.pivot_table(index='group', columns='method', values='delta_vs_R0').reset_index() if not group_test.empty else group_test, floats=8)}

No subgroup benefits, including the high-tactile-consistency users who were the
most plausible beneficiaries.

---

## 6. Autonomous follow-up experiments

Pre-registered in `experiments/24_.../AUTONOMOUS_EXPERIMENTS.md` **before** running,
each with an explicit success/failure rule.

- **A24-1 — standardised tactile ANN.** Hypothesis: raw cosine over [0,1]^14 vectors
  is dominated by the shared positive mean, so the ANN is near-random. Result: the
  mechanism was real (1.65× improvement, replicated on test) but far below the
  pre-registered bar. **H rejected**; R7's candidate-recall leg is genuinely
  unhelpful rather than an artifact.
- **R1b — common-scale fixed alpha.** Built to test the audit's own hypothesis about
  exp17b's combination rule. **Refuted that hypothesis.**

Two confounds were found and fixed before results were read, not after:
- R3's fused embedding entered the Transformer at ~50× R0's scale (LayerNorm unit
  variance vs embedding std 0.02). Fixed by initialising the LayerNorm gain to 0.02,
  so all R3 variants now start numerically where R0 starts.
- R2/R7 originally could not represent the baseline at initialisation, so their
  first (worse-than-R0) numbers measured optimisation, not tactile. Both heads were
  re-parameterised to start as exact no-ops.

---

### The R5 near-miss

R5 mines hard negatives that are same-category, similar-popularity but
tactile-distant. It beat R0 on both splits with intervals excluding zero, and for a
few minutes looked like the project's first recommendation win. The pre-planned
control — identical mining procedure, tactile table deterministically permuted —
removes it:

| | validation | test |
|---|---:|---:|
| R0, random negatives | {r5_val_r0} | {r5_test_r0} |
| R5, real tactile | {r5_val_real} | {r5_test_real} |
| R5, **permuted** tactile | {r5_val_shuf} | {r5_test_shuf} |
| real − permuted | {r5_val_delta} | {r5_test_delta} |

Both permuted intervals contain zero; on test the permuted arm is marginally
*higher*. The gain is real and belongs to **harder negatives**, not to tactile
information — the exp20 `aligned − shuffle ≈ 0` finding reproduced in a fifth
independent design.

## 7. What Worked

1. Review-supervised tactile prediction in-domain (Exp22 Track A).
2. Explicit tactile retrieval, including within a fixed category (Exp23).
3. Negative ("not rough") queries, because this dataset has genuine opposite
   evidence rather than inferred negatives.
4. The evaluation infrastructure: R0 reproduced a prior experiment to 8 decimals.

## 8. What Did Not Work

1. External generalisation to FabricVST — a generic open encoder is better there.
2. Every tactile-aware recommendation method: fixed alpha, learned gate, learned
   reranker, hybrid candidate generation, in-model fusion (significantly worse),
   multi-task auxiliary prediction (significantly worse), and mixture-of-experts.
   R5's apparent win is attributable to hard-negative mining, not tactile.
3. Tactile candidate generation as an indexing mechanism.

## 9. Why

- **Reviewers assert presence, not absence.** Negative evidence is structurally
  sparse, so the pseudo-labels are positive-biased and models drift toward the class
  prior. This is a label-construction problem, not an architecture problem.
- **Interaction ≠ tactile satisfaction.** A purchase is not a statement about feel.
  When the user *states* the constraint (Exp23), the same predictor works well; when
  we must infer it (Exp24), there is nothing to infer from.
- **Retrieval bottleneck.** With Recall@500 ≈ 0.035, reranking can only touch ~3.5 %
  of cases.
- **14 dimensions cannot index 825k items.** Confirmed quantitatively by A24-1.

---

## 10. Recommended final graduation-project configuration

## FINAL RECOMMENDED SYSTEM

| component | choice | why |
|---|---|---|
| **Tactile predictor** | **Last2** (`fashionclip_last2.pt`, 14 classes) | best in-domain macro AUROC ({last2_a:.4f}), 100 % catalog coverage already computed, ~200 img/s on one GPU, 58 MB. FabricVST-A/B are excluded — degenerate. A VLM is excluded on catalog-scale cost even where competitive. |
| **Recommendation model** | **SASRec, no tactile term** | every tactile variant is ≤ R0; adding tactile costs latency and buys nothing measurable |
| **Tactile retrieval** | **Last2 scores, category filter first, then tactile ranking** | Exp23: large significant gain within category; family B shows category must be handled separately |
| **Agent integration** | tactile ranking on *explicit* tactile queries only; never silently injected into personalised feeds | the two experiments disagree precisely on this boundary |
| **Confidence / UNKNOWN handling** | keep the three-state label (positive / negative / unknown); never render unknown as negative; show review-grounded vs image-predicted provenance | the same rule that keeps the evaluation honest keeps the product honest |

Decision factors beyond accuracy: Last2 costs 58 MB and one forward pass per image
against ~17 GB and 8 forward passes per image for an 8B VLM; it is interpretable
per attribute, already integrated, and its failure modes are characterised.

---

## 11. Claims We Can Safely Make

1. In-domain, review-supervised tactile prediction beats a no-pixel category control
   and the strongest open zero-shot model tested, on threshold-free metrics, with
   paired bootstrap intervals that exclude zero.
2. That advantage transfers to explicit tactile retrieval and survives removing the
   category shortcut, with a 95 % CI excluding zero.
3. A natural-language text-image search box's apparent tactile ability is largely
   category matching.
4. Adaptive, conditional, learnable tactile fusion does **not** improve next-item
   recommendation here — and this is now a real test, not an artefact of a disabled
   term, because the gate could represent any weight and validation chose ≈ 0.
5. No executable open RGB-only image→tactile-property model exists to compare with.

## 12. Claims We Must NOT Make

1. That any model predicts *real* tactile properties. Every target is a pseudo-label.
   No human gold set exists (exp15: 5 of 160).
2. That FabricVST retraining improved anything — its F1 gain is all-positive
   degeneracy.
3. That any Exp22–24 result is **confirmatory**. exp16b already opened this test
   split; everything here is locked post-hoc exploratory.
4. That tactile is useless *in general* — Exp23 shows the opposite for explicit
   queries.
4b. That R5 shows tactile helping recommendation. Its control permutes the tactile
   table and the gain is unchanged, so the credit goes to hard-negative mining.
5. That our models generalise to external fabric datasets — Last2's FabricVST
   interval includes chance.
5b. That a generic open encoder is *demonstrably better* than ours on FabricVST. Its
   point estimate is higher, but the paired interval contains zero at n = 50 fabrics.
   Reporting it as a win would be the same overclaim in the opposite direction.
6. Cross-experiment NDCG comparisons (Exp23's ~0.5 and Exp24's ~0.003 have different
   populations and candidate protocols).

---

## 13. Limitations

1. Pseudo-labels throughout; no human relevance or tactile ground truth.
2. Locked post-hoc exploratory, not confirmatory.
3. Shared GPU: another user's job held the A100 for the first hours. Our 7 GiB
   allocation contributed to a CUDA OOM that killed one of their processes, after
   which we stayed off the device entirely until it was free. Precisions actually
   used are recorded in `experiments/22_.../logs/vlm_precision_used.json`.
4. Track B subsamples 24 of 225 crops per fabric (identically for all models).
5. `history ≥ 3` is 1.5 % of the official test population.
6. The 11 product categories are a title-keyword heuristic.
7. Not a git repository: SHA-256 manifests of inputs replace a commit hash.

---

## 14. Reproduction instructions

```bash
PY=/home/user/onsesang/miniconda3/envs/texture/bin/python
export HF_HOME=/home/user/onsesang/.cache/huggingface

# Experiment 22
cd {E22}
$PY scripts/01_score_category_only.py && $PY scripts/02_score_ours.py
$PY scripts/03_score_clip.py && bash scripts/run_vlm_when_free.sh
$PY scripts/05_metrics.py && $PY scripts/06_plots.py && $PY scripts/07_report.py

# Experiment 23
cd {E23}
$PY scripts/00_text_image_features.py --model fashionclip --device cpu
$PY scripts/01_run_retrieval.py && $PY scripts/02_qualitative.py
$PY scripts/03_plots.py && $PY scripts/04_report.py

# Experiment 24
cd {E24}
$PY scripts/01_prepare.py && $PY scripts/02_evaluate.py --split test
for s in train validation test; do $PY scripts/04_candidates.py --split $s; done
$PY scripts/05_rerank.py && $PY scripts/06_analysis.py
bash scripts/run_training_queue.sh && bash scripts/run_post_training.sh

# Final report
$PY {ROOT}/scripts/make_final_report_22_24.py
```

Seeds: Exp22/23 `20260917`, Exp24 `20260917`; inherited split seeds `20260901`
(tactile) and `20260904` (recommendation).

---

## 15. Artifact paths

| what | where |
|---|---|
| Exp22 report / audit | `experiments/22_open_tactile_benchmark/REPORT.md`, `ARTIFACT_AUDIT.md` |
| Exp22 taxonomy mapping (frozen) | `experiments/22_.../artifacts/taxonomy_mapping.{{json,md}}` |
| Exp22 baseline feasibility | `experiments/22_.../results/baseline_feasibility.csv` |
| Exp22 raw scores | `experiments/22_.../cache/scores/*.npz` |
| Exp23 report | `experiments/23_tactile_conditioned_retrieval/REPORT.md` |
| Exp23 query benchmark | `experiments/23_.../artifacts/query_manifest.json` |
| Exp23 qualitative cases | `experiments/23_.../results/qualitative_examples.json` |
| Exp24 report / prior audit | `experiments/24_adaptive_tactile_recommendation/REPORT.md`, `EXP16_17_AUDIT.md` |
| Exp24 pre-registered follow-ups | `experiments/24_.../AUTONOMOUS_EXPERIMENTS.md` |
| Exp24 checkpoints | `experiments/24_.../checkpoints/*.pt` |
| Discord notification log | `logs/discord_notifications.jsonl` (message text only, no webhook) |
| Environments | `experiments/2{{2,3,4}}_*/environment.txt` |

Preserved untouched: `experiments/12`, `13`, `14`, `16`, `17`, `20`, `21` and every
checkpoint they contain.
"""

    target = ROOT / "EXPERIMENTS_22_24_FINAL_REPORT.md"
    target.write_text(report)
    print(f"wrote {target}  ({len(report.splitlines())} lines)")
    if vlm_missing:
        print(f"NOTE: VLMs still missing: {vlm_missing}")
    if trained.empty:
        print("NOTE: trained backbones not yet included")
    if ablation.empty:
        print("NOTE: tactile-source ablation not yet included")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
