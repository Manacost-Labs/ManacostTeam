# Semantic Audit Record Template

Use one record for each decision-relevant Claim → Evidence link reviewed by the Research Auditor.

```yaml
semantic_audit_id: SEM-0001
claim_id: CLM-0001
evidence_id: EVD-0001
source_id: SRC-0001

semantic_support: exact | partial | none | contradicted
scope_match: true | false
authority_match: true | false
freshness_match: true | false
evidence_type_match: true | false

reviewer_status: pass | warning | fail
reviewer_basis:
audited_at:
```

`exact` means the evidence supports the claim as written. `partial` requires narrowing or explicit conditions. `none` and `contradicted` cannot pass. Schema 1.1 final validation requires every critical claim to have at least one exact, fully matched, passing semantic audit; material claims may pass with a scoped partial warning.
