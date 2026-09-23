# Tactile Execution Plan

Status values are updated only after implementation, tests, observation, and fixes complete.

## M0 Repository Audit — complete

- Goal: map frameworks, data, APIs, tests, runtime, and establish a passing baseline.
- Files likely affected: `AGENTS.md`, `docs/tactile/*`.
- Implementation: audited repository/data schemas; recorded architecture and safety rules.
- Tests: 41 baseline unit tests, Python compileall, live API health.
- Validation commands: see `REPO_AUDIT.md`.
- Done when: audit and required design documents exist and baseline is reproducible.
- Known risks: no dependency lock; directory is not a Git worktree.
- Status: complete.

## M1 Data Contract — complete

- Goal: typed claim/evidence/profile/intent/candidate contracts and conservative normalization.
- Files likely affected: `tactile_models.py`, `tactile_normalization.py`, tests.
- Implementation: dataclasses, validation, public serialization, concept polarity handling.
- Tests: schema, negation, unknown phrase, malformed input.
- Validation commands: recommendation API unit suite and compileall.
- Done when: contract tests pass and raw evidence remains traceable.
- Known risks: lexical ambiguity such as “light” requires context safeguards.
- Status: complete. Five new contract/normalization tests pass; recommendation suite 11/11.

## M2 Common Tactile Backend — complete

- Goal: validated 495-product startup cache and profile API.
- Files likely affected: `tactile_store.py`, `server.py`, config, tests.
- Implementation: artifact validation, profile assembly, feature flags, health/stats.
- Tests: data mismatch, unknown product, empty state, API integration.
- Validation commands: unit/integration tests and live smoke.
- Done when: profile is cached, grounded, and available over HTTP.
- Known risks: five source products have no accepted target.
- Status: complete. Six backend/API tests pass; recommendation suite 17/17.

## M3 Product Tactile Description — complete

- Goal: user-facing evidence-grounded summaries and empty states.
- Files likely affected: service, routes, static UI, tests.
- Implementation: reviewer-aware aggregation, confidence/agreement wording, evidence drawer.
- Tests: one reviewer, contradiction, no evidence, source labels.
- Validation commands: unit/API/UI smoke.
- Done when: summary and exact review evidence are accessible.
- Known risks: pseudo-labels are not independent human gold.
- Status: complete. Six service tests plus grounded HTTP integration pass; real catalog has 495
  available and five explicit empty states.

## M4 Tactile Comparison — complete

- Goal: compare two or more profiles without inventing missing dimensions.
- Files likely affected: service, routes, static UI, tests.
- Implementation: common/different/conflicting/insufficient dimensions.
- Tests: missing evidence, category mismatch display, evidence links.
- Validation commands: unit/API/UI smoke.
- Done when: supported differences are traceable and unsupported axes say insufficient evidence.
- Known risks: open-vocabulary grouping precision.
- Status: complete. Six service tests and POST API integration pass for 2–20 products.

## M5 Concern Detection — complete

- Goal: precision-oriented repeated negative/contradictory tactile concern detection.
- Files likely affected: service, config, routes, static UI, tests.
- Implementation: configurable reviewer support, negativity, confidence, agreement and metadata.
- Tests: false-alert, one reviewer, contradictory evidence, verified purchase.
- Validation commands: unit/API/UI smoke.
- Done when: every concern is independently supported and alternatives action is linked.
- Known risks: current evidence artifact may lack some review metadata fields.
- Status: complete. Eight precision-oriented tests and grounded HTTP integration pass; 42 catalog
  products have 48 qualifying concerns.

## M6 Alternative Recommendation — complete

- Goal: same-category alternatives for a current explicit tactile change.
- Files likely affected: service, config, routes, static UI, tests.
- Implementation: anchor preservation, directional improvement, confidence, constraints, MMR.
- Tests: less scratchy fixture, missing anchor concept, no results, category mismatch.
- Validation commands: ranking tests and API smoke.
- Done when: results include full score breakdown and grounded reason.
- Historical risk resolved by D008: all 465 visible product families now have aligned FashionCLIP
  vectors; human design-relevance labels are still unavailable.
- Status: complete. Directional, same-category, evidence and score-breakdown tests plus POST API
  integration pass.

## M7 Base Recommendation / Tactile Ranking — complete

- Goal: baseline/global/category/context strategies behind explicit configuration.
- Files likely affected: service, config, route, offline evaluation, tests.
- Implementation: TactileNeedGate, normalized scores, conflict penalty, MMR.
- Tests: gate strengths, cross-category near-zero, score breakdown, deterministic order.
- Validation commands: unit/API and ablation run.
- Done when: baseline is preserved and strategies are directly comparable.
- Known risks: target coverage in full interaction universe is limited.
- Status: complete. Four strategies, context gate, score breakdown, MMR and POST API pass. The
  quantitative identical-candidate ablation is executed in M10.

## M8 Agent — complete

- Goal: natural-language interface over typed intent and real retrieval.
- Files likely affected: service, route, tests.
- Implementation: deterministic parser, explicit session state, follow-up updates, grounded results.
- Tests: intent, context update, unknown category clarification, no invented ASIN.
- Validation commands: unit/API conversation fixtures.
- Done when: agent output contains only actual catalog results.
- Known risks: rule parser supports bounded Korean/English expressions.
- Status: complete. Six intent/agent tests and HTTP integration pass; all returned IDs are checked
  against the real catalog.

## M9 Frontend E2E Integration — complete

- Goal: coherent product → description/concern → compare/alternative → agent demo.
- Files likely affected: `recommendation_api/static/*`, server routing.
- Implementation: accessible dependency-free UI with evidence dialogs and empty/error states.
- Tests: static route/API integration and JavaScript syntax when available.
- Validation commands: live service smoke and endpoint flow script.
- Done when: all five demo flows work from the UI.
- Known risks: no browser automation framework currently exists.
- Status: complete. Static/API integration passes and the restarted local systemd service serves
  `/tactile-demo` with live 495-profile health.

## M10 Offline Evaluation — complete

- Goal: run recommendation ablations and feature-level deterministic evaluations.
- Files likely affected: `offline_eval/*`, results, report, tests.
- Implementation: identical candidates, context gates, directional and faithfulness metrics.
- Tests: evaluator unit tests and result schema checks.
- Validation commands: evaluation CLI and manifest/hash inspection.
- Done when: JSON/Markdown results exist and limitations are explicit.
- Known risks: non-time-aware tactile targets make recommendation results diagnostic.
- Status: complete. Four identical-candidate strategies ran on 332 temporal cases; feature-level
  metrics and predictions are stored under `data/recommendation_eval/tactile_v1`.

## M11 Full Regression / Bug Fix — complete

- Goal: verify all old/new features, restart local service safely, and finalize documentation.
- Files likely affected: README, API README, docs and fixes discovered by regression.
- Implementation: full suites, compile, live endpoint and demo-flow smoke, final report.
- Tests: every suite and endpoint contract.
- Validation commands: documented final command matrix.
- Done when: no known failing tests and Discord completion messages were delivered per milestone.
- Known risks: local systemd may require restart to load source changes.
- Status: complete. All 94 automated tests, compilation, config/artifact checks, local service
  restart, and live HTTP demo flows pass. Final/API/Notion documentation is current.
