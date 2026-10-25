const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { PassThrough } = require('node:stream');
const test = require('node:test');

const pairs = require('../pairs.js');
const blind = require('../blind_review.js');

const tmp = (prefix) => fs.mkdtempSync(path.join(os.tmpdir(), prefix));

function writePair(dir, id, meta = {}, files = {}) {
  const pairDir = path.join(dir, id);
  fs.mkdirSync(pairDir, { recursive: true });
  fs.writeFileSync(path.join(pairDir, 'draft.md'), files.draft ?? 'Черновик гайда.');
  fs.writeFileSync(path.join(pairDir, 'reference.md'), files.reference ?? 'Эталон владельца.');
  fs.writeFileSync(path.join(pairDir, 'meta.json'), JSON.stringify({ id, type: 'GUIDE', topic: 'тема', date: '2026-10-25', origin: 'owner', synthetic: false, ...meta }));
  return pairDir;
}

test('repository pairs pass the format validator and stubs are marked synthetic', () => {
  assert.deepEqual(pairs.validateAll(), {});
  const loaded = pairs.loadPairs();
  assert.ok(loaded.length >= 2);
  for (const pair of loaded.filter((p) => p.meta.id.startsWith('synthetic-'))) assert.equal(pair.meta.synthetic, true);
});

test('pair validator rejects broken metadata and texts', () => {
  const dir = tmp('pairs-invalid-');
  assert.deepEqual(pairs.validatePair(writePair(dir, 'good')), []);
  const cases = [
    [writePair(dir, 'bad-type', { type: 'NEWS' }), /meta.type/],
    [writePair(dir, 'bad-date', { date: '2026-02-30' }), /meta.date/],
    [writePair(dir, 'bad-id', { id: 'other' }), /directory name/],
    [writePair(dir, 'unmarked', { origin: 'synthetic', synthetic: true }), /synthetic- prefix|start with synthetic-/],
    [writePair(dir, 'synthetic-lie', { origin: 'owner', synthetic: false }), /synthetic- prefix/],
    [writePair(dir, 'typo', { topik: 'x' }), /not a known field/],
    [writePair(dir, 'same', {}, { draft: 'Текст', reference: 'Текст' }), /equals draft/],
    [writePair(dir, 'regression-owner', { regression: { must_not_contain: ['фраза'] } }), /owner-correction/],
  ];
  for (const [pairDir, pattern] of cases) assert.match(pairs.validatePair(pairDir).join('; '), pattern, pairDir);
  fs.writeFileSync(path.join(dir, 'good', 'meta.json'), '{');
  assert.match(pairs.validatePair(path.join(dir, 'good')).join(';'), /invalid JSON/);
  assert.throws(() => pairs.loadPairs(dir), /invalid pairs/);
});

test('owner correction becomes a regression pair and detects returning phrases', () => {
  const dir = tmp('pairs-case-');
  const result = pairs.createCase({ dir, id: 'mulligan-fix', type: 'GUIDE', topic: 'муллиган', date: '2026-10-25',
    source: 'Исходник.', ai: 'Важно отметить, что муллиган важен. Оставляйте двушки.', fixed: 'Оставляйте двушки.' });
  assert.deepEqual(result.must_not_contain, ['Важно отметить, что муллиган важен.']);
  assert.deepEqual(pairs.validatePair(result.dir), []);
  const meta = JSON.parse(fs.readFileSync(path.join(result.dir, 'meta.json'), 'utf8'));
  assert.equal(meta.origin, 'owner-correction');
  assert.equal(fs.readFileSync(path.join(result.dir, 'reference.md'), 'utf8'), 'Оставляйте двушки.');
  assert.deepEqual(pairs.regressionHits(meta, 'Важно  отметить, что муллиган ВАЖЕН. Ещё.'), ['Важно отметить, что муллиган важен.']);
  assert.deepEqual(pairs.regressionHits(meta, 'Оставляйте двушки.'), []);
  assert.throws(() => pairs.createCase({ dir, id: 'noop', type: 'GUIDE', topic: 't', date: '2026-10-25', source: 's', ai: 'Тот же.', fixed: 'Тот же.' }), /does not remove/);
  assert.throws(() => pairs.createCase({ dir, id: 'mulligan-fix', type: 'GUIDE', topic: 't', date: '2026-10-25', source: 's', ai: 'a', fixed: 'b' }), /exists/);
});

test('offline pairs run is one command, blind, and never counts as a measurement', async () => {
  const out = path.join(tmp('pairs-run-'), 'run');
  const summary = await blind.runPairs({ outDir: out, random: () => 0 });
  assert.equal(summary.judge_metric.share, 1);
  assert.equal(summary.judge_metric.measured, false);
  const shown = fs.readFileSync(path.join(out, 'pairs.json'), 'utf8');
  assert.doesNotMatch(shown, /"(human|ai)"/);
  assert.deepEqual(JSON.parse(shown)[0].criteria, blind.RUBRIC.criteria.map((c) => c.id));
  await assert.rejects(blind.runPairs({ outDir: out }), /exists/);
  await assert.rejects(blind.runPairs({ outDir: path.join(out, '..', 'real'), realOnly: true }), /no pairs/);
});

async function measuredRun(judgeWinner) {
  const pairsDir = tmp('pairs-real-');
  writePair(pairsDir, 'one');
  writePair(pairsDir, 'two', { type: 'REPORT' });
  const out = path.join(tmp('pairs-measured-'), 'run');
  const scores = Object.fromEntries(blind.RUBRIC.criteria.map((c) => [c.id, 4]));
  const key = () => JSON.parse(fs.readFileSync(path.join(out, 'key.json'), 'utf8'));
  // Судья голосует за заданный вариант, узнавая сторону по ключу: проверка подсчёта, не честности.
  const judgeFn = async (item) => {
    const side = key().pairs.find((row) => row.id === item.id);
    const preferred = judgeWinner === 'tie' ? 'tie' : side.A === judgeWinner ? 'A' : 'B';
    return { model: 'test-model', reply: { A: scores, B: scores, preferred, evidence: ['фрагмент'] } };
  };
  const summary = await blind.runPairs({ pairsDir, outDir: out, editor: 'cmd', editorCmd: 'tr "а" "А"', judgeFn, random: () => 1 });
  return { out, summary };
}

test('model judge metric counts pairs where AI is not worse than the reference', async () => {
  const human = await measuredRun('human');
  assert.equal(human.summary.judge_metric.share, 0);
  assert.equal(human.summary.judge_metric.measured, true);
  assert.equal(fs.readFileSync(path.join(human.out, 'private', 'ai', 'one.md'), 'utf8'), 'Черновик гАйдА.\n');
  const ai = await measuredRun('ai');
  assert.equal(ai.summary.judge_metric.share, 1);
  const read = (run) => JSON.parse(fs.readFileSync(path.join(run.out, 'judge', 'report.json'), 'utf8'));
  assert.deepEqual(blind.gate(read(human), read(ai), 'model'), { accepted: true, rater: 'model', baseline: 0, candidate: 1, cases: 2 });
  assert.equal(blind.gate(read(ai), read(human), 'model').accepted, false);
  assert.throws(() => blind.gate(read(ai), read(ai), 'human'), /missing/);
});

test('owner rates blind pairs interactively, resumes, and import yields the human metric', async () => {
  const { out } = await measuredRun('tie');
  const answers = (lines) => {
    const input = new PassThrough();
    input.end(lines.join('\n') + '\n');
    return input;
  };
  const output = new PassThrough();
  output.resume();
  const now = () => new Date('2026-10-25T10:00:00Z');
  // Первая пара: невалидный балл переспрашивается; ввод обрывается на второй.
  const first = ['7', '5', '4', '5', '4', '5', '4', '5', '4', 'a', 'конкретный совет про двушку', ''];
  await assert.rejects(blind.rate(out, { input: answers([...first, '3']), output, reviewer: 'owner', now }), /input ended/);
  let saved = JSON.parse(fs.readFileSync(path.join(out, 'ratings.json'), 'utf8'));
  assert.equal(saved.length, 1);
  assert.equal(saved[0].preferred, 'A');
  const second = ['2', '3', '2', '3', '2', '3', '2', '3', 'B', 'B живее', 'ok'];
  const result = await blind.rate(out, { input: answers(second), output, reviewer: 'owner', now });
  assert.equal(result.rated, 1);
  saved = JSON.parse(fs.readFileSync(path.join(out, 'ratings.json'), 'utf8'));
  assert.equal(saved.length, 2);
  const report = blind.importRatings(path.join(out, 'ratings.json'), path.join(out, 'key.json'), path.join(out, 'human'));
  assert.equal(report.human_attested_ratings, 2);
  assert.equal(report.metric.human.cases, 2);
  assert.equal(report.metric.human.measured, true);
  // random() === 1 переставляет стороны: A — ИИ, B — эталон. A предпочтён в первой паре, B — во второй.
  assert.equal(report.metric.human.ai_not_worse, 1);
  assert.match(fs.readFileSync(path.join(out, 'human', 'report.md'), 'utf8'), /владелец: 1\/2 = 50%/);
});

test('judge reply parser enforces the rubric protocol', () => {
  const scores = Object.fromEntries(blind.RUBRIC.criteria.map((c) => [c.id, 5]));
  const ok = { A: scores, B: scores, preferred: 'B', evidence: ['фрагмент'] };
  assert.equal(blind.parseJudgeReply('```json\n' + JSON.stringify(ok) + '\n```').preferred, 'B');
  assert.throws(() => blind.parseJudgeReply(JSON.stringify({ ...ok, B: { ...scores, decisions: 6 } })), /1\.\.5/);
  assert.throws(() => blind.parseJudgeReply(JSON.stringify({ ...ok, preferred: 'C' })), /preferred/);
  assert.throws(() => blind.parseJudgeReply(JSON.stringify({ ...ok, evidence: [] })), /evidence/);
  assert.throws(() => blind.parseJudgeReply('нет ответа'), /no JSON/);
});
