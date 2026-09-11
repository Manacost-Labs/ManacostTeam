# Query Plan Template

## Query set

```yaml
leaf_id:
concept:
official_terms: []
community_terms: []
synonyms: []
localized_terms: []
english_terms: []
entities: []
version_markers: []
deliverable_section_ids: [SEC-0001]
source_emphasis:
  x: standard | high
  youtube: standard | high
```

| Query ID | Leaf | Pass | Family | Query | Expected source class | Result / gap |
|---|---|---|---|---|---|---|
| QRY-001 | Q-001 | discovery | primary |  | official |  |

Families: `general`, `primary`, `statistics`, `experts`, `reddit-forums`, `x-social`, `youtube`, `mistakes`, `synergies`, `counterargument`, `freshness`.

When X or YouTube emphasis is `high`, create distinct section-level query rows instead of repeating one generic topic query. Record which section each result can inform; a large provider result set does not count as broad guide coverage when it belongs to only one section.

In a coverage-enabled editor-ready bundle, every persisted query record has a non-empty `deliverable_section_ids` list containing only IDs declared in `plan.json`.

## Pass checkpoint

```yaml
pass:
what_we_know: []
what_we_think: []
what_is_contested: []
what_we_dont_know: []
what_needs_more_evidence: []
next_queries: []
saturated_branches: []
unsaturated_branches: []
```
