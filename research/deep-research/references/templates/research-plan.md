# Research Plan Template

```yaml
research_id:
created_at:
as_of:
main_question:
intended_use:
research_type: []
domain_adapters: []
depth: quick | deep | exhaustive
modifiers: []
output_profile: editor-ready | research-report | raw-research
coverage_contract_version: "1.0" # editor-ready only; omit for other profiles

scope:
  included: []
  excluded: []
  geography:
  population:
  mode_or_platform:
  current_version:
  patch:
  season:
  time_window:
  terminology: {}

success_criteria: []
material_decisions: []
known_constraints: []

deliverable_outline:
  - section_id: SEC-0001
    working_title:
    reader_question:
    decision_or_claim:
    evidence_needed: []
    preferred_source_channels: []
    freshness_constraint:
    readiness_condition:
    status: planned
    coverage_note:

source_emphasis:
  x: standard | high
  youtube: standard | high
  rationale:

operations:
  persistent_run: true | false
  run_directory:
  downstream_consumer:
  delivery_status_target: ready | ready_with_warnings | not_ready
```

## Research tree

```text
MAIN QUESTION
├── Branch A
│   ├── Leaf A1
│   └── Leaf A2
└── Branch B
    ├── Sub-branch B1
    │   ├── Leaf B1a
    │   └── Leaf B1b
    └── Leaf B2
```

## Leaf register

| Leaf ID | Question / candidate claim | Why it matters | Evidence needed | Preferred source class | Freshness/version constraint | Status |
|---|---|---|---|---|---|---|
| Q-001 |  |  |  |  |  | planned |

For a guide or article, every decision-relevant `deliverable_outline` section must map to one or more leaf IDs. Before the first search, present a short plain-language version of the outline to the user and continue automatically unless they requested an approval checkpoint.

For a new persistent `editor-ready` run, keep these sections in `plan.json` under `coverage_contract_version: "1.0"`. Omit the coverage field and `plan.json` for other output profiles. Use stable zero-padded IDs such as `SEC-0001`; never renumber them when titles change. Allowed section statuses are `planned`, `researching`, `covered`, `excluded`, and `unresolved`. A final plan may contain only `covered`, `excluded`, or `unresolved`, and the latter two require `coverage_note`. Mark a section `covered` only when it has at least one linked query, retained evidence/claim/community material, and a claim with status `supported`, `supported_with_conditions`, or `contested` routed to `main`.

## Risk hypotheses

- Expected ambiguity:
- Likely confounders:
- Likely source dependencies:
- Preliminary belief to avoid anchoring on:
- Evidence that could reverse the answer:
