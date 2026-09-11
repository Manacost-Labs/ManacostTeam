# Community Consensus Template

```yaml
community_claim_id:
community_claim:
claim_ids: []
deliverable_section_ids: [SEC-0001]
output_disposition: main | useful_data | appendix | omit
output_omit_reason:
useful_data_types: []
scope:
  platforms: []
  date_range:
  version_patch_season:
  population_or_rank:

supporting_threads: []
supporting_evidence_ids: []
independent_mentions:
lineages: []

expert_support: []
counterarguments: []
minority_positions: []

consensus_strength: strong | moderate | contested | weak | anecdotal
sampling_limitations: []
confidence:
bounded_output_wording:
```

## Position map

| Position | Platforms | Independent origins | Expertise signals | Main reasoning | Counterevidence | Version relevance |
|---|---|---:|---|---|---|---|
|  |  |  |  |  |  |  |

Do not convert independent-mention counts into population percentages unless the collection design supports it.

The coverage fields apply only when `manifest.json` enables `coverage_contract_version: "1.0"`. `omit` requires a reason. `useful_data` requires one or more of `number`, `comparison`, `advice`, `sequence`, `example`, `mistake`, `exception`, `deck_code`, `x_insight`, or `youtube_segment`.
