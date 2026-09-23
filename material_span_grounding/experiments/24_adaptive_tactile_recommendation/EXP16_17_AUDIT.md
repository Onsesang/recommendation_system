# Experiment 24 — Step 24.0: audit of experiments 16b and 17b

Read from the stored artifacts and source, 2026-09-17. Nothing in exp16/17 was
modified. Every number below was re-read from the files named, not copied from a
handoff document.

---

## 1. What the two experiments actually did

| | exp16b `16_strong_recommender_tactile` | exp17b `17_history3_recommender_refresh` |
|---|---|---|
| dataset | Amazon Reviews'23 `Amazon_Fashion`, rev `2aa726ef444e72c6a1364c4baa0bcdfb1de55db6`, official `0core/last_out` | same, reused read-only |
| catalog | 825,869 parent items, nothing filtered out | same |
| interactions | 2,474,375 | same |
| evaluation cohort | **all** official targets (validation 281,395 / test 2,035,490) | **history ≥ 3** (validation 14,731 / test 29,991) |
| training data | full | **unchanged** — only the evaluation cohort narrowed |
| backbones | Popularity, BPR, LightGCN, SASRec, eSASRec, SMORE-derived | + BERT4Rec, GRU4Rec |
| selected backbone | SASRec | SASRec, `lr=3e-4`, best epoch 5, ckpt SHA-256 `8420c256b08b0444…` |
| candidate K | grid {100,300,500,1000,3000} | same |
| tactile source | Last2 14-class probabilities over the full 825,840-item catalog | same |
| alpha grid | 0 … 1.00 step 0.05 | same |
| seed | 20260904 | 20260904 |
| bootstrap | paired by user, 1,000 replicates | same |

Source of record: `experiments/17_history3_recommender_refresh/PROTOCOL.md`,
`configs/experiment.json`, `artifacts/selected_backbone.json`,
`artifacts/selected_tactile.json`, `run_state.json` (all stages `complete`).

Model code reused: `experiments/16_strong_recommender_tactile/models.py`
(`SASRec`, dim 64, 2 layers, 2 heads, maxlen 50, dropout 0.2, item id shifted by
one with 0 = padding) and `experiments/17_.../models_history3.py`
(BERT4Rec, GRU4Rec).

---

## 2. R0 / R1 baselines this experiment inherits

**R0 — SASRec, no tactile.** history≥3 test (29,991 users):

| metric | value |
|---|---:|
| NDCG@10 | 0.00349417 |
| HR@10 | 0.00576840 |
| MRR@10 | 0.00280234 |

**R1 — fixed-alpha tactile reranking.** Validation selected **alpha = 0**, so R1
is numerically identical to R0 and the reported paired delta was exactly
0.00000000 with CI [0, 0] and improved/unchanged/worsened = 0 / 29,991 / 0
(`artifacts/bootstrap_tactile_history3.json`).

> This is **not** a null-effect test. The tactile term was switched off during
> validation, so the test comparison measured nothing. Exp24 must not repeat this
> framing.

---

## 3. Two findings from re-reading the code that change how Exp24 must be designed

### 3.1 The alpha search does not fail by scale mismatch — every positive alpha is strictly worse

`run_experiment.py::tactile_config` combines in **percentile space**:

```python
final = torch.where(valid, bp + a * (tp - bp), bp)
```

`bp` = percentile rank of the SASRec score among candidates, `tp` = percentile
rank of cosine similarity between the user's category-local tactile profile and
the candidate's Last2 vector. Both live in [0, 1], so the familiar
"raw scores have different magnitudes" explanation does **not** apply here.

The 84-row grid in `artifacts/alpha_search_history3.csv` is unambiguous:

| | validation NDCG@10 |
|---|---:|
| best over all `alpha = 0` rows | **0.0030016** |
| best over all `alpha > 0` rows | **0.0022846** |

Every one of the 80 positive-alpha configurations is worse than alpha = 0, and
the loss is monotone-ish in alpha. The fixed-alpha approach did not merely fail
to help; it actively destroyed ranking quality.

### 3.2 The reranker mixes two different score spaces across candidates

In the same line, a candidate that is `valid` (has a tactile vector **and** the
user has support in that candidate's category) is mapped to
`(1-a)·bp + a·tp`, while a candidate that is not valid keeps `bp` unchanged.

Interpolating one subset toward a second percentile distribution while leaving
the rest alone shrinks the valid candidates toward the middle of the ranking
relative to the invalid ones. So a positive alpha applies a **systematic
re-ordering driven by tactile *availability*, not by tactile *fit*** — an item is
moved because it has a tactile vector at all. With `tp` close to uninformative,
that is pure noise injection, which is consistent with the monotone degradation
above.

**Consequence for Exp24:** any method compared here must apply its tactile term
to *every* candidate on a single, common score scale, or gate it explicitly with
a learned weight that can go to zero per item. This is exactly what R2 (learned
gate) and R7 (learned reranker) do, and it is a concrete reason to expect them to
behave differently from R1 rather than a vague hope.

---

## 4. The retrieval bottleneck is the dominant constraint

`experiments/16_strong_recommender_tactile/artifacts/candidate_recall.csv`,
validation split, full catalog:

| K | popularity | BPR | LightGCN | SASRec | eSASRec | SMORE |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 0.0270 | 0.0232 | 0.0249 | 0.0266 | 0.0264 | 0.0220 |
| 300 | 0.0448 | 0.0381 | 0.0407 | 0.0433 | 0.0429 | 0.0365 |
| 1000 | 0.0728 | 0.0615 | 0.0652 | 0.0693 | 0.0706 | 0.0592 |
| 3000 | 0.1172 | 0.0981 | 0.1029 | **0.1092** | 0.1124 | 0.0954 |

On the history≥3 validation cohort SASRec's Recall@3000 is only **0.0732**
(`selected_backbone.json`), against the experiment's own pre-registered
requirement of ≥ 0.80. `candidate_rule_satisfied: false` is recorded in that file.
Exp20 later pushed K to 30,000 and still reached only Recall@30000 ≈ 0.236.

**So in ~93 % of history≥3 cases the correct item was never in the candidate set
at all.** No reranker — fixed, gated, or learned — can recover those. This is the
single strongest argument for R7 (hybrid candidate generation), and it means
reranking-only methods (R1, R2) should be read as an upper bound of roughly
7 % of the population.

Note also that **popularity has the best candidate recall of any backbone**
(0.1172 vs SASRec 0.1092), while SASRec has the best NDCG. Candidate generation
and ranking are being optimised for different things.

---

## 5. What Exp24 reuses, and what it must not

Reused read-only (absolute paths, never copied or edited):

| purpose | path |
|---|---|
| events / users / catalog / targets | `experiments/16_strong_recommender_tactile/data/*.parquet` |
| full-catalog Last2 tactile vectors (825,840 × 14) | `…/artifacts/product_tactile_profiles.parquet` |
| SASRec checkpoint of record | `…/artifacts/checkpoints/sasrec_lr0.0003.pt` |
| history≥3 cohorts | `experiments/17_…/caches/{validation,test}_cohort_history3.parquet` |
| SASRec / BERT4Rec / GRU4Rec definitions | `…/16_…/models.py`, `…/17_…/models_history3.py` |

Prohibited, carried over from the exp17 protocol and the leakage rules:

- no re-labelling with Qwen, no Last2 retraining, no re-download of images;
- test targets, test-period reviews, ratings and review-derived labels of the
  target item are never features — candidate tactile features come only from the
  **image** predictor, user tactile preference only from **past** interactions;
- architecture and hyper-parameter selection happen on validation only;
- previously seen items are excluded for every model; ties break by ascending
  `iid`.

---

## 6. Honest record of prior test exposure

Per the prompt's instruction to state this rather than hide it:

- exp16b opened the official test split first, so everything afterwards is
  post-hoc with respect to it.
- exp17b ran a **preliminary backbone test pass before the alpha lock**; its
  outputs were quarantined to `artifacts/quarantined_pre_alpha_test/` rather than
  deleted, and exp17b explicitly declines to call its final table a fully unread
  confirmatory test (`RESULTS.md`).
- exp20 records `protocol_state = complete_locked_posthoc_exploratory`,
  `confirmatory: false`.

**Therefore Exp24 cannot produce a confirmatory claim on this test split either.**
Everything here is locked post-hoc exploratory, and the report must say so.
