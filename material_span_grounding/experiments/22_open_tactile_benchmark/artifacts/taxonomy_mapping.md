# Exp22 Taxonomy Mapping (frozen)

Frozen 2026-09-17, before any model in this experiment was scored.
Inherited verbatim from `experiments/21_fabricvst_external/config.json` -> `mapping`;
nothing here was re-derived after seeing a result.

**Policy.** The main comparison uses EXACT mappings only. APPROXIMATE mappings appear
in supplementary sensitivity analysis. UNAVAILABLE attributes are never silently
approximated to make a model look comparable.

EXACT 8 / APPROXIMATE 2 / UNAVAILABLE 18

## Main comparison set (EXACT, 8 attributes)

| attribute | last2 | FabricVST A/B | CLIP family | VLM | note |
|---|---|---|---|---|---|
| `soft` | `soft` | `soft` | paired text prompt | YES/NO logit | Surface form identical in both taxonomies; both denote yielding to pressure. |
| `rough` | `rough` | `rough` | paired text prompt | YES/NO logit | Identical surface form and gloss (coarse / scratchy surface). |
| `smooth` | `smooth` | `smooth` | paired text prompt | YES/NO logit | Identical surface form and gloss (even, slick surface). |
| `thick` | `thick` | `thick` | paired text prompt | YES/NO logit | Identical surface form; both denote fabric substance / gauge. |
| `thin` | `thin` | `thin` | paired text prompt | YES/NO logit | Identical surface form; both denote low fabric substance / gauge. |
| `cool` | `cool` | `cool` | paired text prompt | YES/NO logit | Identical surface form; both denote cool thermal feel on contact. |
| `warm` | `warm` | `warm` | paired text prompt | YES/NO logit | Identical surface form; both denote warm / insulating thermal feel. |
| `stiff` | `stiff` | `stiff` | paired text prompt | YES/NO logit | Identical surface form, both denote resistance to bending. Caveat carried over from exp21: last2 treats stiff as the antonym of flexible, FabricVST lists it opposite soft. Recorded EXACT, flagged in the report. |

## APPROXIMATE (supplementary only)

| FabricVST | last2 | note |
|---|---|---|
| `stretchable` | `elastic` | elastic implies recovery after extension, stretchable implies extensibility; related but not identical, hence approximate. |
| `fluffy` | `spongy` | spongy denotes compressibility, fluffy denotes light raised-fibre loft; related but not identical, hence approximate. |

## UNAVAILABLE

FabricVST attributes with no last2 counterpart (14): `heavy`, `delicate`, `durable`, `absorbent`, `holey`, `flat`, `bumpy`, `patterned`, `striped`, `shinny`, `hairy`, `embroidered`, `jacquard`, `pigment printed`

last2 classes with no FabricVST counterpart (4): `firm`, `non_elastic`, `flexible`, `crisp`

Deliberate non-mappings carried over from exp21:

- `firm` is **not** mapped to FabricVST `stiff`: in last2, `firm` is the antonym of `soft`, a different axis from `stiff`/`flexible`.
- `flexible` is **not** mapped to `stretchable`: bending compliance is not extensibility.
