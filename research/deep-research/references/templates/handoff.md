# Research Handoff Template

```yaml
research_id:
delivery_status: ready | ready_with_warnings | not_ready
main_question:
as_of:
current_context:
output_profile: editor-ready | research-report | raw-research
audit_status:
clarity_preservation: pass | fail | not_applicable
coverage_preservation: pass | fail | not_applicable
bundle_validation: pass | fail
useful_data:
  status: complete | partial | not_applicable
  file:
  item_count:
  uncovered_section_ids: []
```

## What is delivered

- Files:
- Main document:
- Useful-data bank:
- Evidence appendix, if any:
- Research depth, output profile, and modifiers:
- Covered branches:
- Excluded scope:

## Section to useful-material map

Complete this map for every `deep` or `exhaustive` editor-ready handoff. Use one row per deliverable section, including sections with no usable material so gaps remain visible.

| Section ID and title | Useful item IDs and types | Output disposition | Claim / evidence / direct source links | Gaps or limits |
|---|---|---|---|---|
| SEC-0001 —  | UDT-0001 — number | useful_data | CLM- / EVD- / [source](https://example.com) |  |

## Decisive findings

For each: claim ID, bounded wording, confidence, conditions, and decisive evidence IDs.

## Warnings and unknowns

- Decision-critical gaps:
- Access limitations:
- Freshness/version risks:
- Contested claims:

## Instructions for downstream Writer or Editor

- Claims that may be stated directly:
- Claims that require qualification:
- Claims that must not be used:
- Terms, patch/version, and audience constraints to preserve:
- Citations that must remain attached to specific claims:
- Useful-data items the writer should consider for each section:

## Validation evidence

- Research Auditor status:
- Bundle validator result:
- Weakest decision-critical claim:
- Useful-data coverage: complete | partial | not_applicable
- Coverage preservation: pass | fail | not_applicable

Use `coverage_preservation: pass` only for a coverage-enabled `editor-ready` final whose `audit.json.coverage_review` passed against the frozen manifest, plan, all eight JSONL ledgers, report, every required/routed/present bank, and applicable appendix. Use `not_applicable` for legacy bundles and other output profiles.
