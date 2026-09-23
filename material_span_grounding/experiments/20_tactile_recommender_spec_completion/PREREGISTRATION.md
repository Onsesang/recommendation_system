# Experiment 20 preregistration: tactile recommender specification completion

Version: 1.0  
Frozen design date: 2026-09-08 (Asia/Seoul)  
Machine-readable protocol: `configs/protocol.json`  
Machine-readable model definitions: `configs/model_variants.json`

## 1. Purpose and claim boundary

This experiment completes the parts of the original Amazon Fashion tactile-recommendation specification that Experiment 16 did not implement directly: a true in-model tactile modality, interaction/tactile modality ablations, the original global history profiles, wider and hybrid candidate retrieval, identical Strong/SMORE candidate-pool comparisons for explicit tactile queries, and complete coverage/support/cold-start reporting.

The official Amazon Reviews'23 Amazon_Fashion test split was already opened by Experiment 16 before this preregistration was written. Consequently, every Experiment 20 result obtained on that same official test is a **locked post-hoc exploratory follow-up**, even when its implementation, hyperparameters, and validation selection are frozen before Experiment 20 reads the test inputs. Confidence intervals on this reused test describe uncertainty; they are not fresh confirmatory hypothesis tests.

Only either of the following can support a new confirmatory claim:

1. Amazon Fashion interactions from a genuinely unseen temporal period that were not used for prior training, development, evaluation, or design; or
2. a prospective human relevance benchmark whose user/query/candidate manifest and development/test partition are hash-locked before annotation, whose hidden test labels are not opened until all selection is locked, and whose annotator provenance is recorded.

Carving a new holdout from interactions already used to train or assess Experiments 16--19 is an internal robustness analysis, not a fresh confirmatory test. Previously inspected Experiment 14/19 outputs and incomplete Experiment 15 annotations are never promoted to confirmatory ground truth.

## 2. Research questions and fixed primary contrast

- RQ1: Does a dedicated frozen Last2 tactile modality add value inside a multimodal recommender, beyond generic image and text?
- RQ2: Does a global history-derived tactile profile improve two-stage recommendation, and how does it differ from the conservative category-local proxy?
- RQ3: Under an explicit tactile request, do tactile-aware systems rank tactile-relevant products above the same non-tactile Strong and generic-multimodal systems?
- RQ4: Are effects concentrated in users with usable tactile history or in interaction-cold / Last2-training-family-outside items?

The single primary Track-A contrast is:

```text
I+V+X+T minus I+V+X
metric: NDCG@10
population: all official Amazon_Fashion test targets
direction: greater is better
```

Here `I` is interaction, `V` is generic FashionCLIP image, `X` is generic FashionCLIP metadata text, and `T` is the frozen 14-dimensional `fashionclip_last2.pt` probability vector. The primary implementation seed is `20260904`. The paired user bootstrap uses 1,000 replicates and seed `20260904`. A positive point estimate whose 95% bootstrap interval excludes zero is the preregistered exploratory success criterion; because the test is reused, it is not described as confirmatory statistical evidence.

All other contrasts, cohorts, eight-class results, additional seeds, and candidate-conditional results are secondary or diagnostic and cannot replace the primary contrast.

## 3. Five fixed model groups

The exact architectures and training rules are in `configs/model_variants.json`.

1. `I`: the generalized recommender's behavioral user-item branch only.
2. `I_T`: the same behavioral branch plus a dedicated tactile branch.
3. `I_VX`: behavioral branch plus generic image, generic text, and their existing image-text fusion.
4. `I_VX_T`: `I_VX` with a dedicated tactile residual branch; this is the primary proposed model.
5. `I_VX_T_SHUFFLE`: identical to `I_VX_T`, but the tactile vectors are deterministically permuted within frozen category and train-count strata. This controls for added capacity and broad category/popularity structure.

The generic image/text modalities are not replaced by tactile. Last2 is inference-only: its checkpoint, preprocessing, class order, and output probabilities are never retrained or retuned. For the primary in-model variants, tactile probabilities are a frozen feature table; only recommendation-side projection, gate, and preference parameters train. Missing tactile features remain masked to an exactly zero tactile branch and never remove an item from the catalog.

The `I_VX_T` primary comparison preserves the complete `I_VX` side term and adds a tactile residual with fixed scale `1/3`, matching the contribution scale of one branch in the three-view generic side average. This scale is not tuned. `I_VX_T_SHUFFLE` has the same parameters and scale.

## 4. Development, selection, and irreversible state transitions

The Experiment 20 state is stored in `artifacts/protocol_state.json`. Only these forward transitions are valid:

```text
implemented_not_scored
  -> implementation_frozen_before_validation
  -> validation_locked_before_exp20_test
  -> exploratory_test_opened_no_retuning
  -> complete_locked_posthoc_exploratory
```

There is no reset transition. If a protocol, config, code, allowed-input hash, feature transform, candidate rule, normalization, model variant, or selection rule changes after `implementation_frozen_before_validation`, the run is invalid and must receive a new experiment directory/version. Operational retry is permitted only when it resumes the identical hashed computation without changing scientific settings.

Before the first validation metric is computed, the implementation lock must contain:

- SHA256 of both config files and all metric-producing source files;
- a complete input manifest with no unresolved required hash;
- environment/package versions;
- successful unit tests and a synthetic/dry-run record that contains no official validation or test metric;
- the exact five model IDs and all hyperparameter grids.

Before Experiment 20 may read `test_targets.parquet` or any official test row, `validation_locked_before_exp20_test` must contain:

- selected learning rate and epoch for every fixed model variant;
- selected candidate budget under the fixed rule;
- every reranker alpha selected on validation only;
- hashes of all validation selection tables, selected checkpoints, candidate rules, input manifest, configs, and metric code;
- an assertion that no Experiment 16 test-result artifact was used for development or selection.

Opening Experiment 20 test inputs is irreversible. No post-test training, profile selection, class selection, graph change, candidate-K change, alpha change, cohort redefinition, or normalization change is allowed.

The prospective human and future-temporal tracks use separate state files and never inherit an “unopened” status from Track A. Their independent state machines are specified in `configs/protocol.json`.

## 5. Data and split semantics

Track A uses the same hash-verified official McAuley-Lab Amazon Reviews'23 `benchmark/0core/last_out` split and the same full 825,869-parent catalog as Experiment 16. Training uses official train interactions only. Validation histories contain only earlier train events. Test-time histories may contain train plus the chronologically preceding official validation event, but no model parameter is refit on validation.

Interactions are review/rating events, not inferred clicks or purchases. `verified_purchase=True` is the only verified-purchase evidence. A history item is not treated as proof that every tactile property was liked.

The model and candidate universe never intersects down to tactile-covered or v3-labelled items. Seen items are removed identically, and missing tactile is neutral. Target category is never used as an offline filter. Category filtering is permitted only for an explicit user-provided category or a separately locked query/category benchmark.

The shared Experiment 16 `events.parquet` physically contains multiple splits. Before model code runs, an audited preparation step must materialize a train-only development view. Model-training and validation modules may read only the manifest-listed train view and validation targets, not the shared mixed-split file directly. Official test inputs remain sealed until the validation lock.

## 6. Tactile modality and graph

Primary tactile input is the 14 continuous probabilities in the fixed order:

```text
soft, firm, smooth, rough, non_elastic, elastic, thin, thick,
flexible, stiff, warm, cool, spongy, crisp
```

No threshold is applied. Available vectors are L2-normalized for the tactile graph. Missing rows remain zero and are excluded from graph neighbor search. The primary graph has `k=40`, removes self edges, clamps negative cosine weights to zero, adds reverse edges, and applies symmetric normalization.

Approximate-neighbor fidelity is an unsupervised engineering guard, not a recommendation hyperparameter search. A fixed 1,000-query exact-neighbor audit uses the escalation schedule `nprobe=32,64,128` and accepts the first setting with mean Recall@40 at least 0.95. If none passes, graph construction is marked blocked; it must not choose the setting using recommendation validation or test performance. The exact query IDs, index-training IDs, selected setting, graph file, and hashes are persisted.

The reliable eight classes are a predeclared sensitivity analysis only:

```text
smooth, rough, thin, thick, flexible, stiff, warm, cool
```

They cannot replace the 14-class primary model after test inspection.

## 7. Model selection

Each of the five model groups is retained; architecture is not selected by choosing the best validation model. Within each group, learning rate and checkpoint epoch are selected only by full-validation NDCG@10, then HR@10, then MRR@10, then the earlier epoch, then the smaller learning rate. The learning-rate grid is fixed at `{0.001, 0.0003}` and validation is evaluated every five epochs up to epoch 20.

Seed `20260904` is primary. Seeds `20260905` and `20260906` are robustness replications after the primary configuration is locked and never replace it.

## 8. Candidate retrieval

Every model reports exact full-catalog rank metrics and candidate Recall at:

```text
100, 300, 500, 1000, 3000, 10000, 30000
```

Candidate K is the smallest validation K with full-cohort Recall at least 0.80. If no K reaches 0.80, K is fixed to 30,000 and the report must state `retrieval_bottleneck_unresolved`; a favorable conditional cohort cannot be substituted for the full-cohort rule.

The hybrid diagnostic candidate set is a deterministic capped union of Strong, generic multimodal, in-model tactile, and tactile-ANN sources. Sources receive equal round-robin opportunity in a fixed order, duplicate item IDs are removed, and parent-ASIN ascending resolves score ties. Users without usable history do not receive a fabricated history-tactile source. Explicit-query mode may use full-catalog tactile ANN because tactile intent is directly supplied.

Test candidates are generated after the validation lock. Existing Experiment 16 test chunks are forbidden inputs because they contain held-out targets and target ranks. Candidate evaluation must stream batches and persist only resume state, per-user ranks, and display Top-K needed by the locked analysis.

## 9. Global and category-local reranking profiles

Eight configurations are reported independently; a test winner is never chosen among them:

- global all-history, 14 and 8 classes;
- global rating-at-least-4, 14 and 8 classes;
- category-local all-history, 14 and 8 classes;
- category-local rating-at-least-4, 14 and 8 classes.

The primary two-stage configuration is global all-history with 14 classes because it directly implements the original specification. Category-local profiles are conservative controls and remain the service-safe default when no explicit tactile query exists. Each configuration receives its own validation-only alpha from `0.00` through `1.00` in increments of `0.05`; ties choose the smaller alpha. Base and tactile scores use within-candidate rank percentiles with average ties. If alpha is zero, profile/class identity is not claimed to have been empirically selected.

## 10. Explicit tactile RQ3

The fixed query set contains eight single classes and eight non-contradictory pairs listed in `configs/protocol.json`. The explicit score is the mean predicted probability of requested classes; unselected classes are not negatives. General-history alpha and explicit-query alpha are separate validation selections for Strong and multimodal bases.

Track A compares, on the same item universe and judged/masked pool:

- Strong;
- Strong + explicit tactile;
- generic multimodal;
- generic multimodal + explicit tactile.

Existing v3 observed labels may be used only for an exploratory replication. `mask=0` means unknown and is excluded, never treated as negative. Previously generated review-derived evidence and image-derived probabilities remain separate fields and endpoints. No new Qwen inference is permitted.

For the confirmatory human track, the candidate pool, query assignment, family grouping, development/test partition, and system outputs are hash-locked before labels are collected. Annotators are blinded to system identity and score, and annotator ID/provenance/timestamp are mandatory. AI output is never a human label. Image-observable tactile and review/text-supported tactile are separate endpoints and are not silently merged.

## 11. Cohorts and statistics

The all-official-user result is primary. The following are predeclared secondary/diagnostic cohorts:

- train history at least 1, 3, and 5;
- mutually exclusive tactile support 0, 1, 2, 3--4, and 5+;
- target train interaction count 0, at most 5, and at most 10;
- image available with target train count 0;
- target outside fixed v3 Last2-training families;
- target-in-candidate.

Every cohort reports its definition and support. Cold definitions use train counts only. No cutoff may be selected using test outcomes. `outside_v3_training_family` is supplementary unless its complete parent-family mapping and definition are present in the implementation lock.

Primary uncertainty is the paired user bootstrap described above. Rank movement reports improved, unchanged, worsened, entered Top-10, and left Top-10. Qualitative examples are selected deterministically as largest gains, median-nearest changes, and largest losses with UID tie-breaking; manual success-only cherry-picking is forbidden.

## 12. Input integrity and prohibited reuse

All external input access is allowlist-based. `configs/protocol.json` contains known expected hashes and paths whose hashes must be materialized in `artifacts/input_manifest.json` before the implementation lock. Any missing required hash, unexpected file, hash mismatch, writable hard link, or unmanifested path is a hard failure.

Large immutable features may be referenced by absolute resolved path with `mmap_mode='r'`; they are not copied or hard-linked. Generated Experiment 20 outputs are written only below this experiment directory using temporary-file-plus-atomic-replace semantics.

Allowed reuse includes fixed raw/processed identity data, frozen Last2 checkpoint and full-catalog probabilities, generic image/text features and graphs, fixed v3 masks/family split for exploratory RQ3, and optionally pre-existing validated review evidence as a separately labelled exploratory modality.

Forbidden development or selection inputs include every Experiment 16 test metric, per-user test result, mixed `candidate_recall.csv`, qualitative test example, cold-start test result, test candidate chunk, test no-history rank, test-derived selection summary, and all Experiment 14/19 test results. Experiment 16 trained recommender checkpoints may be used only as post-completion audit references; they are not initializers or substitutes for the five freshly trained Experiment 20 variants.

The official test target itself is conditionally allowed only after `validation_locked_before_exp20_test`. Reading it earlier invalidates Track A.

## 13. Reporting language

The reused-official-test track must use “post-hoc exploratory,” “SMORE-derived scalable adaptation,” and “fixed Last2 tactile modality.” It must not say “fresh test,” “confirmatory,” “official SMORE reproduction,” or “tactile preference proven from history.”

The confirmatory label is allowed only for the independent human or future-temporal track after every corresponding state-machine guard passes. A null, negative, alpha-zero, low-recall, or blocked result is reported unchanged.

