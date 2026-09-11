# Claim Record Template

```yaml
claim_id:
claim:
claim_class: official_fact | statistical | strategic | causal | prevalence | superlative | forecast | interpretation
importance: critical | material | supporting | contextual
deliverable_section_ids: [SEC-0001]
output_disposition: main | useful_data | appendix | omit
output_omit_reason:
useful_data_types: []

scope:
  population:
  geography:
  mode_or_platform:
  time_window:
  version_patch_season:
  conditions: []

evidence_required: []
supporting_evidence_ids: []
challenging_evidence_ids: []
challenge_search:
  query_ids: []
  result: none_found | found_weak | found
source_lineages: []

status: supported | supported_with_conditions | contested | unsupported | unresolved | rejected
confidence: VERY_HIGH | HIGH | MEDIUM | LOW | SPECULATIVE
confidence_reason:

inference_steps: []
exceptions: []
unknowns: []
wording_for_output:
```

If one field contains two independently falsifiable assertions, split the record.

`challenge_search` records the contradiction-pass queries that looked for disconfirming evidence when none was found or the found evidence was weak. In schema 1.2 a critical claim cannot pass final validation without either challenging evidence or this record.

The coverage fields apply only when `manifest.json` enables `coverage_contract_version: "1.0"`. A rejected claim routes to `omit` with a reason. Every non-rejected critical or material claim routes to `main`. `useful_data` requires one or more of `number`, `comparison`, `advice`, `sequence`, `example`, `mistake`, `exception`, `deck_code`, `x_insight`, or `youtube_segment`.
