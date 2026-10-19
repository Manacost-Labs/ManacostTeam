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

const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const blind = require('../blind_review.js');

function workspace() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'publication-review-'));
  const input = path.join(dir, 'input.json');
  fs.writeFileSync(input, JSON.stringify({results: ['baseline', 'candidate'].map(label => ({
    vars: {id: 'case', text: 'Исходник'}, prompt: {label}, response: {output: label === 'baseline' ? 'Первый текст' : 'Второй текст'},
  }))}));
  return {dir, input, out: path.join(dir, 'blind')};
}

test('blind review pending templates never become ties or measurements', () => {
  const {input, out} = workspace();
  blind.prepare(input, out, () => 0, {swapOrder: true});
  const rows = JSON.parse(fs.readFileSync(path.join(out, 'ratings.template.json')));
  assert.equal(rows.length, 2);
  assert.equal(rows[0].review_status, 'pending');
  const result = blind.importRatings(path.join(out, 'ratings.template.json'), path.join(out, 'key.json'), out);
  assert.equal(result.rated, 0);
  assert.deepEqual(result.preferences, {});
  assert.equal(result.human_review_status, 'pending');
  assert.throws(() => blind.prepare(input, out), /exists/);
});

test('blind review preserves swapped disagreements and rejects fabricated attestations', () => {
  const {input, out} = workspace();
  blind.prepare(input, out, () => 0, {swapOrder: true});
  const rows = JSON.parse(fs.readFileSync(path.join(out, 'ratings.template.json')));
  for (const row of rows) {
    row.review_status = 'reviewed'; row.reviewer = 'Human test reviewer'; row.reviewed_at = '2026-10-19T12:00:00Z';
    row.preferred = 'A'; row.comment = 'Конкретное сравнение';
    row.evidence = ['Сохранено условие'];
    for (const side of ['A', 'B']) for (const c of blind.CRITERIA) row[side][c] = 4;
  }
  const file = path.join(out, 'ratings.json');
  fs.writeFileSync(file, JSON.stringify(rows));
  const result = blind.importRatings(file, path.join(out, 'key.json'), out);
  assert.equal(result.rated, 2);
  assert.deepEqual(result.preferences, {baseline: 1, candidate: 1});
  assert.equal(result.disagreements[0].case_id, 'case');
  assert.equal(result.observations[0].evidence[0], 'Сохранено условие');
  assert.equal(result.quality_improvement_confirmed, false);
  rows[0].reviewer = '';
  fs.writeFileSync(file, JSON.stringify(rows));
  assert.throws(() => blind.importRatings(file, path.join(out, 'key.json'), out), /reviewer/);
});

test('publication modes do not collapse into a single retrieval label', () => {
  const results = ['edit', 'reconstruct'].map(mode => ({vars: {id: 'same', text: 'Исходник'}, response: {output: mode, metadata: {prompt_version: 'candidate', editorial_mode: mode, retrieval_variant: 'no-retrieval'}}}));
  assert.equal(blind.pairUp(results).length, 1);
});

test('pipeline evaluation records measured duration and only supplied resource counts', async () => {
  const Provider = require('../providers/pipeline-e2e.js');
  const oldFetch = global.fetch;
  const previous = process.env.EDITOR_EVAL_CANDIDATE_GATEWAY_URL;
  process.env.EDITOR_EVAL_CANDIDATE_GATEWAY_URL = 'http://test.invalid';
  global.fetch = async url => new Response(JSON.stringify(String(url).endsWith('/health')
    ? {checks_complete: true}
    : {text: 'Готово.', accepted: true, checks_complete: true, prompt_variant: 'candidate', usage: {total_tokens: 123}, attempts: 2}));
  try {
    const prompt = fs.readFileSync(path.join(__dirname, '../prompts/candidate.txt'), 'utf8');
    const result = await new Provider({config: {retrieval: 'off'}}).callApi(prompt, {vars: {text: 'Готово.'}});
    assert.equal(result.metadata.resource_usage.tokens, 123);
    assert.equal(result.metadata.resource_usage.cost_usd, null);
    assert.ok(result.metadata.resource_usage.elapsed_seconds >= 0);
  } finally {
    global.fetch = oldFetch;
    if (previous === undefined) delete process.env.EDITOR_EVAL_CANDIDATE_GATEWAY_URL;
    else process.env.EDITOR_EVAL_CANDIDATE_GATEWAY_URL = previous;
  }
});

test('blind pairs reject differing inputs and duplicate variants', () => {
  const results = ['baseline', 'candidate'].map(label => ({vars: {id: 'same', text: 'Исходник'}, prompt: {label}, response: {output: 'Текст'}}));
  assert.throws(() => blind.pairUp([...results, results[0]]), /duplicate/);
  results[1].vars.text = 'Другой исходник';
  assert.throws(() => blind.pairUp(results), /inputs/);
});

test('frozen development pilot exercises controls and keeps human state pending', () => {
  const cases = require('../cases/research-editor-pilot.js')();
  assert.equal(cases.length, 10);
  assert.ok(cases.every(row => row.vars.synthetic === true && row.vars.split === 'development'));
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'research-editor-pilot-'));
  const out = path.join(dir, 'run');
  const result = require('../RESEARCH_EDITOR_PILOT.js').run(out);
  assert.equal(result.unchanged_pass, 10);
  assert.equal(result.number_damage_rejected, 10);
  assert.equal(result.human_rated, 0);
  assert.equal(result.live_model_report.status, 'real model evaluation not executed');
  assert.throws(() => require('../RESEARCH_EDITOR_PILOT.js').run(out), /exists/);
});

test('publication report separates gateway versions and keeps unavailable costs unknown', () => {
  const rows = ['candidate', 'baseline'].map(label => ({vars: {id: 'one', text: 'Текст'}, response: {output: 'Текст', metadata: {
    editorial_mode: 'edit', prompt_version: label, retrieval_variant: 'no-retrieval',
    resource_usage: {tokens: label === 'candidate' ? 200 : null, cost_usd: null, elapsed_seconds: 1},
  }}}));
  const result = require('../report.js').summarize(rows);
  assert.equal(result.pairs.complete, 1);
  assert.equal(result.pairs.candidate, 'candidate:edit:no-retrieval');
  assert.equal(result.pairs.baseline, 'baseline:edit:no-retrieval');
  assert.equal(result.variants['candidate:edit:no-retrieval'].resource_usage.tokens.total, 200);
  assert.equal(result.variants['baseline:edit:no-retrieval'].resource_usage.tokens.total, null);
  assert.equal(result.quality_improvement_confirmed, false);
});
