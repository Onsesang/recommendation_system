# FabricVST tactile pseudo-label prompt (v1)

Frozen prompt used to relabel raw clothing reviews against the FabricVST
semantic attribute vocabulary. Any edit requires a new version file; the version
string is recorded in every output row.

- version: `fabricvst_tactile_pseudolabel_v1`
- model: `Qwen/Qwen3-VL-32B-Instruct`, revision `0cfaf48183f594c314753d30a4c4974bc75f3ccb`
- decoding: greedy, `do_sample=false` (the deterministic setting this model exposes)
- input: raw review text only, no product title, no category, no image

## Attribute vocabulary

Exactly the 24 FabricVST attributes, in dataset order and dataset spelling:

```
stiff, soft, rough, smooth, thick, thin, cool, warm, fluffy, heavy,
delicate, durable, stretchable, absorbent, holey, flat, bumpy,
patterned, striped, shinny, hairy, embroidered, jacquard, pigment printed
```

Dataset-supplied glosses, included verbatim in the prompt:

- `absorbent` - Absorbent material soaks up liquid easily
- `embroidered` - the design is stitched into the fabric after weaving, by machine
- `jacquard` - the design is incorporated into the weave, woven with different colours of yarn
- `pigment printed` - the pattern is printed onto the fabric after it is finished

## System instruction

```
You are annotating tactile and physical properties explicitly supported by a clothing review.

Do not infer properties only from the product category.

For every FabricVST attribute, return positive, negative, or unknown.

Use unknown whenever the review does not contain enough evidence.

Multiple attributes may be positive simultaneously.

These labels are multi-label attributes, not mutually exclusive classes.
```

## Task instruction

```
Read the REVIEW and decide, for each attribute you can justify, whether the review
gives evidence that the garment's material HAS the property (positive) or does NOT
have it (negative).

Rules:
- Judge the material or fabric of the garment, not the fit, the sizing, the price,
  the delivery, the colour preference, or the wearer's mood.
- Report an attribute only when the review contains explicit or strongly implied
  linguistic evidence for it. Silence is not evidence.
- Never infer an attribute from the product type alone. "It is denim" is not
  evidence for stiff. "It is a sweater" is not evidence for warm. "It is silk" is
  not evidence for smooth. Only the reviewer's own description counts.
- Negation gives a negative label: "not scratchy at all" is rough=negative.
  A negated property does NOT license its opposite: "not soft" is soft=negative
  and says nothing about stiff.
- Comparative or hedged statements ("a little thin", "thinner than expected")
  still count as evidence; reflect the uncertainty in the confidence value.
- Omit every attribute you cannot justify. Omitted attributes are treated as
  unknown. Do not pad the output with guesses.
- evidence must be copied character for character from the REVIEW below, at most
  120 characters. Never copy evidence text out of these instructions.

Return only compact JSON, no prose, no markdown fence. Output shape only:
{"a":[["ATTRIBUTE","p",0.0,"EXACT QUOTE FROM THE REVIEW"]]}

Each entry is [attribute, polarity, confidence, evidence].
polarity is "p" for positive or "n" for negative.
confidence is a number between 0 and 1.
Return {"a":[]} when the review supports no attribute at all.
```

## Output contract

One JSONL row per review:

```json
{
  "review_id": "...",
  "asin": "...",
  "prompt_version": "fabricvst_tactile_pseudolabel_v1",
  "attributes": {
    "soft": {"label": "positive", "confidence": 0.93, "evidence": "very soft against the skin"},
    "rough": {"label": "negative", "confidence": 0.88, "evidence": "not scratchy at all"}
  },
  "unmapped": false,
  "parse_error": null
}
```

Attributes absent from `attributes` are `unknown` with null confidence and null
evidence. `unknown` never contributes to the training loss.
