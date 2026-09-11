# Confidence System

## Claim-level labels

- `VERY HIGH`: direct high-authority evidence; correct scope/version; no material unresolved contradiction; independence sufficient for the claim type.
- `HIGH`: strong appropriate evidence and corroboration; minor limitations do not threaten the conclusion.
- `MEDIUM`: useful but incomplete evidence, limited independence, moderate version/method uncertainty, or meaningful conditions.
- `LOW`: sparse, indirect, weakly matched, stale-risk, or materially contested evidence.
- `SPECULATIVE`: hypothesis or interpretation without adequate verification.

Use `UNRESOLVED` as a claim status, not a confidence label, when competing evidence cannot be reconciled.

## Assessment dimensions

Evaluate:

- authority for this claim type;
- directness and semantic support;
- source independence and lineage;
- evidence quantity only after quality and independence;
- freshness/version compatibility;
- statistical reliability and scope;
- contradiction strength;
- completeness of required source classes;
- degree of inference.

Do not calculate confidence as a simple average. A fatal flaw such as semantic mismatch, incompatible patch, or fabricated denominator overrides other strengths. One decisive official source can yield very high confidence for a narrow rule; one hundred weak comments cannot.

## Language calibration

| Confidence | Suitable language |
|---|---|
| very high | “establishes,” “is,” within explicit scope |
| high | “strong evidence indicates,” “is well supported” |
| medium | “available evidence suggests,” “likely under these conditions” |
| low | “limited evidence points to,” “cannot be concluded reliably” |
| speculative | “one hypothesis is,” “unverified” |

Strong language must also respect claim type. Observational data does not justify causal wording even at high confidence in the association.

## Report-level summary

Do not average claim labels into one opaque score. State confidence separately for main findings and call out the weakest decision-critical claim.

## Updating confidence

Reassess after contradiction search, freshness validation, and audit. Explain material changes, such as a downgrade caused by shared dataset lineage or an upgrade after locating current official rules.
