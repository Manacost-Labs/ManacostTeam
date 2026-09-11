# Audit Report Template

```yaml
audit_status: pass | pass_with_warnings | fail
audited_at:

critical_issues: []
warnings: []
claims_to_rewrite: []
claims_to_remove: []
additional_search_required: []

gate_results:
  claim_coverage:
  semantic_support:
  source_integrity:
  primary_source_coverage:
  independence:
  freshness_and_version:
  evidence_type_discipline:
  statistics_context:
  contradiction_search:
  confidence_and_wording:
  branch_coverage:
  saturation:
  citation_integrity:
  web_content_safety:
  persistent_bundle_integrity:

weakest_decision_critical_claim:
impact_on_main_answer:
bundle_validation: pass | fail | not_applicable
delivery_status: ready | ready_with_warnings | not_ready

clarity_review:
  status: pass | fail | not_run | not_applicable
  claims_preserved: true | false
  numbers_preserved: true | false
  scope_preserved: true | false
  citations_preserved: true | false
  limitations_preserved: true | false
  contradictions_preserved: true | false
  reviewed_at:
  reviewed_claim_ids: []
  report_sha256:
  claims_sha256:
  sources_sha256:

coverage_review:
  status: pass | fail | not_run | not_applicable
  sections_covered: true | false
  dispositions_preserved: true | false
  reviewed_at:
  reviewed_record_ids: []
  omitted_record_ids: []
  section_results:
    - section_id: SEC-0001
      status: covered | excluded | unresolved
      record_ids: []
      note:
  manifest_sha256:
  plan_sha256:
  queries_sha256:
  sources_sha256:
  evidence_sha256:
  claims_sha256:
  community_sha256:
  contradictions_sha256:
  checkpoints_sha256:
  semantic_audit_sha256:
  report_sha256:
  useful_data_sha256:
  appendix_sha256:
```

Auditor instruction: do not improve style; try to prove the research wrong.

Use `coverage_review` for coverage-enabled `editor-ready` bundles. At final, `reviewed_record_ids` accounts for every non-omitted evidence, claim, and community record; `omitted_record_ids` accounts for every `omit` record; and section results cover every stable plan section. Every covered section must include at least one `supported`, `supported_with_conditions`, or `contested` claim routed to `main`.

The review always freezes `manifest.json`, `plan.json`, all eight JSONL ledgers (`queries`, `sources`, `evidence`, `claims`, `community`, `contradictions`, `checkpoints`, and `semantic-audit`), and `report.md`. It also freezes `useful-data.md` whenever the bank is required, contains routed records, or is present even in a `quick` run; it freezes `evidence-appendix.md` whenever any record routes to `appendix`. Use `not_applicable` for legacy bundles and other profiles.
