# Review-Cold-Start Tactile Retrieval
## End-to-End Research and Experiment Specification for Codex

> **Project root assumption:** `/home/user/onsesang/material_span_grounding`  
> **Semantic labeler:** Reuse the repository's existing **Qwen Instruct** model/checkpoint for review-span semantic grounding. The exact checkpoint/model ID must be discovered from the current repository/config and recorded in each run manifest rather than silently replaced.  
> **Important:** Before implementing anything, audit the existing repository and reuse existing modules, schemas, caches, embeddings, experiment utilities, and existing Qwen inference code wherever possible. Do not duplicate already implemented functionality.

---

# 0. Purpose of this document

This document specifies the end-to-end research pipeline for a paper on **review-cold-start tactile retrieval**.

The core problem is:

> Existing products may have buyer reviews containing tactile evidence such as "very soft", "slightly rough", "thin", or "stretchy".  
> Newly listed products have images but no buyer reviews.  
> We want to learn tactile information from existing product reviews and transfer only **reliably visually recoverable tactile information** to review-less products.  
> If the evidence is not sufficiently reliable, the system must preserve an **UNKNOWN / unverified** state rather than hallucinating a tactile property.

The research is NOT simply:
- review tactile extraction,
- image-to-review embedding regression,
- multimodal fusion,
- attribute-specific gating,
- or tactile-aware reranking.

The experiments must test whether **sparse, selectively mentioned buyer-review tactile evidence can supervise reliable visual tactile prediction and improve tactile-conditioned retrieval for review-cold-start products**.

---

# 1. Non-negotiable implementation principles

## 1.1 No hardcoded queries, questions, or semantic rules

The implementation MUST NOT contain hardcoded natural-language questions such as:

```python
if axis == "softness":
    question = "Is this product soft?"
elif axis == "roughness":
    question = "Is this product rough?"
```

This is prohibited.

Similarly, do not hardcode:
- query sentences,
- prompt variants per class,
- class-specific if/else branches,
- class-specific thresholds,
- manually written mappings scattered throughout source files,
- manually curated keyword lists embedded in Python code,
- hand-authored test queries that determine the reported result.

All experiment behavior must be **configuration-driven**.

Allowed:
- a tactile taxonomy/config file,
- reusable generic prompts parameterized by taxonomy metadata,
- generic ranking/query generation code,
- generic label aggregation code.

Preferred:

```yaml
axes:
  - id: softness
    poles:
      negative: soft
      positive: firm
    aliases:
      - softness
      - firmness
  - id: surface_texture
    poles:
      negative: smooth
      positive: rough
```

The core code should operate on `axis.id`, `axis.poles`, etc. without special-case logic.

---

## 1.2 Tactile classes/axes are allowed, but they must be declarative

A structured tactile taxonomy is unavoidable for the controlled experiments.

However:
- store it in YAML/JSON/config,
- never bake class names into model architecture code,
- allow the number of axes to change without editing model source,
- preserve the original open-vocabulary review span in all records.

The system must support:

```text
Structured tactile axis
+
Original open-vocabulary evidence span
```

Do NOT replace the original review phrase with only a closed class.

---

## 1.3 UNKNOWN is not a tactile class

This distinction is critical.

There are at least three different states:

### A. REVIEW_UNOBSERVED
The review does not mention an attribute.

Example:

```text
Review: "Love the color and fit."
Softness: REVIEW_UNOBSERVED
```

This does NOT mean:
- neutral,
- average,
- not soft,
- negative.

It means there is no supervision for that product-attribute pair.

During image-model training:
- mask this target out of the loss.

### B. REVIEW_DISAGREEMENT
The property is mentioned, but buyers disagree.

Example:

```text
4 buyers: soft
4 buyers: firm
```

This is NOT missing.

Preserve:
- mean/ordinal consensus,
- vote distribution,
- support count,
- disagreement/entropy/variance.

### C. VISUAL_ABSTAIN / UNKNOWN
At inference time, the system has no buyer review and decides that visual evidence is insufficiently reliable.

This is an inference-time abstention state.

Do not train `UNKNOWN` as a sixth softness class.

---

# 2. Research question

Primary research question:

> Can sparse and selectively mentioned tactile evidence in buyer reviews supervise a reliable visual tactile representation for review-cold-start products, and can property-level visual recoverability plus instance-level predictive uncertainty improve tactile-conditioned retrieval by abstaining when visual evidence is not trustworthy?

Sub-questions:

1. Can open-vocabulary buyer tactile expressions be grounded into a small structured tactile space without discarding the original expression?
2. Are structured tactile targets easier and more robust for image prediction than the current high-dimensional review embedding target?
3. Which tactile properties can be transferred from image with meaningful reliability?
4. Does a model trained on buyer-review pseudo-supervision generalize to independent tactile/perceptual datasets?
5. Does property-level visual recoverability provide information beyond raw model confidence?
6. Is selective prediction better than forcing predictions for every tactile property?
7. Does the resulting system improve tactile-conditioned ranking of products with zero reviews?
8. How severe is selective review-mention bias, especially the tendency to mention extreme tactile experiences?

---

# 3. Dataset roles

Do NOT merge datasets naively.

Each dataset has a distinct role.

## 3.1 Amazon Fashion / current project data

Role:
- main e-commerce dataset,
- buyer-review weak supervision,
- product-image learning,
- review-cold-start retrieval benchmark.

Current known project state should be audited rather than regenerated blindly.

Relevant current assets include approximately:
- 500 products,
- 4,158 reviews,
- 6,345 exact tactile/material spans,
- 4,527 Qwen-accepted tactile claims,
- existing product-level review tactile embeddings,
- existing FashionCLIP-based image features,
- existing product-family split utilities.

Important:
- Qwen-accepted claims are pseudo-labels, not human gold.
- review-derived product vectors are proxy targets, not physical tactile ground truth.

---

## 3.2 Leeds Fabric Perception data

Role:
- external perceptual/visuotactile grounding,
- property-level image-vs-touch recoverability analysis.

Candidate bipolar axes from the literature:
- Flexible ↔ Stiff
- Smooth ↔ Rough
- Soft ↔ Firm
- Spongy ↔ Crisp
- Warm ↔ Cool

Important:
- treat them as axes, not 10 independent classes,
- use continuous/ordinal values if the raw rating format supports them,
- do not assume the dataset can be used until raw images/ratings and licensing/access are verified.

Leeds should NOT be used as the sole training dataset for the Amazon image model.

---

## 3.3 MLLM-Fabric or similar external tactile dataset

Role:
- external validation for tactile attributes not covered well by Leeds,
- especially candidate properties such as:
  - elasticity,
  - thickness,
  - softness,
  - texture.

Do not assume identical scales across external datasets.
Calibrate and evaluate attributes separately.

---

## 3.4 Optional Jiffy-style commercial product data

Potential role:
- supplementary validation where product image, buyer review text, material composition, and structured buyer softness ratings coexist.

Before use:
- verify terms of service,
- verify crawling/research permission,
- verify reproducibility,
- verify redistribution restrictions.

Do not build the core paper around a dataset that cannot legally/reproducibly be acquired.

---

## 3.5 H&M

H&M is NOT the main dataset for this paper because:
- it has product images and product description/metadata,
- but not the buyer-review tactile evidence required by the primary research question.

H&M can be used only as an optional secondary domain or for comparisons with product-description-based models.

Do not mix seller description and buyer review as if they were semantically equivalent.

---

# 4. Tactile taxonomy design

Do NOT immediately assume seven axes.

First perform empirical coverage analysis over the current Amazon exact spans.

Initial candidate axes:

```text
softness
surface_texture / roughness
elasticity
thickness
flexibility
warmth
sponginess
```

The final active axis set MUST be chosen based on:
- review coverage,
- number of unique products,
- number of independent reviewers,
- polarity balance,
- intensity balance,
- external tactile benchmark availability,
- semantic separability.

The likely first experimental subset is:

```text
softness
surface_texture / roughness
elasticity
thickness
```

because these are expected to be easier to interpret and more common in apparel reviews.

But Codex must not assume this list is final.

Store taxonomy in config.

Suggested file:

```text
configs/tactile_axes.yaml
```

Suggested schema:

```yaml
version: 1

axes:
  - id: softness
    display_name: Softness
    type: bipolar_ordinal
    negative_pole: soft
    positive_pole: firm
    external_sources:
      - leeds
      - mllm_fabric

  - id: surface_texture
    display_name: Surface texture
    type: bipolar_ordinal
    negative_pole: smooth
    positive_pole: rough
    external_sources:
      - leeds

  - id: elasticity
    display_name: Elasticity
    type: ordinal
    negative_pole: non_elastic
    positive_pole: elastic
    external_sources:
      - mllm_fabric
```

The code must automatically adapt to any number of axes.

---

# 5. Review-to-tactile grounding

## 5.1 Input

Use the existing exact tactile span extraction results.

Each tactile observation should retain:
- product_id,
- review_id,
- user/reviewer identifier internally if available,
- exact span,
- review context,
- source review timestamp if available,
- existing Qwen acceptance result,
- negation,
- scope,
- condition/context,
- category/product metadata if required for analysis.

Raw reviewer identifiers must not leak into exported/public artifacts.

---

## 5.2 Generic grounding output

Each accepted span should be mapped to a structured schema.

Example schema:

```json
{
  "axis_id": "softness",
  "direction": "negative",
  "intensity": "strong",
  "mappable": true,
  "evidence_span": "extremely soft",
  "scope": "garment_body",
  "confidence": 0.93
}
```

Unmappable:

```json
{
  "axis_id": null,
  "direction": null,
  "intensity": null,
  "mappable": false,
  "evidence_span": "feels luxurious",
  "scope": null,
  "confidence": 0.77
}
```

Do not discard unmappable spans.

---

## 5.3 Qwen semantic labeler

The semantic grounding model for this project is **Qwen Instruct**, reusing the Qwen model/checkpoint already used in the repository for tactile-claim semantic validation whenever possible.

Qwen's role is intentionally narrow:

```text
exact buyer-review span + local review context + tactile taxonomy config
        ↓
Qwen Instruct
        ↓
mappable / axis_id / direction(or pole) / intensity / scope / mapping confidence
```

Qwen MUST NOT be used to directly generate the final continuous product-level tactile score.

The exact Qwen checkpoint must not be invented in this document or silently changed in code. Codex must first inspect the repository, identify the current Qwen model ID/checkpoint/tokenizer/inference wrapper, reuse it as the default semantic labeler, and expose the model ID through experiment config.

Suggested config shape:

```yaml
semantic_labeler:
  provider: qwen
  model_id: REUSE_EXISTING_REPO_QWEN_MODEL_ID
  mode: instruct
  temperature: 0.0
  output_format: json
```

If a larger/different Qwen checkpoint is later tested, it must be treated as an explicit ablation and evaluated on the same human-audited subset.

### Prompting constraints

Use ONE generic schema-driven Qwen prompt.

Bad:

```python
softness_prompt = "Is the text soft or firm?"
roughness_prompt = "Is the text smooth or rough?"
```

Good:

```text
Given:
- tactile taxonomy loaded from config,
- exact buyer-review span,
- local review context,

return a JSON object containing:
- whether the span is safely mappable,
- the matching axis_id,
- the matching pole/direction,
- intensity,
- scope if present,
- semantic-mapping confidence.
```

The axis definitions must be inserted dynamically from config.

No class-specific questions. No axis-specific prompt branches. No manually written question per tactile property.

---

## 5.4 Qwen outputs symbolic labels; code creates numeric targets

Do NOT ask Qwen to output:

```text
softness = -0.82
```

Qwen should output symbolic/ordinal structure such as:

```json
{
  "mappable": true,
  "axis_id": "softness",
  "direction": "soft",
  "intensity": "strong",
  "scope": "garment_body",
  "confidence": 0.93
}
```

Then convert the symbolic result deterministically in code using taxonomy/config metadata.

Baseline ordinal coding can be:

```text
strong negative pole = -2
negative pole        = -1
neutral              =  0
positive pole        = +1
strong positive pole = +2
```

But this scale must be stored in config and treated as a baseline assumption.

Do not claim equal perceptual distances between ordinal levels.

Example:

```text
Span: "extremely soft"
Qwen output: axis=softness, direction=soft, intensity=strong
Config: softness.negative_pole=soft
Deterministic baseline conversion: strong negative pole -> -2
```

A product-level value such as `softness = -0.82` is created only **after** reviewer-level and product-level aggregation. It is never a raw Qwen output.

---

# 6. Product-level tactile target aggregation

## 6.1 Reviewer-level aggregation first

A single reviewer may produce several tactile spans.

Do NOT treat every span as an independent vote.

For each:

```text
(product_id, reviewer_id, axis_id)
```

aggregate that reviewer's evidence first.

Then aggregate across distinct reviewers.

This prevents one verbose reviewer from dominating the target.

---

## 6.2 Product-attribute record

Create a normalized table such as:

```text
product_id
axis_id
target_mean
target_distribution
support_reviewers
support_spans
agreement
dispersion
mask
source
```

Example:

```text
A123
softness
-1.25
[0.30, 0.55, 0.10, 0.05, 0.00]
8
11
0.86
0.21
1
review_pseudo
```

Missing:

```text
A123
elasticity
null
null
0
0
null
null
0
review_unobserved
```

---

## 6.3 Preserve disagreement

Do not collapse buyer disagreement into UNKNOWN.

Potential representations:
- mean + variance,
- ordinal vote distribution,
- Dirichlet-smoothed class distribution,
- entropy.

At minimum store:
- mean/median,
- number of unique reviewers,
- dispersion,
- entropy/agreement.

---

# 7. Critical bias: selective review mention / MNAR

A central concern is that buyers may mention tactile properties primarily when the experience is extreme.

Examples:

```text
"extremely rough"
"insanely soft"
"much thinner than expected"
"super stretchy"
```

while ordinary products receive no tactile mention.

Therefore:

```text
no mention != neutral
```

and:

```text
observed tactile labels are not an unbiased sample
```

This must be empirically diagnosed.

---

# 8. Mandatory dataset diagnostics BEFORE training

Codex must create a diagnostics pipeline and report.

For every candidate axis:

1. number of spans,
2. number of reviews,
3. number of unique products,
4. number of unique reviewers,
5. products with >=2 independent reviewers,
6. products with >=3 independent reviewers,
7. UNKNOWN/unobserved rate,
8. direction distribution,
9. intensity distribution,
10. ordinal target histogram,
11. product-level support-count histogram,
12. reviewer disagreement distribution,
13. category distribution,
14. category-by-target distribution,
15. material composition distribution if available,
16. temporal distribution if timestamps exist.

Required outputs:
- CSV/JSON summary,
- plots,
- Markdown report.

Suggested:

```text
reports/tactile_axis_diagnostics.md
artifacts/tactile_axis_stats.csv
artifacts/plots/
```

---

## 8.1 Explicit extreme-mention-bias diagnostics

Test whether observed tactile claims appear disproportionately extreme.

Possible analyses:

### A. Intensity histogram
Compare:
- weak,
- normal,
- strong.

### B. Product-level ordinal histogram
Inspect U-shape / center sparsity.

### C. Mention-rate proxy
If a review contains no claim for an axis, treat as unobserved only.

Do NOT infer neutral.

### D. Length/control analysis
Check whether tactile mention correlates with review length.

### E. Rating association
Check whether tactile mentions or extreme tactile claims correlate with low/high star ratings.

### F. Category association
Check if particular categories dominate one pole.

The goal is to determine whether the review-derived supervision is highly selected.

---

# 9. Human audit subset

Before training the image model, create a small human-audited subset for review-to-axis grounding.

Recommended:
- stratified sample of 500-1,000 spans if feasible,
- balanced across candidate axes,
- balanced across poles/intensity where feasible,
- include unmappable/open-vocabulary cases,
- include negation,
- include body-part/scope cases,
- include ambiguous expressions.

Annotate:
- mappable yes/no,
- axis,
- direction/pole,
- intensity,
- scope if relevant.

Metrics:
- axis macro F1,
- polarity accuracy,
- intensity weighted kappa or ordinal agreement,
- unmappable detection F1,
- exact-span preservation check.

This audit is required because the downstream image model is otherwise trained on unchecked pseudo-label noise.

---

# 10. Train/validation/test split

## 10.1 Product-family split

Use a product-family split, not random image split.

Same or near-duplicate product variants must not cross splits.

Example:

```text
train family 70%
validation family 15%
test family 15%
```

Reuse the current project family grouping if valid.

---

## 10.2 No review leakage

For test products:
- reviews must never participate in image-model training,
- reviews must never participate in prompt/taxonomy tuning after the split is locked,
- reviews must never participate in threshold calibration,
- reviews must remain hidden until evaluation.

If doing temporal recommendation:
- only reviews available before the cutoff may create features.

---

# 11. Image-to-tactile prediction task

## 11.1 Input

Product image(s).

Image representation candidates:
- FashionCLIP,
- DINO/DINOv3 global feature,
- optional local/patch feature,
- VLM zero-shot baseline.

Start with frozen encoders.

Do not full-finetune large encoders on ~500 products as the first experiment.

---

## 11.2 Target

For each product and axis:

```text
value
mask
support_count
agreement
distribution
```

Missing targets are masked.

---

## 11.3 Baseline models

Required minimum:

### B0. Category-only
Predict tactile targets from category only.

Purpose:
- detect category shortcut.

### B1. Image embedding + Ridge
Frozen image embedding -> independent or multi-output Ridge.

### B2. Image embedding + Linear head
Frozen encoder.

### B3. Image embedding + tiny MLP
One small hidden layer.

### B4. Current open-space baseline
Current image -> 384-d review tactile embedding system.

Purpose:
- compare structured low-dimensional target vs current open-vocabulary embedding target.

### B5. VLM zero-shot
Generic taxonomy-driven prompt only.

No hardcoded axis-specific questions.

---

# 12. Loss design

## 12.1 Masked regression baseline

For known product-attribute pairs:

\[
L =
\frac{
\sum_{i,c} m_{i,c} w_{i,c}
\operatorname{Huber}(\hat{y}_{i,c}, y_{i,c})
}{
\sum_{i,c} m_{i,c} w_{i,c}
}
\]

where:
- `m=1` only when review evidence exists,
- `m=0` for REVIEW_UNOBSERVED,
- `w` is optional reliability based on support/agreement.

Do not include missing labels as zero.

---

## 12.2 Ordinal prediction

Because tactile strength levels are ordered but not guaranteed equally spaced, implement an ordinal baseline.

Compare:
- regression,
- ordinal classification/regression.

Do not assume one is superior.

---

## 12.3 Pairwise ranking

Because review observations may overrepresent extremes, implement a pairwise/ordinal ranking objective.

For products A and B with sufficiently reliable evidence on the same axis:

```text
A softer than B
```

train:

\[
f_c(I_A) < f_c(I_B)
\]

or the corresponding pole orientation from config.

Pair generation must be generic and config-driven.

Avoid pairs where:
- both targets are uncertain,
- difference is below a configurable margin,
- evidence support is insufficient.

No hand-authored pairs.

This may be particularly useful if absolute calibration is poor but relative tactile ordering is learnable.

---

# 13. Compare three supervision strategies

Required ablation:

1. **Masked Regression**
2. **Ordinal**
3. **Pairwise Ranking**

Optional:
4. combined ordinal + pairwise objective.

Evaluate which is most stable under sparse/extreme review supervision.

---

# 14. Label reliability weighting

Do not assume all review-derived labels are equally trustworthy.

Candidate reliability features:
- number of unique reviewers,
- reviewer agreement,
- entropy,
- span mapping confidence,
- number of independent supporting reviews.

Compare:

### W0
No weighting.

### W1
Support-count weighting.

Example generic transform:

```text
log(1 + support)
```

### W2
Agreement weighting.

### W3
Support + agreement.

Any formula must be parameterized/configurable and tuned on validation data.

Do not hardcode per-axis weights.

---

# 15. Category/material shortcut analysis

The model may learn:

```text
sweater -> soft
denim -> stiff
legging -> stretchy
```

instead of actual tactile visual cues.

Mandatory tests:

## 15.1 Category-only baseline
Already required.

## 15.2 Same-category evaluation
Evaluate ranking/prediction only among items of the same category.

## 15.3 Category-stratified metrics
Report per-category and macro average where sample size allows.

## 15.4 Optional material composition baseline
If composition data are available:

- composition only,
- image only,
- image + composition,
- category only,
- image + category.

Do not claim composition is tactile ground truth.

---

# 16. External tactile validation

This stage tests whether the Amazon-trained visual predictor learns tactile semantics rather than only Amazon linguistic/category shortcuts.

## 16.1 Leeds

For overlapping axes:
- map external labels into compatible axis orientation,
- do not force incompatible properties,
- keep dataset-specific scaling separate.

Evaluate:
- Spearman correlation,
- ordinal accuracy,
- pairwise accuracy,
- optionally MAE after validation-only scale calibration.

Also compute property-level image-touch agreement if raw ratings support it.

This becomes a candidate **visual recoverability prior**.

---

## 16.2 MLLM-Fabric / other external data

Use for overlapping attributes such as:
- softness,
- elasticity,
- thickness,
- texture.

Again:
- do not merge score scales blindly,
- evaluate each external source independently.

---

# 17. Property-level visual recoverability

For each tactile axis `c`, estimate:

```text
O_c = visual recoverability of property c
```

Possible definitions depending on external data:
- image-rating vs touch-rating correlation,
- image-model performance against tactile labels,
- normalized external pairwise accuracy,
- calibrated external validation score.

Do NOT fix the final formula before inspecting the data.

Important distinction:

### Property-level recoverability
`O_c`

Question:
> Is this tactile property generally recoverable from visual information?

### Instance-level model confidence
`C_i,c`

Question:
> Is the model confident about this particular product image?

These must remain separate.

---

# 18. Instance-level uncertainty/confidence

Do NOT treat raw regression magnitude as confidence.

Candidate methods:

1. predictive distribution entropy for ordinal model,
2. deep ensemble variance,
3. MC dropout variance,
4. heteroscedastic regression,
5. distance-to-training-distribution,
6. post-hoc calibration.

Start simple.

Validation-set calibration is mandatory.

Report:
- calibration error where appropriate,
- confidence vs actual error correlation,
- risk-coverage curves.

---

# 19. Selective tactile prediction

At inference for a review-less product:

```text
image
-> tactile prediction
-> instance confidence
-> combine with property-level visual recoverability
-> predict or abstain
```

The first baseline can use:

\[
R_{i,c} = O_c \times C_{i,c}
\]

but this is ONLY a baseline.

Compare:
- confidence only,
- recoverability only,
- product,
- learned generic calibrator over `[O_c, C_i,c, optional features]`.

The learned calibrator must be generic across axes unless an ablation explicitly tests otherwise.

No per-axis handcrafted threshold code.

Thresholds must come from:
- validation optimization,
- a target coverage,
- a target risk,
- or configuration.

---

# 20. Selective prediction evaluation

Accuracy alone is invalid because abstaining on everything trivially increases accuracy among answered samples.

Required:

- coverage,
- risk/error,
- risk-coverage curve,
- AURC or equivalent,
- performance at fixed coverage points,
- coverage at fixed risk if useful.

Example fixed coverage:
- 100%,
- 80%,
- 60%,
- 40%.

Do not choose only the operating point that makes the proposed method look best.

---

# 21. Review-present vs review-cold-start inference

## 21.1 Existing product with buyer reviews

Prefer direct buyer-review evidence when adequate support exists.

Possible strategies to compare:
- review-only,
- image-only,
- naive fusion,
- reliability-aware evidence selection.

Do not assume review is perfect; preserve support and disagreement.

---

## 21.2 New product with zero buyer reviews

Only image-based tactile prediction is available.

For each axis:
- if reliability passes selective criterion -> use predicted tactile evidence,
- otherwise -> VISUAL_ABSTAIN / UNKNOWN.

Do not convert UNKNOWN to a negative match.

---

# 22. Tactile-conditioned retrieval

Main downstream task should be tactile-conditioned product retrieval rather than generic purchase prediction.

Reason:
generic purchase behavior depends heavily on:
- price,
- style,
- brand,
- fit,
- popularity,
- etc.

Tactile relevance can be diluted in generic recommendation metrics.

---

## 22.1 Query representation

Queries must be parsed/grown generically from the tactile schema.

No hardcoded list like:

```python
queries = [
    "soft shirt",
    "rough sweater",
    "thick pants"
]
```

for the final benchmark.

Instead create structured query objects:

```json
{
  "constraints": [
    {
      "axis_id": "softness",
      "direction": "negative",
      "strength": 1.0
    }
  ]
}
```

Natural-language renderings, if needed, must be generated from:
- taxonomy/config,
- templates externalized into config,
- or a generic Qwen-based renderer if natural-language rendering is required.

The ranking system should consume the structured query.
Natural language is an interface layer, not the ground truth.

---

## 22.2 Query set construction

Construct query sets automatically from axes with sufficient test support.

Possible benchmark partitions:

### Single-axis
One tactile constraint.

### Multi-axis
Two or more compatible tactile constraints where sufficient ground-truth support exists.

### Cold-start-only
All candidate target items have zero training reviews.

### Mixed
Review-present and review-cold-start items coexist.

### Same-category retrieval
All candidates share category.

This is mandatory to reduce category shortcut.

The actual available queries must be determined from data coverage, not manually selected.

---

# 23. Retrieval ground truth

For held-out test products, hidden buyer reviews can provide **held-out buyer tactile evidence**.

Do not call this physical tactile ground truth.

For each test product/axis:
- aggregate held-out review evidence,
- require minimum support,
- construct graded relevance if possible.

Example:

```text
strongly matches query -> 3
matches -> 2
weak/neutral -> 1
opposite -> 0
```

The mapping must be generic/configurable.

If support is insufficient:
- exclude the product-axis pair from that query's evaluation,
- do not infer neutral.

---

# 24. Retrieval metrics

Required:
- NDCG@K,
- Recall@K,
- pairwise ranking accuracy.

Potential:
- MRR,
- MAP depending on query construction.

Always report:
- overall,
- cold-start subset,
- same-category subset,
- single-axis,
- multi-axis.

---

# 25. Retrieval baselines

Minimum:

1. Random
2. Popularity if applicable
3. Category-only
4. FashionCLIP image similarity
5. VLM zero-shot tactile scoring
6. Current open-vocabulary image-to-review-vector baseline
7. Structured-axis image prediction without abstention
8. Confidence-only selective prediction
9. Recoverability-only selective prediction
10. Naive image+review fusion where reviews exist
11. Proposed recoverability + calibrated uncertainty
12. Proposed method + UNKNOWN-aware ranking

Do not compare numbers from incompatible Amazon splits/protocols.

---

# 26. UNKNOWN-aware ranking

Unknown must not equal negative.

For each query constraint and product, possible states:

```text
SUPPORTED_MATCH
SUPPORTED_MISMATCH
UNKNOWN
```

Ranking logic must distinguish these.

A product with UNKNOWN:
- should not receive a positive tactile-match score,
- should not receive the same penalty as a confirmed mismatch,
- may receive an uncertainty penalty or neutral contribution depending on validated design.

Compare alternatives:

### U0
UNKNOWN = neutral zero contribution.

### U1
UNKNOWN = mild penalty.

### U2
Coverage-aware scoring.

### U3
Learned/validated risk-aware scoring.

No handcrafted per-axis behavior.

---

# 27. Material composition extension

If composition such as:

```text
Polyester 95%
Cotton 5%
```

is available, treat it as a separate structured information source.

Do NOT treat fiber composition as tactile ground truth.

Required optional ablation:

- Category only
- Image only
- Composition only
- Image + composition
- Image + category
- Image + composition + category
- Review upper bound where available

Special attention:
- elasticity,
- thickness,
- softness,
- roughness/texture.

Also test interaction with fabric structure if available.

Do not claim simple multimodal fusion is novel.

---

# 28. Main experiment sequence

Do NOT implement the entire recommendation stack first.

Proceed in gates.

---

## Experiment Gate 1: Taxonomy feasibility

Goal:
Determine whether structured tactile axes are sufficiently represented.

Steps:
1. map current tactile spans into configurable axes,
2. preserve original spans,
3. compute coverage,
4. compute product/reviewer counts,
5. compute intensity/polarity distribution,
6. compute unmappable/open-vocabulary fraction,
7. compute category confounding,
8. audit pseudo-label quality.

Success criteria should be defined after seeing distributions.

Failure signs:
- most axes have only tens of products,
- nearly all evidence lies in one category,
- axis mapping is too ambiguous,
- reviewer support per product is extremely low.

If failure:
- reduce active axis set,
- do not force sparse axes.

---

## Experiment Gate 2: Image prediction feasibility

Compare:
- category-only,
- FashionCLIP + Ridge,
- DINO + Ridge,
- linear head,
- tiny MLP,
- current 384-d review-vector baseline,
- VLM zero-shot.

Evaluate:
- per-axis Spearman,
- MAE/Huber metric,
- direction accuracy,
- pairwise accuracy,
- same-category metrics,
- multiple random seeds.

Success:
image model must beat category-only meaningfully and remain non-trivial on same-category evaluation.

Failure:
if category-only explains most performance, the model is not learning tactile visual cues.

---

## Experiment Gate 3: Learning objective robustness

Compare:
- masked regression,
- ordinal,
- pairwise ranking,
- optional combined objective.

Evaluate under:
- all labeled data,
- high-support labels only,
- extreme-only subset,
- moderate-intensity subset if available.

Goal:
test whether pairwise/ordinal learning is more stable under selective/extreme review supervision.

---

## Experiment Gate 4: External tactile transfer

Train on Amazon review-derived supervision.

Evaluate zero-shot or minimally calibrated on:
- Leeds,
- MLLM-Fabric,
- other compatible tactile benchmark.

No test-time fitting on external test labels.

Goal:
determine whether the learned representation transfers beyond Amazon language/category shortcuts.

Failure:
strong Amazon performance but near-random external performance indicates weak tactile grounding.

---

## Experiment Gate 5: Uncertainty and recoverability

Compute:
- property-level recoverability,
- instance-level calibrated confidence.

Compare:
- confidence only,
- recoverability only,
- product baseline,
- learned calibrator.

Evaluate:
- risk-coverage,
- AURC,
- error at fixed coverage.

Goal:
prove recoverability contributes beyond confidence.

---

## Experiment Gate 6: Review-cold-start retrieval

Create hidden-review tactile relevance for test products.

Compare all retrieval baselines.

Report:
- NDCG@10,
- Recall@10,
- same-category,
- cold-start,
- single-axis,
- multi-axis.

Only after this stage should the full end-to-end paper claim be evaluated.

---

# 29. Overfitting safeguards

Potential overfitting risks:
- ~500 products,
- even fewer labels per axis,
- multiple images per product falsely inflating apparent sample size,
- near-duplicate variants,
- high-dimensional frozen embeddings,
- too-large MLP.

Rules:
- split by product family,
- count effective sample size by product, not image,
- begin with Ridge/linear,
- tiny MLP only,
- regularization tuned on validation,
- report multiple seeds,
- bootstrap confidence intervals where feasible,
- do not full-finetune large encoders in the initial feasibility phase.

---

# 30. Underfitting safeguards

Potential underfitting:
- global image embeddings may not encode micro-texture.

Compare:
- FashionCLIP global,
- DINO global,
- optional patch aggregation/local features.

Potential hypothesis:
surface texture may require local evidence.

Do not assume this before experiment.

---

# 31. Pseudo-label noise safeguards

Review-derived targets pass through:
- span extraction,
- semantic validation,
- axis mapping,
- intensity mapping,
- product aggregation.

Errors can accumulate.

Required:
- human audit subset,
- confidence threshold ablation,
- high-confidence-only training ablation,
- support-count threshold ablation.

Potential experiment:

```text
All pseudo-labels
vs
High-confidence pseudo-labels
vs
Human-audited subset evaluation
```

---

# 32. Robustness experiments

Where data permits:

1. different random family splits,
2. different minimum reviewer support,
3. different confidence thresholds,
4. different active tactile-axis subsets,
5. with/without category features,
6. with/without composition,
7. high-confidence spans only,
8. extreme-only supervision,
9. no-intensity supervision,
10. regression vs ordinal vs pairwise,
11. global vs local visual features.

---

# 33. Statistical reporting

For key metrics:
- report mean/std over seeds where feasible,
- bootstrap confidence intervals for retrieval metrics,
- paired tests across identical queries if appropriate.

Do not overclaim tiny absolute differences.

---

# 34. Required artifacts

Codex should produce reproducible experiment artifacts.

Suggested layout:

```text
configs/
  tactile_axes.yaml
  experiments/
    axis_mapping.yaml
    image_prediction.yaml
    selective_prediction.yaml
    retrieval.yaml

src/
  tactile/
    taxonomy.py
    grounding.py
    qwen_semantic_labeler.py
    aggregation.py
    diagnostics.py
    targets.py

  vision/
    encoders.py
    tactile_predictor.py
    uncertainty.py

  calibration/
    recoverability.py
    confidence.py
    selective.py

  retrieval/
    query_schema.py
    relevance.py
    scorer.py
    evaluator.py

scripts/
  build_axis_targets.py
  run_tactile_diagnostics.py
  train_image_tactile.py
  evaluate_external_transfer.py
  calibrate_selective_prediction.py
  build_coldstart_benchmark.py
  evaluate_tactile_retrieval.py

reports/
  tactile_axis_diagnostics.md
  image_prediction_results.md
  external_transfer_results.md
  selective_prediction_results.md
  retrieval_results.md

artifacts/
  ...
```

Adapt to the repository's existing structure instead of duplicating modules unnecessarily.

---

# 35. Configuration-first requirement

All experimental differences should be controlled through config.

Example:

```yaml
experiment:
  seed: 42

taxonomy:
  path: configs/tactile_axes.yaml

semantic_labeler:
  provider: qwen
  model_id: REUSE_EXISTING_REPO_QWEN_MODEL_ID
  mode: instruct
  temperature: 0.0
  output_format: json

target:
  representation: ordinal
  min_reviewers: 2
  use_mapping_confidence: true

image_encoder:
  name: fashionclip
  frozen: true

predictor:
  type: ridge

loss:
  type: masked_huber

selective:
  method: calibrated
  target_coverage: 0.8

retrieval:
  k: [5, 10, 20]
  candidate_protocol: same_category
```

No hidden constants in source code.

---

# 36. No hardcoded natural-language benchmark

Do not report results on a tiny manually selected set of questions such as:

```text
"Find me a soft shirt."
"Find me a thick sweater."
```

The final benchmark must be generated from the structured tactile axis space and test-data support.

Human-readable examples may be shown qualitatively only.

The metric-driving benchmark must be data-generated and reproducible.

---

# 37. Qualitative examples

Qualitative figures may show:

- exact buyer-review tactile evidence,
- structured axis mapping,
- image prediction,
- confidence,
- external recoverability,
- final use/abstain decision.

Example format:

```text
Product: X

Buyer evidence:
"surprisingly soft but a little thin"

Mapped:
softness -> soft, strong
thickness -> thin, weak

New-product image prediction:
softness -> soft
confidence -> high

Property recoverability:
softness -> sufficient

Decision:
USE IMAGE EVIDENCE
```

and:

```text
elasticity -> high
model confidence -> high
external recoverability -> low

Decision:
ABSTAIN / UNKNOWN
```

Examples must be selected using documented criteria, not cherry-picked without disclosure.

---

# 38. Paper-level ablation table

Target final table structure:

| Method | Softness | Roughness | Elasticity | Thickness | Same-cat | External | AURC | Cold-start NDCG@10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Category only | | | | | | | | |
| Image open-vector | | | | | | | | |
| Image structured | | | | | | | | |
| Ordinal | | | | | | | | |
| Pairwise | | | | | | | | |
| Confidence only | | | | | | | | |
| Recoverability only | | | | | | | | |
| Recoverability + Confidence | | | | | | | | |
| + UNKNOWN-aware ranking | | | | | | | | |

Only include columns compatible with each experiment.

---

# 39. Hypotheses and falsification criteria

The pipeline must be treated as a sequence of falsifiable hypotheses.

## H1
Structured tactile axes improve image-learning stability over the current open 384-d review target.

Falsified if:
- no consistent improvement,
- only category shortcut gains,
- worse external transfer.

## H2
Amazon buyer-review tactile supervision transfers to external tactile semantics.

Falsified if:
- external correlation/pairwise accuracy is near random,
- category-only performs similarly.

## H3
Property-level recoverability adds information beyond model confidence.

Falsified if:
- confidence-only matches recoverability+confidence across risk-coverage metrics.

## H4
Selective prediction is useful.

Falsified if:
- abstention gives no better risk-coverage tradeoff,
- or simply destroys coverage without improving downstream ranking.

## H5
Selective tactile evidence improves review-cold-start retrieval.

Falsified if:
- NDCG/Recall gains are absent on cold-start and same-category subsets.

Do not continue to increasingly complex modeling if an earlier foundational hypothesis fails.

---

# 40. What must NOT be claimed

Do NOT claim:

- Amazon review-derived tactile targets are physical ground truth.
- Qwen-accepted tactile claims are human gold.
- Missing review mention means neutral.
- A high model confidence means the tactile property is visually observable.
- Leeds and Amazon scales are directly numerically comparable.
- Different Amazon recommendation protocols can be compared directly.
- Image + review fusion itself is novel.
- Attribute-specific gating itself is novel.
- Material composition alone determines tactile feel.
- A model that performs well across categories necessarily learned tactile cues.
- Reviewless-product image prediction is reliable for every tactile property.

---

# 41. Existing-prior positioning

Be aware of nearby prior directions:

- visual/tactile fabric perception,
- vision-to-touch embeddings,
- tactile property prediction from images,
- attribute-conditioned modality gating,
- missing-modality recommendation,
- review-derived sensory recommendation,
- fine-grained review attribute recommendation,
- selective prediction / abstention,
- material composition + mechanics prediction.

Therefore the paper should NOT be framed as:
- "first image-to-tactile prediction",
- "first tactile recommendation",
- "first review-based tactile extraction",
- "first attribute-specific multimodal gate".

Candidate differentiating problem formulation:

> Review-cold-start tactile retrieval under sparse and selectively mentioned buyer tactile evidence, where visual tactile evidence is accepted only when both the property is externally recoverable from vision and the instance-level prediction is sufficiently reliable; otherwise the system preserves an unknown state.

Novelty must still be validated against literature before final paper writing.

---

# 42. Recommended immediate implementation order

Codex should execute in this order.

## Phase 0. Repository audit
- inspect current schemas,
- locate existing review spans,
- locate the existing Qwen model/checkpoint, inference wrapper, prompt/schema, and cached Qwen outputs,
- locate image embeddings,
- locate family split,
- locate current 384-d regression evaluation,
- write a short reuse plan.

Do not modify behavior yet.

## Phase 1. Configurable tactile taxonomy
- build schema/config loader,
- no hardcoded axes in implementation.

## Phase 2. Review span -> axis grounding with Qwen Instruct
- reuse the repository's existing Qwen inference stack,
- one generic taxonomy-driven Qwen prompt,
- Qwen returns symbolic `mappable / axis / direction / intensity / scope / confidence`,
- preserve the original open span,
- cache Qwen outputs with model/checkpoint ID, prompt/schema version, and taxonomy version,
- deterministic score conversion happens in code, not in Qwen.

## Phase 3. Diagnostics
- generate all coverage/extreme-bias/category-confounding statistics.

STOP and inspect results before selecting the final active axis set.

## Phase 4. Human audit support
- export annotation sheet/sample,
- evaluation script for mapping quality.

## Phase 5. Product-level targets
- reviewer-first aggregation,
- mean/distribution/support/agreement/mask.

## Phase 6. Image prediction baselines
- category-only,
- frozen FashionCLIP/DINO + Ridge,
- linear,
- tiny MLP,
- open-vector baseline.

## Phase 7. Regression vs ordinal vs pairwise
- compare robustness.

## Phase 8. External tactile transfer
- Leeds / MLLM-Fabric where accessible.

## Phase 9. Confidence and recoverability calibration
- risk-coverage evaluation.

## Phase 10. Review-cold-start tactile retrieval
- hidden review relevance,
- no hardcoded query list,
- NDCG/Recall.

## Phase 11. Full ablations and paper tables
- only after earlier gates pass.

---

# 43. Deliverables expected from Codex

For each phase, Codex must provide:

1. implementation,
2. unit tests,
3. CLI command,
4. config example,
5. output schema,
6. generated report,
7. limitations/failure notes,
8. exact data split IDs or hashes where practical.

No experiment should exist only as an ad-hoc notebook.

Notebooks may be used for exploration, but final reported experiments must be runnable from scripts/config.

---

# 44. Reproducibility

Every run must record:

```text
git commit
timestamp
config
random seed
dataset version
split identifier
taxonomy version
Qwen semantic-labeler model/checkpoint ID
Qwen prompt/schema version
model/encoder identifier
input cache identifier
output directory
metrics
```

Prefer a machine-readable run manifest.

---

# 45. Most important conceptual distinction

The entire paper depends on keeping these four objects separate:

```text
1. Buyer-review tactile evidence
   = weak, selective, subjective supervision

2. Structured tactile target
   = derived pseudo-target for training

3. Property-level visual recoverability
   = external evidence about whether a tactile property can generally be inferred visually

4. Instance-level model confidence
   = uncertainty about one prediction on one product
```

Do not collapse any of them into a single "confidence score" too early.

---

# 46. Final end-to-end pipeline

```text
                 EXISTING PRODUCTS
                       │
                       ▼
              Amazon Buyer Reviews
                       │
                       ▼
             Exact tactile spans
                       │
                       ▼
        Qwen taxonomy grounding
             /                 \
            /                   \
Structured tactile axes      Open-vocab span
            │
            ▼
Reviewer-level aggregation
            │
            ▼
Product-level weak tactile targets
(value + distribution + support + agreement + mask)
            │
            │ supervision
            ▼
        Product Images
            │
      Frozen visual encoder
            │
            ▼
      Tactile predictor
            │
       prediction + uncertainty
            │
            │
            │                  EXTERNAL DATA
            │                       │
            │              Leeds / MLLM-Fabric
            │                       │
            │                       ▼
            │             Property-level visual
            │                recoverability
            │                       │
            └──────────┬────────────┘
                       ▼
             Selective tactile evidence
                  /              \
                 /                \
              USE               ABSTAIN
               │                   │
               │                UNKNOWN
               └─────────┬─────────┘
                         ▼
               Tactile-conditioned
                    retrieval
                         │
                         ▼
                    Ranked items
                         │
                         ▼
              HIDDEN TEST REVIEWS
                         │
                         ▼
             Held-out buyer tactile
                  relevance
                         │
                         ▼
             NDCG / Recall / AURC
```

---

# 47. Immediate first milestone

Before training any new neural model, produce:

```text
Tactile Axis Feasibility Report
```

with, for every candidate axis:

- exact-span count,
- accepted-span count,
- unique product count,
- unique reviewer count,
- >=2 reviewer product count,
- missing rate,
- pole distribution,
- intensity distribution,
- product target distribution,
- disagreement,
- category distribution,
- category/target mutual dependence,
- unmappable fraction,
- examples sampled automatically by stratum.

Then recommend the active axis set based on explicit quantitative criteria.

Do NOT choose axes only because they were used by Leeds.

---

# 48. Final instruction to Codex

Do not optimize for implementing the fanciest model.

Optimize for answering the research questions with the smallest defensible experiment first.

The first priority is to determine whether:

```text
review-derived tactile evidence
        ->
structured tactile supervision
        ->
image prediction
        ->
external tactile transfer
```

actually works.

If this chain does not hold, stop and report the failure rather than hiding it behind a downstream recommender.

If it does hold, proceed to:

```text
visual recoverability
+
calibrated instance uncertainty
+
UNKNOWN-aware selective ranking
```

and finally evaluate review-cold-start tactile retrieval.

The codebase must remain generic, config-driven, reproducible, and free from hardcoded natural-language questions or class-specific control flow. Qwen is the fixed semantic-labeling model family for this plan, but the exact checkpoint/model ID, decoding settings, taxonomy, and prompt/schema version must remain configuration-controlled and logged.
