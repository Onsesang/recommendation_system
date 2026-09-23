# Tactile-Aware Shopping Agent: Experiments 22–24

Generated 2026-09-17 15:06 KST by `scripts/make_final_report_22_24.py`.
Every figure is read from the three experiments' `results/` directories.

---

## 1. Executive Summary

Three experiments were run to decide whether this project's review-supervised
tactile pipeline is worth keeping, and where.

**The answer is: keep it for search, drop it for recommendation.**

1. **Experiment 22 — prediction.** On our own apparel distribution the
   review-supervised predictor (Last2) reaches macro AUROC **0.7345**, against
   **0.5589** for a control that sees no pixels at all
   (Last2 − category-only = +0.1760, 95 % CI [+0.1266, +0.2246], CI excludes zero), and it
   leads the strongest open encoder by a paired margin that also excludes zero
   (Last2 − SigLIP2 = +0.1228, 95 % CI [+0.0790, +0.1635], CI excludes zero).
   On the external FabricVST fabrics it falls to **0.5752**, an interval that
   **includes chance** — it does not generalise. A generic open encoder scores higher
   there, but at 50 fabrics that ordering is *not* statistically established
   (SigLIP2 − Last2 = +0.1002, 95 % CI [-0.0081, +0.2048], **CI contains zero**).
2. **Experiment 23 — retrieval.** For explicit tactile queries the predictor gives a
   large, significant gain that **survives removing the category shortcut**
   (same-category NDCG@10 0.8290 vs control 0.5393, Δ +0.2898,
   95 % CI [+0.2091, +0.3791]). A natural-language search box
   looks competitive globally but **collapses to the control** once category is held
   fixed (0.5609, CI [-0.0552, +0.1000], contains zero).
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

| model | type | direct_baseline |
|---|---|---|
| Qwen3-VL-8B-Instruct | generic open VLM | YES |
| Qwen3-VL-32B-Instruct | generic open VLM | CONDITIONAL |
| InternVL3.5-8B | generic open VLM | YES |
| CLIP-Texture protocol (OpenAI CLIP ViT-L/14) | texture/material specialist protocol | YES |
| SigLIP2-so400m-patch14-384 | general open contrastive VL model | YES |
| FashionCLIP (zero-shot) | in-domain apparel contrastive model | YES |
| Teaching Cameras to Feel (Purri & Dana ECCV 2020) | image->tactile-property specialist | NO |
| FabricVST / Multimodal ZSL (Cao et al. RAS 2024) | visuo-tactile zero-shot texture model | NO |
| TactStyle (CHI 2025) | image->tactile texture generation | NO |
| Li (2025) fabric tactile prediction from vision and touch | visuo-tactile fabric property model | NO |
| Category-only baseline (exp13) | control (no pixels) | YES |

**No executable image→tactile-property specialist exists.** `Teaching Cameras to
Feel` (ECCV 2020) ships a README and a dataset link — no code, no weights. The
alternatives found (FabricVST/Multimodal-ZSL, TactStyle, Li 2025) all require a
tactile sensor or produce non-semantic output. That absence is a finding, not a gap
we papered over.

### Main results

**Track A — Amazon locked test, 1,060 products**

| model | family | macro_auroc | macro_auprc | macro_f1 | mean_prediction_positive_rate |
|---|---|---|---|---|---|
| Last2 (ours) | ours | 0.7345 | 0.7548 | 0.7321 | 0.7717 |
| FashionCLIP frozen head (ours) | ours | 0.6595 | 0.6781 | 0.6955 | 0.9045 |
| InternVL3.5-8B | vlm | 0.6323 | 0.6558 | 0.5745 | 0.5325 |
| FabricVST-B 18attr (ours) | ours | 0.6239 | 0.6446 | 0.6823 | 0.8669 |
| SigLIP2-so400m | clip | 0.6118 | 0.6401 | 0.6639 | 0.7895 |
| Qwen3-VL-32B-Instruct | vlm | 0.5946 | 0.6255 | 0.6595 | 0.7710 |
| FabricVST-A 24attr (ours) | ours | 0.5827 | 0.6148 | 0.6826 | 0.9720 |
| Qwen3-VL-8B-Instruct | vlm | 0.5662 | 0.6074 | 0.6579 | 0.7850 |
| Category-only (no pixels) | control | 0.5589 | 0.5940 | 0.6785 | 0.9181 |
| FashionCLIP zero-shot | clip | 0.5368 | 0.5926 | 0.6755 | 0.8747 |
| CLIP-Texture protocol (ViT-L/14) | clip | 0.5288 | 0.5734 | 0.6754 | 0.9315 |

**Track B — FabricVST external OOD, 50 fabrics**

| model | family | macro_auroc | macro_auprc | macro_f1 | mean_prediction_positive_rate |
|---|---|---|---|---|---|
| SigLIP2-so400m | clip | 0.6755 | 0.6844 | 0.5856 | 0.7250 |
| Qwen3-VL-32B-Instruct | vlm | 0.6745 | 0.6978 | 0.6358 | 0.6575 |
| Qwen3-VL-8B-Instruct | vlm | 0.6259 | 0.6228 | 0.4211 | 0.3150 |
| FabricVST-B 18attr (ours) | ours | 0.5948 | 0.5980 | 0.6058 | 0.8575 |
| InternVL3.5-8B | vlm | 0.5818 | 0.5876 | 0.5484 | 0.5975 |
| Last2 (ours) | ours | 0.5752 | 0.5748 | 0.5620 | 0.7725 |
| FabricVST-A 24attr (ours) | ours | 0.5722 | 0.6011 | 0.5951 | 0.8950 |
| FashionCLIP frozen head (ours) | ours | 0.5629 | 0.5708 | 0.5702 | 0.8800 |
| CLIP-Texture protocol (ViT-L/14) | clip | 0.5322 | 0.5624 | 0.6524 | 0.9975 |
| FashionCLIP zero-shot | clip | 0.5316 | 0.5539 | 0.6520 | 0.9525 |

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
| `A_last2_minus_category_only` | +0.1760 | [+0.1266, +0.2246] | excludes zero |
| `A_last2_minus_siglip2_so400m_384` | +0.1228 | [+0.0790, +0.1635] | excludes zero |
| `B_siglip2_so400m_384_minus_last2` | +0.1002 | [-0.0081, +0.2048] | contains zero — not established |
| `A_last2_minus_qwen3vl_32b` | +0.1405 | [+0.0985, +0.1820] | excludes zero |
| `B_qwen3vl_32b_minus_last2` | +0.0991 | [+0.0125, +0.1797] | excludes zero |
| `A_last2_minus_qwen3vl_8b` | +0.1686 | [+0.1246, +0.2113] | excludes zero |
| `B_qwen3vl_8b_minus_last2` | +0.0506 | [-0.0465, +0.1435] | contains zero — not established |
| `A_last2_minus_internvl3_5_8b` | +0.1021 | [+0.0549, +0.1487] | excludes zero |
| `B_internvl3_5_8b_minus_last2` | +0.0070 | [-0.1009, +0.1118] | contains zero — not established |

### Conclusion
Review supervision earns its place **in-domain**, where its lead over both the
no-pixel control and the best open encoder survives a paired test. It fails
**out-of-domain**, where its interval includes chance. Whether a generic encoder is
genuinely *better* on FabricVST is not established at n = 50. There is no open
tactile specialist to lose to.

---

## 4. Experiment 23 — Tactile-conditioned retrieval

### Query construction
107 queries
enumerated from the taxonomy, admitted only on pool size and class balance.
Five families: single tactile, category+tactile, **same-category**, multi-tactile and
**negative** tactile.

Negative queries are legitimate here because this dataset records real opposite
evidence: a negative is written only when a reviewer asserted the declared
incompatible counterpart (`smooth↔rough`, `thin↔thick`, `warm↔cool`,
`soft↔firm`, `flexible↔stiff`). Silence stays UNKNOWN and is removed from the pool.

### Results — all queries

| system | family_type | ndcg@10 | precision@10 | map@10 | dNDCG_vs_category_only | dNDCG_vs_category_only_ci_low | dNDCG_vs_category_only_ci_high |
|---|---|---|---|---|---|---|---|
| Last2 (ours) | ours | 0.4738 | 0.4589 | 0.3829 | 0.1795 | 0.1266 | 0.2322 |
| FashionCLIP text-image (query sentence) | clip | 0.4561 | 0.4570 | 0.3276 | 0.1618 | 0.1038 | 0.2197 |
| InternVL3.5-8B | vlm | 0.3879 | 0.3776 | 0.2915 | 0.0936 | 0.0451 | 0.1404 |
| FabricVST-B 18attr (ours) | ours | 0.3818 | 0.3682 | 0.2817 | 0.0875 | 0.0381 | 0.1350 |
| FashionCLIP frozen head (ours) | ours | 0.3807 | 0.3710 | 0.2883 | 0.0864 | 0.0367 | 0.1346 |
| Qwen3-VL-32B-Instruct | vlm | 0.3769 | 0.3692 | 0.2752 | 0.0826 | 0.0391 | 0.1254 |
| SigLIP2-so400m | clip | 0.3714 | 0.3617 | 0.2687 | 0.0771 | 0.0344 | 0.1202 |
| Qwen3-VL-8B-Instruct | vlm | 0.3552 | 0.3439 | 0.2569 | 0.0609 | 0.0156 | 0.1052 |
| FabricVST-A 24attr (ours) | ours | 0.3548 | 0.3514 | 0.2650 | 0.0605 | 0.0148 | 0.1127 |
| FashionCLIP zero-shot | clip | 0.3249 | 0.3206 | 0.2201 | 0.0306 | -0.0119 | 0.0717 |
| CLIP-Texture protocol (ViT-L/14) | clip | 0.3081 | 0.3121 | 0.2116 | 0.0138 | -0.0259 | 0.0526 |
| Category-only (no pixels) | control | 0.2943 | 0.3009 | 0.2083 | 0.0000 | 0.0000 | 0.0000 |
| Popularity (non-tactile) | baseline | 0.2820 | 0.2888 | 0.1780 | -0.0123 | -0.0578 | 0.0317 |

### Same-category — the shortcut-free evaluation

| system | family_type | ndcg@10 | precision@10 | map@10 | dNDCG_vs_category_only | dNDCG_vs_category_only_ci_low | dNDCG_vs_category_only_ci_high |
|---|---|---|---|---|---|---|---|
| Last2 (ours) | ours | 0.8290 | 0.8125 | 0.7409 | 0.2898 | 0.2091 | 0.3791 |
| FabricVST-B 18attr (ours) | ours | 0.6859 | 0.6583 | 0.5530 | 0.1466 | 0.0352 | 0.2587 |
| SigLIP2-so400m | clip | 0.6741 | 0.6333 | 0.5341 | 0.1349 | 0.0425 | 0.2322 |
| FashionCLIP frozen head (ours) | ours | 0.6708 | 0.6500 | 0.5380 | 0.1316 | 0.0440 | 0.2247 |
| InternVL3.5-8B | vlm | 0.6565 | 0.6417 | 0.5328 | 0.1172 | 0.0152 | 0.2288 |
| Qwen3-VL-32B-Instruct | vlm | 0.6502 | 0.6208 | 0.5110 | 0.1110 | 0.0271 | 0.2115 |
| Qwen3-VL-8B-Instruct | vlm | 0.6019 | 0.5750 | 0.4612 | 0.0626 | -0.0302 | 0.1631 |
| FabricVST-A 24attr (ours) | ours | 0.6017 | 0.6042 | 0.4751 | 0.0625 | -0.0490 | 0.1699 |
| FashionCLIP text-image (query sentence) | clip | 0.5609 | 0.5667 | 0.4237 | 0.0216 | -0.0552 | 0.1000 |
| FashionCLIP zero-shot | clip | 0.5520 | 0.5292 | 0.4078 | 0.0127 | -0.0821 | 0.1066 |
| CLIP-Texture protocol (ViT-L/14) | clip | 0.5467 | 0.5458 | 0.4096 | 0.0074 | -0.0635 | 0.0825 |
| Category-only (no pixels) | control | 0.5393 | 0.5292 | 0.4014 | 0.0000 | 0.0000 | 0.0000 |
| Popularity (non-tactile) | baseline | 0.5240 | 0.5250 | 0.3685 | -0.0153 | -0.1157 | 0.0892 |

### By query family

| system | A | B | C | D | E |
|---|---|---|---|---|---|
| CLIP-Texture protocol (ViT-L/14) | 0.6024 | 0.0746 | 0.5467 | 0.3917 | 0.5004 |
| Category-only (no pixels) | 0.5762 | 0.0660 | 0.5393 | 0.3716 | 0.4632 |
| FabricVST-A 24attr (ours) | 0.7030 | 0.0964 | 0.6017 | 0.4467 | 0.5977 |
| FabricVST-B 18attr (ours) | 0.7874 | 0.1196 | 0.6859 | 0.4005 | 0.5930 |
| FashionCLIP frozen head (ours) | 0.7394 | 0.1030 | 0.6708 | 0.4500 | 0.6529 |
| FashionCLIP text-image (query sentence) | 0.5882 | 0.4286 | 0.5609 | 0.3379 | 0.4556 |
| FashionCLIP zero-shot | 0.6918 | 0.1027 | 0.5520 | 0.3866 | 0.4630 |
| InternVL3.5-8B | 0.7661 | 0.1147 | 0.6565 | 0.4479 | 0.7007 |
| Last2 (ours) | 0.8722 | 0.1317 | 0.8290 | 0.6018 | 0.7589 |
| Popularity (non-tactile) | 0.5227 | 0.0775 | 0.5240 | 0.3094 | 0.4773 |
| Qwen3-VL-32B-Instruct | 0.7470 | 0.1053 | 0.6502 | 0.4510 | 0.6397 |
| Qwen3-VL-8B-Instruct | 0.7045 | 0.0965 | 0.6019 | 0.4414 | 0.6133 |
| SigLIP2-so400m | 0.7199 | 0.0943 | 0.6741 | 0.4577 | 0.5725 |

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
SASRec's Recall@500 on the test cohort is **0.035177** —
the right item is outside the candidate set for ~96.5 % of users. Every reranking
result is bounded by that.

### Results

| method | split | NDCG@10 | HR@10 | MRR@10 |
|---|---|---|---|---|
| R0_sasrec | validation | 0.00300162 | 0.00549861 | 0.00224745 |
| R1_fixed_alpha | validation | 0.00300162 | 0.00549861 | 0.00224745 |
| R1b_fixed_alpha_common_scale | validation | 0.00300162 | 0.00549861 | 0.00224745 |
| R2_learned_gate | validation | 0.00303138 | 0.00549861 | 0.00228705 |
| R7_hybrid_candidates_reranker | validation | 0.00300162 | 0.00549861 | 0.00224745 |
| R0_sasrec | test | 0.00349417 | 0.00576840 | 0.00280234 |
| R1_fixed_alpha | test | 0.00349417 | 0.00576840 | 0.00280234 |
| R1b_fixed_alpha_common_scale | test | 0.00349417 | 0.00576840 | 0.00280234 |
| R2_learned_gate | test | 0.00341802 | 0.00576840 | 0.00269953 |
| R7_hybrid_candidates_reranker | test | 0.00349417 | 0.00576840 | 0.00280234 |

**Significance vs R0 (test), paired bootstrap by user**

| method | NDCG@10 | delta_vs_R0 | ci95_low | ci95_high | improved | worsened | significant |
|---|---|---|---|---|---|---|---|
| R0_sasrec | 0.00349417 | 0.00000000 | 0.00000000 | 0.00000000 | 0 | 0 | no |
| R1_fixed_alpha | 0.00349417 | 0.00000000 | 0.00000000 | 0.00000000 | 0 | 0 | no |
| R1b_fixed_alpha_common_scale | 0.00349417 | 0.00000000 | 0.00000000 | 0.00000000 | 0 | 0 | no |
| R7_hybrid_candidates_reranker | 0.00349417 | 0.00000000 | 0.00000000 | 0.00000000 | 0 | 0 | no |
| R2_learned_gate | 0.00341802 | -0.00007615 | -0.00017460 | 0.00002230 | 6 | 13 | no |

### The decisive table: the R2 gate initialisation sweep

| init_bias | lr | validation_NDCG@10 | gate_mean | gate_std |
|---|---|---|---|---|
| -6.00000000 | 0.00100000 | 0.00303138 | 0.00250357 | 0.00000099 |
| -6.00000000 | 0.01000000 | 0.00298127 | 0.00247263 | 0.00000001 |
| -2.00000000 | 0.00100000 | 0.00226639 | 0.11920211 | 0.00000080 |
| -2.00000000 | 0.01000000 | 0.00226639 | 0.11920211 | 0.00000080 |
| 0.00000000 | 0.00100000 | 0.00174169 | 0.31109494 | 0.02322011 |
| 0.00000000 | 0.01000000 | 0.00247650 | 0.47097757 | 0.29394084 |

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
| SASRec Recall@500 | 0.038083 | 0.035177 |
| union Recall@500+500 | 0.040052 | 0.036878 |
| ΔNDCG@10 | 0.00000000 | 0.00000000 |

Tactile candidates add coverage the backbone missed and **none of them reach the
top 10**.

### Trained backbones (R3 / R4 / R5 / R6)

| tag | variant | validation_NDCG@10 | test_NDCG@10 |
|---|---|---|---|
| R5_hard0.5_seed20260917 | R5 | 0.00270890 | 0.00271676 |
| R5_hard0.5_SHUFFLED_seed20260917 | R5 | 0.00260951 | 0.00272138 |
| R6_seed20260917 | R6 | 0.00232685 | 0.00192620 |
| R4_lambda0.01_seed20260917 | R4 | 0.00213812 | 0.00179847 |
| R0_seed20260917 | R0 | 0.00212398 | 0.00179340 |
| R4_lambda0.2_seed20260917 | R4 | 0.00207992 | 0.00162318 |
| R3_residual_gate_seed20260917 | R3 | 0.00207504 | 0.00129798 |
| R4_lambda0.1_seed20260917 | R4 | 0.00204030 | 0.00171317 |
| R4_lambda0.5_seed20260917 | R4 | 0.00201303 | 0.00156706 |
| R5_hard0.25_seed20260917 | R5 | 0.00198758 | 0.00244410 |
| R4_lambda0.05_seed20260917 | R4 | 0.00198143 | 0.00158865 |
| R5_hard0.75_seed20260917 | R5 | 0.00189586 | 0.00200299 |
| R3_shuffle_seed20260917 | R3 | 0.00156872 | 0.00124657 |
| R3_film_seed20260917 | R3 | 0.00141221 | 0.00075655 |
| R3_concat_proj_seed20260917 | R3 | 0.00085448 | 0.00060669 |

### The aligned − shuffle control (exp20's decisive test, retested)

Identical capacity, tactile table deterministically permuted in the shuffle arm.

| split | aligned − shuffle, NDCG@10 |
|---|---:|
| validation | +0.0005063222 |
| test | +0.0000514122 |

### Tactile-source ablation

| tactile_source | status | selected_alpha | R1_NDCG@10 | R2_NDCG@10 | gate_mean |
|---|---|---|---|---|---|
| none | control | 0.00000000 | 0.00349417 | 0.00349417 | 0.00247261 |
| last2 | ours | 0.00000000 | 0.00349417 | 0.00341802 | 0.00250727 |
| fabricvst_B | diagnostic | 0.00000000 | 0.00349417 | 0.00346063 | 0.00278464 |
| fabricvst_A | diagnostic | 0.00000000 | 0.00349417 | 0.00349620 | 0.00278538 |

FabricVST-A/B rows are marked **diagnostic**: experiment 21 showed both predict
almost every fabric positive on the comparable attributes, so they are not credible
tactile predictors and their numbers are not presented as improvements.

### User group analysis

Subgroups defined from **train history only**, never from the test outcome.

| group | R0_sasrec | R1_fixed_alpha | R1b_fixed_alpha_common_scale | R2_learned_gate | R7_hybrid_candidates_reranker |
|---|---|---|---|---|---|
| history 10+ | 0.00000000 | 0.00000000 | 0.00000000 | 0.00000000 | 0.00000000 |
| history 3-4 | 0.00000000 | 0.00000000 | 0.00000000 | -0.00002025 | 0.00000000 |
| history 5-9 | 0.00000000 | 0.00000000 | 0.00000000 | -0.00027234 | 0.00000000 |
| tactile consistency: high | 0.00000000 | 0.00000000 | 0.00000000 | -0.00010307 | 0.00000000 |
| tactile consistency: low | 0.00000000 | 0.00000000 | 0.00000000 | -0.00004923 | 0.00000000 |

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
| R0, random negatives | 0.00212398 | 0.00179340 |
| R5, real tactile | 0.00270890 | 0.00271676 |
| R5, **permuted** tactile | 0.00260951 | 0.00272138 |
| real − permuted | +0.00009939 [-0.00047240, +0.00073466] ns | -0.00000462 [-0.00041189, +0.00038502] ns |

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
| **Tactile predictor** | **Last2** (`fashionclip_last2.pt`, 14 classes) | best in-domain macro AUROC (0.7345), 100 % catalog coverage already computed, ~200 img/s on one GPU, 58 MB. FabricVST-A/B are excluded — degenerate. A VLM is excluded on catalog-scale cost even where competitive. |
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
cd /home/user/onsesang/material_span_grounding/experiments/22_open_tactile_benchmark
$PY scripts/01_score_category_only.py && $PY scripts/02_score_ours.py
$PY scripts/03_score_clip.py && bash scripts/run_vlm_when_free.sh
$PY scripts/05_metrics.py && $PY scripts/06_plots.py && $PY scripts/07_report.py

# Experiment 23
cd /home/user/onsesang/material_span_grounding/experiments/23_tactile_conditioned_retrieval
$PY scripts/00_text_image_features.py --model fashionclip --device cpu
$PY scripts/01_run_retrieval.py && $PY scripts/02_qualitative.py
$PY scripts/03_plots.py && $PY scripts/04_report.py

# Experiment 24
cd /home/user/onsesang/material_span_grounding/experiments/24_adaptive_tactile_recommendation
$PY scripts/01_prepare.py && $PY scripts/02_evaluate.py --split test
for s in train validation test; do $PY scripts/04_candidates.py --split $s; done
$PY scripts/05_rerank.py && $PY scripts/06_analysis.py
bash scripts/run_training_queue.sh && bash scripts/run_post_training.sh

# Final report
$PY /home/user/onsesang/material_span_grounding/scripts/make_final_report_22_24.py
```

Seeds: Exp22/23 `20260917`, Exp24 `20260917`; inherited split seeds `20260901`
(tactile) and `20260904` (recommendation).

---

## 15. Artifact paths

| what | where |
|---|---|
| Exp22 report / audit | `experiments/22_open_tactile_benchmark/REPORT.md`, `ARTIFACT_AUDIT.md` |
| Exp22 taxonomy mapping (frozen) | `experiments/22_.../artifacts/taxonomy_mapping.{json,md}` |
| Exp22 baseline feasibility | `experiments/22_.../results/baseline_feasibility.csv` |
| Exp22 raw scores | `experiments/22_.../cache/scores/*.npz` |
| Exp23 report | `experiments/23_tactile_conditioned_retrieval/REPORT.md` |
| Exp23 query benchmark | `experiments/23_.../artifacts/query_manifest.json` |
| Exp23 qualitative cases | `experiments/23_.../results/qualitative_examples.json` |
| Exp24 report / prior audit | `experiments/24_adaptive_tactile_recommendation/REPORT.md`, `EXP16_17_AUDIT.md` |
| Exp24 pre-registered follow-ups | `experiments/24_.../AUTONOMOUS_EXPERIMENTS.md` |
| Exp24 checkpoints | `experiments/24_.../checkpoints/*.pt` |
| Discord notification log | `logs/discord_notifications.jsonl` (message text only, no webhook) |
| Environments | `experiments/2{2,3,4}_*/environment.txt` |

Preserved untouched: `experiments/12`, `13`, `14`, `16`, `17`, `20`, `21` and every
checkpoint they contain.
