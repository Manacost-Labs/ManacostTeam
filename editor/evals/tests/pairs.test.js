const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { PassThrough } = require('node:stream');
const { spawnSync } = require('node:child_process');
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

test('explicit clean controls require equality while ordinary duplicates remain invalid', () => {
  const dir = tmp('pairs-clean-');
  assert.deepEqual(pairs.validatePair(writePair(dir, 'clean', { expected_edit: 'none' }, { draft: 'Совет.\n', reference: ' Совет. ' })), []);
  assert.match(pairs.validatePair(writePair(dir, 'unmarked', {}, { draft: 'Совет.', reference: 'Совет.' })).join(';'), /equals draft/);
  assert.match(pairs.validatePair(writePair(dir, 'changed-control', { expected_edit: 'none' })).join(';'), /requires.*equal/);
  for (const [index, value] of ['some', '', true, null].entries()) {
    assert.match(pairs.validatePair(writePair(dir, `bad-control-${index}`, { expected_edit: value })).join(';'), /expected_edit/);
  }
});

test('owner restoration can create an explicit clean regression control through API and CLI', () => {
  const dir = tmp('pairs-restored-');
  const source = 'Сохраняйте ресурс при слабой позиции.';
  const ai = 'Всегда сохраняйте ресурс.';
  const common = { dir, type: 'GUIDE', topic: 'условие', date: '2026-10-25', source, ai, fixed: source };
  assert.throws(() => pairs.createCase({ ...common, id: 'unmarked' }), /equals draft/);
  const result = pairs.createCase({ ...common, id: 'restored', expectedEdit: 'none' });
  const meta = JSON.parse(fs.readFileSync(path.join(result.dir, 'meta.json'), 'utf8'));
  assert.equal(meta.origin, 'owner-correction');
  assert.equal(meta.expected_edit, 'none');
  assert.deepEqual(meta.regression.must_not_contain, [ai]);
  assert.deepEqual(pairs.validatePair(result.dir), []);
  const input = path.join(dir, 'source.md'), rejected = path.join(dir, 'ai.md');
  fs.writeFileSync(input, source); fs.writeFileSync(rejected, ai);
  const cli = spawnSync(process.execPath, [path.join(__dirname, '../pairs.js'), 'case', '--source', input, '--ai', rejected,
    '--fixed', input, '--type', 'GUIDE', '--topic', 'условие', '--id', 'cli-control', '--dir', dir, '--expected-edit', 'none'], { encoding: 'utf8' });
  assert.equal(cli.status, 0, cli.stderr);
  assert.equal(JSON.parse(fs.readFileSync(path.join(dir, 'cli-control/meta.json'), 'utf8')).expected_edit, 'none');
});

async function controlRun({ changed = false, winner = 'tie', synthetic = false, offline = false, offlineJudge = false, mixed = false, swapOrder = false } = {}) {
  const pairsDir = tmp('pairs-control-run-'), out = path.join(tmp('pairs-control-out-'), 'run');
  const id = synthetic ? 'synthetic-control' : 'control';
  writePair(pairsDir, id, { expected_edit: 'none', ...(synthetic ? { origin: 'synthetic', synthetic: true } : {}) },
    { draft: 'Сохраняйте ресурс при слабой позиции.', reference: 'Сохраняйте ресурс при слабой позиции.' });
  if (mixed) writePair(pairsDir, 'ordinary');
  const scores = Object.fromEntries(blind.RUBRIC.criteria.map(c => [c.id, 4]));
  const judgeFn = async item => {
    assert.deepEqual(Object.keys(item).sort(), ['A', 'B', 'criteria', 'id', 'source']);
    assert.doesNotMatch(JSON.stringify(item), /expected_edit|reference_side|unchanged/);
    const side = JSON.parse(fs.readFileSync(path.join(out, 'key.json'), 'utf8')).pairs.find(row => row.id === item.id);
    const preferred = winner === 'tie' ? 'tie' : side.A === winner ? 'A' : 'B';
    return { model: 'test-model', reply: { A: scores, B: scores, preferred, evidence: ['Условие сохранено; суждение fixture, не измерение качества модели.'] } };
  };
  const summary = await blind.runPairs({ pairsDir, outDir: out, editor: offline ? 'offline' : 'cmd',
    editorCmd: changed ? "sed 's/Сохраняйте ресурс при слабой позиции./При слабой позиции сохраняйте ресурс./'" : 'cat',
    ...(offlineJudge ? { judge: 'offline' } : { judgeFn }), swapOrder, random: () => 0 });
  const report = JSON.parse(fs.readFileSync(path.join(out, 'judge/report.json'), 'utf8'));
  return { summary, report, out, id };
}

test('clean controls are separate observations, not an editing metric or a quality verdict', async () => {
  for (const changed of [false, true]) for (const winner of ['tie', 'ai', 'human']) {
    const { summary, report, out } = await controlRun({ changed, winner, mixed: true });
    assert.deepEqual(report.metric.model.case_ids, ['ordinary']);
    assert.equal(report.metric.model.share, winner === 'human' ? 0 : 1);
    const controls = report.control_results.model;
    assert.deepEqual(controls.case_ids, ['control']);
    assert.equal(controls.cases, 1);
    assert.equal(controls.preferences[winner], 1);
    assert.equal(controls.unchanged_outputs, changed ? 0 : 1);
    assert.equal(controls.changed_outputs, changed ? 1 : 0);
    assert.equal(controls.measured, true);
    assert.equal(controls.quality_improvement_confirmed, false);
    assert.equal(controls.accepted, undefined);
    assert.deepEqual(summary.judge_control_results, controls);
    const key = JSON.parse(fs.readFileSync(path.join(out, 'key.json'), 'utf8'));
    assert.deepEqual(key.run.controls, [{ case_id: 'control', expected_edit: 'none', unchanged: !changed }]);
    assert.doesNotMatch(fs.readFileSync(path.join(out, 'pairs.md'), 'utf8'), /expected_edit|reference_side/);
    assert.match(fs.readFileSync(path.join(out, 'pairs.md'), 'utf8'), /Неизменённый исходник допустим/);
    assert.match(fs.readFileSync(path.join(out, 'pairs.md'), 'utf8'), /равноценная формулировка/);
  }
});

test('control-only and synthetic/offline runs cannot inflate the main measured metric', async () => {
  for (const options of [{}, { synthetic: true }, { offline: true }, { offlineJudge: true }]) {
    const { report } = await controlRun(options);
    assert.equal(report.metric.model, null);
    assert.equal(report.control_results.model.measured, !options.synthetic && !options.offline && !options.offlineJudge);
    assert.equal(report.quality_improvement_confirmed, false);
  }
});

test('control-only CLI reports unknown main metric and pending human reviews stay pending', async () => {
  const pairsDir = tmp('pairs-control-cli-'), out = path.join(tmp('pairs-control-cli-out-'), 'run');
  writePair(pairsDir, 'synthetic-clean', { expected_edit: 'none', origin: 'synthetic', synthetic: true },
    { draft: 'Ясный совет.', reference: 'Ясный совет.' });
  const cli = spawnSync(process.execPath, [path.join(__dirname, '../blind_review.js'), 'pairs', '--pairs', pairsDir, '--out', out], { encoding: 'utf8' });
  assert.equal(cli.status, 0, cli.stderr);
  assert.match(cli.stdout, /ИИ не хуже человека: нет оценок/);
  assert.match(cli.stdout, /наблюдение: без изменений 1, изменены 0/);
  assert.match(cli.stdout, /НЕ ИЗМЕРЕНИЕ/);
  const summary = JSON.parse(fs.readFileSync(path.join(out, 'private/summary.json'), 'utf8'));
  assert.equal(summary.judge_metric, null);
  const pending = blind.importRatings(path.join(out, 'ratings.template.json'), path.join(out, 'key.json'), path.join(out, 'pending'));
  assert.equal(pending.rated, 0);
  assert.deepEqual(pending.pending, ['synthetic-clean']);
  assert.equal(pending.metric.human, null);
  assert.equal(pending.control_results.human, null);
  assert.equal(pending.human_review_status, 'pending');
  assert.equal(pending.quality_improvement_confirmed, false);
});

test('human control results keep swapped presentations distinct without double-counting outputs', async () => {
  const { out } = await controlRun({ changed: true, swapOrder: true });
  const model = JSON.parse(fs.readFileSync(path.join(out, 'judge/ratings.json'), 'utf8'));
  const ratings = model.map(row => ({ ...row, review_status: 'reviewed', reviewer: 'owner', reviewed_at: '2026-10-31T12:00:00Z' }));
  const ratingsFile = path.join(out, 'human-ratings.json');
  fs.writeFileSync(ratingsFile, JSON.stringify(ratings));
  const report = blind.importRatings(ratingsFile, path.join(out, 'key.json'), path.join(out, 'human'));
  assert.equal(report.metric.human, null);
  assert.equal(report.control_results.human.cases, 1);
  assert.equal(report.control_results.human.observations, 2);
  assert.equal(report.control_results.human.changed_outputs, 1);
  assert.equal(report.control_results.human.preferences.tie, 2);
  assert.equal(report.control_results.human.measured, true);
});
