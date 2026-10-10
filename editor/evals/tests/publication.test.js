const assert = require('node:assert/strict');
const test = require('node:test');
const check = require('../assertions/publication.js');

const h = { chapters: [{ required_claim_ids: ['C'] }], sources: [{source_id: 'S', url: 'https://example.org/guide'}], claims: [{ claim_id: 'C', condition: 'при условии', exception: 'кроме исключения', evidence_refs: ['S'] }] };
const row = { claim_id: 'C', status: 'supported', action_quote: 'Совет', condition_quote: 'при условии', exception_quote: 'кроме исключения', evidence_refs: ['S'] };
function context(rows) { return { vars: {research_handoff: h}, providerResponse: {metadata: {accepted: true, checks_complete: true, fact_review: {claims: rows}}} }; }
test('publication assertion rejects dropped conditions and duplicate attestations', () => {
  const candidate = 'Совет при условии кроме исключения https://example.org/guide';
  assert.equal(check(candidate, context([row])).pass, true);
  assert.equal(check('Совет', context([row])).pass, false);
  assert.equal(check('Совет при условии кроме исключения', context([row])).pass, false);
  assert.equal(check(candidate, context([row, row])).pass, false);
  assert.equal(check(candidate, context([{...row, evidence_refs: ['wrong']}])).pass, false);
});

test('publication corpus loader does not infer gold from published articles', () => {
  const saved = process.env.EDITOR_EVAL_PUBLICATION_CASES;
  delete process.env.EDITOR_EVAL_PUBLICATION_CASES;
  try { assert.throws(() => require('../cases/publication.js')(), /required/); }
  finally { if (saved !== undefined) process.env.EDITOR_EVAL_PUBLICATION_CASES = saved; }
});
