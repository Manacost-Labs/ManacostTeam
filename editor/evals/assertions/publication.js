module.exports = (output, context) => {
  const meta = context.providerResponse?.metadata || {};
  const h = context.vars?.research_handoff;
  const required = new Set((h?.chapters || []).flatMap(c => c.required_claim_ids || []));
  const rows = meta.fact_review?.claims || [];
  const seen = new Set();
  const pass = meta.accepted === true && meta.checks_complete === true && required.size > 0 && rows.length === required.size && rows.every(row => {
    if (seen.has(row.claim_id) || !required.has(row.claim_id) || row.status !== 'supported' || !row.action_quote || !output.includes(row.action_quote)) return false;
    seen.add(row.claim_id);
    const claim = h.claims.find(c => c.claim_id === row.claim_id);
    return ['condition', 'exception'].every(field => !claim[field] || (row[`${field}_quote`] && output.includes(row[`${field}_quote`]))) &&
      row.evidence_refs?.length > 0 && row.evidence_refs.every(ref => {
        const source = h.sources?.find(source => source.source_id === ref);
        return claim.evidence_refs.includes(ref) && source?.url && output.includes(source.url);
      });
  });
  return { pass, score: pass ? 1 : 0, reason: pass ? 'Required advice and quoted conditions verified' : 'Incomplete factual review or rejected output' };
};
