# Explicit tactile preference — exploratory experiment 19

Human audit is **skipped by user, not completed**. AI labels are not gold.
This directory is separate from experiments 12–18. Raw data, original models,
and human annotation templates are not changed.

Stages: frozen full-cohort lexical occurrences → Qwen32B NF4 extraction →
anchored-quote validation and two formatting retries → temporal/category-local
profiles → validation-only candidate/weight selection → exploratory test,
review/image ablations, paired bootstrap, future-review pseudo consistency →
Notion Markdown and GPT handoff.

The scope is all official lexical reviews of the existing recommendation
evaluation users, not all Amazon reviews submitted to Qwen. Original full-corpus
feasibility remains in experiment 17. Conditional and garment-part preferences
remain as evidence but do not enter the unconditional primary score.

Use the texture environment. `PREFERENCE_BATCH_SIZE` is an operational batch
override; it does not change inclusion rules, prompts, or ranking settings.
Extraction appends checkpointed complete batches and resumes by occurrence ID.
Do not launch overlapping inference writers. Failed schema/quote output is
retained and never converted into a guessed valid label.

See `notion/EXPLICIT_PREFERENCE_EXPLORATORY_RESULTS.md` after completion.
