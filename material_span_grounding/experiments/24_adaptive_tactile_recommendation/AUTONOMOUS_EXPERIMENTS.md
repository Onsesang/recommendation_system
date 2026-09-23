# Autonomous follow-up experiments

Each entry is written **before** the experiment runs, and states why it is needed,
what hypothesis it tests, and what result would count as success or failure.
Budget: at most 1-2 meaningful follow-ups per priority, per the task rules.

---

## A24-1 — Standardised tactile ANN for the R7 candidate generator

**Recorded 2026-09-17 02:55 KST, before running.**

### Why it is needed

The first R7 candidate-recall measurement (validation, 14,731 users) is:

| generator | Recall@500 |
|---|---:|
| SASRec | 0.038083 |
| tactile ANN (raw cosine) | **0.001358** |
| union (500 + 500) | 0.039373 |

The tactile arm contributes almost nothing: the union gains only +0.00129 over
SASRec alone. Taken at face value this kills the candidate-recall leg of R7.

But there is a mechanical reason to suspect the *query*, not the idea. Last2
outputs 14 independent sigmoids, so every item's tactile vector lies in
[0,1]^14 with mostly-positive entries. Cosine similarity between two such vectors
is near 1 for almost any pair — the measure is dominated by the shared positive
mean, not by how the items differ. Ranking 825,869 items by that cosine is close
to ranking them by vector magnitude.

### Hypothesis

H: centring each tactile dimension by its catalog mean and scaling by its
catalog standard deviation before the cosine makes the ANN discriminative, and
raises tactile-arm Recall@500 materially above the raw-cosine version.

### Metric and decision rule

Primary: **Recall@500 of the tactile arm alone, on the validation cohort.**
Secondary: union Recall@500, and union Recall@500 minus SASRec Recall@500.

- **Success**: standardised tactile Recall@500 ≥ 0.010 (a ~7x improvement, still
  far below SASRec) **and** union Recall@500 − SASRec Recall@500 ≥ 0.005.
- **Failure**: below either threshold. In that case R7's candidate-recall leg is
  reported as genuinely unhelpful rather than as a query-construction artifact,
  and R7 is evaluated only as a learned reranker over SASRec candidates.

Either outcome is reported. The variant is chosen on **validation only**; test is
scored once with whichever query construction validation selects.

### Leakage note

Standardisation statistics are computed over the catalog's image-derived Last2
vectors, which contain no user, no interaction and no review information, so they
cannot leak the evaluation target.

### Result — FAILS both pre-registered thresholds

Validation cohort, 14,731 users, decided on validation only:

| generator | Recall@100 | Recall@300 | Recall@500 |
|---|---:|---:|---:|
| SASRec | 0.020773 | 0.031430 | 0.038083 |
| tactile ANN, raw cosine | 0.000339 | 0.000950 | 0.001358 |
| tactile ANN, **standardised** | 0.000611 | 0.001222 | **0.002240** |

| union (500 + 500) | Recall |
|---|---:|
| SASRec + raw-cosine tactile | 0.039373 |
| SASRec + standardised tactile | **0.040052** |
| SASRec alone | 0.038083 |

Decision against the rule written above:

- tactile-arm Recall@500 = **0.002240**, threshold was ≥ 0.010 → **FAIL**
- union − SASRec = 0.040052 − 0.038083 = **0.001969**, threshold was ≥ 0.005 → **FAIL**

Standardisation does exactly what the mechanism predicted — it improves the
tactile arm by 1.65x (0.001358 → 0.002240) and the effect replicates on test
(0.001100 → 0.001834). So the diagnosis of the raw cosine was correct. It simply
does not matter: even with a properly scaled query, ranking 825,869 items by
similarity to a 14-dimensional tactile profile retrieves the user's next item
about **17 times less often than the collaborative backbone does**, and the
backbone itself only reaches 0.038.

**Conclusion.** H is rejected. The weak tactile arm is not an artifact of query
construction. R7's candidate-recall leg is genuinely unhelpful on this dataset,
and the report must say so rather than attribute it to an implementation detail.
R7 is therefore carried forward and judged as a *learned reranker*, with its
candidate-recall contribution reported separately and honestly as ≈ +0.002
absolute recall.

**Selection.** Between the two query constructions, validation prefers the
standardised one (0.002240 > 0.001358), so that is what R7 uses on test. This
selection is about which of two variants to run, not a claim that either works.

A 14-dimensional, largely positively-correlated tactile vector simply does not
carry enough information to index a 825k catalog. This is the same direction as
exp20's `aligned − shuffle ≈ 0` result, reached independently.
