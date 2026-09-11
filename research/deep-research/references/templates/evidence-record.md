# Evidence Record Template

```yaml
evidence_id:
source_id:
claim_ids: []
deliverable_section_ids: [SEC-0001]
relationship: supports | challenges | contextualizes | mentions_only
output_disposition: main | useful_data | appendix | omit
output_omit_reason:
useful_data_types: []

locator:
  page:
  section:
  table_or_figure:
  paragraph_or_anchor:
  media_timestamp:

exact_excerpt:
faithful_paraphrase:
source_statement_or_researcher_inference: source_statement | researcher_inference

evidence_type: fact | statistic | observation | opinion | speculation
directness: direct | indirect

metric:
unit:
numerator:
denominator:
sample_size:
population_or_rank:
filters: []
data_timeframe:
version_patch_season:
uncertainty_or_variance:
selection_bias_notes:

scope_limitations: []
alternative_interpretations: []
quality_notes:
```

Leave irrelevant statistical fields blank. Do not infer a missing denominator or sample size.

In schema 1.2, `exact_excerpt` is the verifiable anchor: at least four words copied verbatim from the inspected source. The validator looks for it in the source snapshot and rejects the evidence when it is absent; at final stage every supporting evidence item of a critical or material claim with a snapshotted source must carry one. Keep excerpts short and within the web-safety limits.

The coverage fields apply only when `manifest.json` enables `coverage_contract_version: "1.0"`. `omit` requires `output_omit_reason`. `useful_data` requires one or more of `number`, `comparison`, `advice`, `sequence`, `example`, `mistake`, `exception`, `deck_code`, `x_insight`, or `youtube_segment`.
