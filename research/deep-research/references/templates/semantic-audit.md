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

# Required by the strict editorial handoff compiler. These bind the review to
# the records actually inspected; recompute only after reviewing changes.
claim_sha256:
evidence_sha256:
source_sha256:
```

`exact` means the evidence supports the claim as written. `partial` requires narrowing or explicit conditions. `none` and `contradicted` cannot pass. Schema 1.1 final validation requires every critical claim to have at least one exact, fully matched, passing semantic audit; material claims may pass with a scoped partial warning.

The editorial handoff accepts only current exact/pass audits for transferred
claims. Get hashes with `python scripts/editorial_handoff.py RUN --review-digests`,
then inspect the claim, evidence and source before recording the verdict.
Hash generation does not verify support. A changed record invalidates the review.
