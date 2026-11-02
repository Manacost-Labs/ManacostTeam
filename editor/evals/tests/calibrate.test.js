const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const cli = path.join(__dirname, '../calibrate.js');
const hash = text => crypto.createHash('sha256').update(text, 'utf8').digest('hex');
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const write = (file, value) => fs.writeFileSync(file, JSON.stringify(value));
const call = args => spawnSync(process.execPath, [cli, ...args], { encoding: 'utf8' });
const cases = [
  { id: 'original', task: 'meaning', source: 'Можно взять карту.', provenance: 'local fixture', source_units: ['S08-0014'],
    variants: [{ text: 'Карту можно взять.', expected: 'accept', reason: 'Возможность сохранена.' },
      { text: 'Карту нужно взять.', expected: 'repair', reason: 'Возможность стала обязанностью.' }] },
  { id: 'compound', task: 'compound', source: 'Можно взять карту, если рука пуста.', reference: 'Сохранить условие и возможность.',
    provenance: 'fixture', source_units: ['S08-0014'], error_types: ['condition', 'modality'], variants: [
      { text: 'Всегда берите карту.', expected: 'repair', reason: 'Две ошибки.' },
      { text: 'Карту нужно взять, если рука пуста.', expected: 'repair', reason: 'Осталась модальность.', error_types: ['modality'] },
      { text: 'Если рука пуста, можно взять карту.', expected: 'accept', reason: 'Оба условия выполнены.' }] },
  { id: 'voice', task: 'voice', source: 'Пока стол пуст, не тратьте ресурс.', brief: 'Расскажите о запасном зонте, без игровых советов.',
    genre: 'совет', topic_source: 'игра', topic_target: 'погода', provenance: 'fixture', source_units: ['S17-0041'],
    variants: [{ text: 'Если тучи рядом, возьмите зонт.', expected: 'accept', reason: 'Сохранён ход мысли, не факты игры.' }] },
];

function run() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'editor-calibration-'));
  const file = path.join(dir, 'cases.json'), out = path.join(dir, 'frozen');
  write(file, cases);
  const prepared = call(['prepare', '--cases', file, '--out', out]);
  assert.equal(prepared.status, 0, prepared.stderr);
  const packetFile = path.join(out, 'packet.json'), packet = read(packetFile);
  const row = (candidate, decision, extra = {}) => {
    const item = packet.items.find(value => value.candidate === candidate);
    return { id: item.id, decision, source_sha256: hash(item.source), candidate_sha256: hash(item.candidate), reason: 'Проверка тестового протокола.', ...extra };
  };
  return { dir, out, file, packet, packetFile, row };
}
function score(run, ...reviews) {
  const args = ['score', '--run', run.out];
  for (const [i, review] of reviews.entries()) {
    const file = path.join(run.dir, 'review-' + i + '.json');
    write(file, review);
    args.push('--reviews', file);
  }
  const file = path.join(run.dir, crypto.randomUUID() + '.json');
  const p = call([...args, '--out', file]);
  return { ...p, report: p.status === 0 ? read(file) : null };
}

test('freeze hides treatment, binds all visible instructions, preserves literal UTF-8, and refuses overwrite', () => {
  const r = run();
  assert.equal(r.packet.items.length, 6);
  assert.equal(new Set(r.packet.items.map(v => v.id)).size, 6);
  for (const item of r.packet.items) {
    assert.match(item.id, /^[0-9a-f-]{36}$/);
    assert.deepEqual(Object.keys(item).filter(k => !['id','task','source','candidate','brief','reference'].includes(k)), []);
  }
  assert.ok(!fs.readFileSync(r.packetFile, 'utf8').includes('S08-0014'));
  assert.ok(r.packet.items.filter(v => v.task === 'compound').every(v => v.reference === cases[1].reference));
  assert.equal(call(['prepare', '--cases', r.file, '--out', r.out]).status, 1);
  assert.deepEqual(read(r.packetFile), r.packet);
  r.packet.items.find(v => v.task === 'compound').reference += ' Изменено.';
  write(r.packetFile, r.packet);
  assert.match(score(r, { reviewer: 'test', reviewer_type: 'offline', rows: [] }).stderr, /hash|changed/);
});

test('false acceptance, false rejection and partial repairs retain separate assigned and judged denominators', () => {
  const r = run();
  const rows = [
    r.row(cases[0].variants[0].text, 'reject', { checks_complete: true }),
    r.row(cases[0].variants[1].text, 'accept', { checks_complete: true }),
    r.row(cases[1].variants[0].text, 'unavailable'),
    r.row(cases[1].variants[1].text, 'accept', { checks_complete: false, skipped_analyzers: ['vale'] }),
    r.row(cases[1].variants[2].text, 'accept', { checks_complete: true }),
  ];
  const result = score(r, { reviewer: 'service', reviewer_type: 'production-critic', rows },
    { reviewer: 'manual model', reviewer_type: 'model', rows: [] });
  assert.equal(result.status, 0, result.stderr);
  const a = result.report.by_reviewer_type['production-critic'][0];
  assert.deepEqual(a.tasks.meaning.false_accept, { count: 1, decided: 1, assigned: 1, rate: 1 });
  assert.deepEqual(a.tasks.meaning.false_reject, { count: 1, decided: 1, assigned: 1, rate: 1 });
  assert.deepEqual(a.tasks.compound.false_accept, { count: 1, decided: 1, assigned: 2, rate: 1 });
  assert.equal(a.tasks.voice.false_reject.rate, null);
  assert.equal(a.coverage.complete, false);
  assert.equal(a.coverage.packet_items, 6);
  assert.equal(a.coverage.assigned, 5);
  assert.equal(a.coverage.not_assigned, 1);
  assert.equal(a.coverage.missing, 0);
  assert.equal(a.coverage.unavailable, 1);
  assert.equal(a.compound_error_combinations.find(g => g.error_types.join() === 'modality').false_accept.count, 1);
  assert.equal(a.compound_error_combinations.find(g => g.error_types.length === 2).false_accept.rate, null);
  assert.deepEqual(a.compound_basis_combinations[0].error_types, ['condition', 'modality']);
  assert.equal(a.compound_basis_combinations[0].coverage.assigned, 3);
  assert.ok(a.errors.some(e => e.expected_reason === 'Возможность стала обязанностью.' && e.review_reason));
  const empty = result.report.by_reviewer_type.model[0];
  assert.equal(empty.coverage.missing, 6);
  assert.equal(empty.coverage.decided, 0);
  assert.equal(empty.tasks.meaning.false_accept.rate, null);
  assert.deepEqual(result.report.by_reviewer_type.human, []);
});

test('rejects stale hashes, foreign IDs, duplicate rows, forged quotes and implicit reviewer type', () => {
  const r = run(), item = r.packet.items[0], good = r.row(item.candidate, 'accept', { candidate_quote: item.candidate, source_quote: item.source });
  const model = rows => ({ reviewer: 'someone', reviewer_type: 'model', rows });
  for (const bad of [model([{ ...good, source_sha256: hash('other') }]), model([{ ...good, candidate_sha256: hash('other') }]),
    model([{ ...good, id: 'elsewhere' }]), model([good,good]), model([{ ...good, candidate_quote: 'нет такой цитаты' }]),
    model([{ ...good, source_quote: 'нет такой цитаты' }]), model([{ ...good, candidate_quote: undefined }]),
    model([{ ...good, decision: 'unavailable' }]), model([{ ...good, task: 'wrong' }]),
    model([{ ...good, decision: 'unavailable', source_quote: undefined, candidate_quote: undefined, scores: {} }]),
    { ...model([good]), packet_sha256: hash('other') },
    { reviewer: 'human:owner', rows: [good] }]) assert.notEqual(score(r, bad).status, 0);
  assert.equal(score(r, model([good])).status, 0);
});

test('fully decided offline control stays separate from real reviewers and never confirms quality', () => {
  const r = run();
  const truth = read(path.join(r.out, 'key.json')).items;
  const rows = truth.map(k => ({ id: k.id, source_sha256: k.source_sha256, candidate_sha256: k.candidate_sha256,
    decision: k.expected, reason: 'Fixture uses the key to test counting.' }));
  const result = score(r, { reviewer_type: 'offline', reviewer: 'oracle-fixture', rows });
  assert.equal(result.status, 0, result.stderr);
  const offline = result.report.by_reviewer_type.offline[0];
  assert.equal(offline.coverage.complete, true);
  assert.equal(offline.tasks.meaning.false_accept.rate, 0);
  assert.equal(offline.tasks.meaning.false_reject.rate, 0);
  assert.equal(offline.tasks.voice.false_accept.rate, null);
  assert.deepEqual(result.report.by_reviewer_type['production-critic'], []);
  assert.equal(result.report.quality_improvement_confirmed, false);
  const previous = fs.readFileSync(r.packetFile);
  assert.equal(call(['score', '--run',r.out,'--reviews',path.join(r.dir,'review-0.json'),'--out',r.packetFile]).status, 1);
  assert.deepEqual(fs.readFileSync(r.packetFile), previous);
});

const http = require('node:http');
const { promisify } = require('node:util');
const execFile = promisify(require('node:child_process').execFile);

async function localJudge(t, respond) {
  const requests = [];
  const server = http.createServer(async (req, res) => {
    let raw = '';
    for await (const chunk of req) raw += chunk;
    const body = JSON.parse(raw);
    requests.push({ url: req.url, auth: req.headers.authorization, body });
    respond(JSON.parse(body.messages[1].content).items, res);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); server.close(); });
  return { url: 'http://127.0.0.1:' + server.address().port + '/v1', requests };
}

async function judge(dir, out, server, extra = {}) {
  return execFile(process.execPath, [cli, 'judge', '--run', dir, '--out', out], { env: {
    ...process.env, EDITOR_EVAL_JUDGE_BASE_URL: server.url, EDITOR_EVAL_JUDGE_MODEL: 'fixture',
    EDITOR_EVAL_JUDGE_API_KEY: 'private-transport-token', EDITOR_EVAL_JUDGE_TIMEOUT_MS: '2000',
    EDITOR_EVAL_JUDGE_BATCH_SIZE: '4', ...extra } });
}
const reply = (res, content) => res.end(JSON.stringify({ choices: [{ message: { content } }] }));
const judged = item => ({ id: item.id, decision: 'accept', source_quote: item.source, candidate_quote: item.candidate,
  reason: 'Тестовая модель связывает утверждение с исходником.' });

test('judge consumes a public packet alone, uses individual quotations, and its report scores normally', async t => {
  const r = run(), publicDir = path.join(r.dir, 'public-only'), out = path.join(r.dir, 'judgments.json');
  fs.mkdirSync(publicDir); fs.copyFileSync(r.packetFile, path.join(publicDir, 'packet.json'));
  const server = await localJudge(t, (items, res) => reply(res, JSON.stringify({ rows: items.map(judged) })));
  await judge(publicDir, out, server);
  const report = read(out);
  assert.equal(report.reviewer_type, 'model');
  assert.equal(report.packet_sha256, hash(fs.readFileSync(r.packetFile)));
  assert.ok(server.requests.every(x => x.url === '/v1/chat/completions' && x.auth === 'Bearer private-transport-token'));
  assert.ok(server.requests.length > 1);
  assert.deepEqual(server.requests.flatMap(x => JSON.parse(x.body.messages[1].content).items).map(x => x.id).sort(), r.packet.items.map(x => x.id).sort());
  assert.ok(server.requests.every(x => !JSON.stringify(x.body).includes('S08-0014') && !JSON.stringify(x.body).includes('private-transport-token')));
  assert.ok(!fs.readFileSync(out, 'utf8').includes(server.url) && !fs.readFileSync(out, 'utf8').includes('private-transport-token'));
  assert.equal(score(r, report).report.by_reviewer_type.model[0].coverage.complete, true);
  const count = server.requests.length;
  await assert.rejects(judge(publicDir, out, server), /exists/);
  assert.equal(server.requests.length, count);
});

test('judge quarantines foreign IDs, missing rows, malformed output and fabricated quotations', async t => {
  const r = run();
  for (const [name, response, want] of [
    ['foreign', items => ({ rows: [...items.map(judged), { ...judged(items[0]), id: 'foreign' }] }), 'foreign'],
    ['duplicate', items => ({ rows: [judged(items[0]), judged(items[0])] }), 'duplicate'],
    ['missing', () => ({ rows: [] }), 'missing'],
    ['quote', items => ({ rows: items.map(item => ({ ...judged(item), candidate_quote: 'invented sentence' })) }), 'invalid'],
    ['json', () => null, 'invalid'],
  ]) {
    const server = await localJudge(t, (items, res) => { const data = response(items); reply(res, data ? JSON.stringify(data) : 'not JSON'); });
    const out = path.join(r.dir, name + '.json');
    await judge(r.out, out, server);
    const report = read(out);
    assert.ok(report.rows.length && report.rows.every(row => row.decision === 'unavailable' && row.reason.includes(want) && !row.candidate_quote));
    assert.equal(score(r, report).report.by_reviewer_type.model[0].coverage.decided, 0);
  }
});

test('judge records transport unavailability with bounded timeout and no automatic preference', async t => {
  const r = run();
  const server = await localJudge(t, () => {});
  const out = path.join(r.dir, 'timeout.json');
  await judge(r.out, out, server, { EDITOR_EVAL_JUDGE_TIMEOUT_MS: '100' });
  const report = read(out);
  assert.ok(report.rows.every(row => row.decision === 'unavailable' && row.reason.includes('timeout')));
  assert.equal(score(r, report).report.by_reviewer_type.model[0].coverage.unavailable, r.packet.items.length);
});

test('judge keeps valid siblings alongside abstentions and bad evidence', async t => {
  const r = run(), out = path.join(r.dir, 'mixed-judgments.json');
  const states = new Map();
  const server = await localJudge(t, (items, res) => {
    const rows = items.map((item, idx) => {
      const row = judged(item);
      if (idx === 0) { states.set(item.id, 'repair'); return { ...row, decision: 'repair' }; }
      if (idx === 1) { states.set(item.id, 'unavailable'); return { id: item.id, decision: 'unavailable', reason: 'Недостаточно контекста.' }; }
      states.set(item.id, 'unavailable');
      return { ...row, source_quote: 'Выдуманный фрагмент.' };
    });
    reply(res, JSON.stringify({ rows }));
  });
  await judge(r.out, out, server);
  const report = read(out);
  assert.ok(report.rows.some(row => row.reason.includes('invalid_source_quote')));
  assert.ok(report.rows.some(row => row.reason.includes('model_unavailable')));
  assert.ok(report.rows.every(row => row.decision === states.get(row.id)));
  assert.equal(score(r, report).report.by_reviewer_type.model[0].coverage.decided,
    report.rows.filter(row => row.decision === 'repair').length);
});

test('judge stops on HTTP refusal, distinguishes unattempted items, and omits provider details', async t => {
  const r = run(), out = path.join(r.dir, 'unavailable.json');
  const server = await localJudge(t, (items, res) => { res.writeHead(503); res.end('private provider diagnostic'); });
  await judge(r.out, out, server, { EDITOR_EVAL_JUDGE_BATCH_SIZE: '2' });
  assert.equal(server.requests.length, 1);
  const report = read(out);
  assert.ok(report.rows.some(row => row.reason === 'http_503'));
  assert.ok(report.rows.some(row => row.reason === 'not_attempted_after_http_503'));
  assert.ok(report.rows.every(row => row.decision === 'unavailable'));
  assert.ok(!fs.readFileSync(out, 'utf8').includes('private provider diagnostic'));
});

test('shipped controls retain traceable archive excerpts and a topic-controlled voice contrast', () => {
  const root = path.resolve(__dirname, '../../..');
  const cases = read(path.join(root, 'editor/evals/cases/source-mechanisms.json'));
  const archiveTasks = new Set(), papers = new Map(), voices = [];
  for (const item of cases) {
    if (item.provenance !== 'synthetic') {
      assert.match(item.provenance, /^editor\/corpus-archive\/guides\/[\w-]+\.md$/);
      const original = fs.readFileSync(path.join(root, item.provenance), 'utf8');
      assert.equal(original.split(item.source).length, 2, 'archive quote is missing or ambiguous: ' + item.id);
      archiveTasks.add(item.task);
    }
    for (const unit of item.source_units) {
      assert.match(unit, /^S\d{2}-\d{4}$/);
      const id = unit.slice(0, 3);
      if (!papers.has(id)) papers.set(id, fs.readFileSync(path.join(root, 'docs/research/ai-writing-2026-10-30/papers', id + '.md'), 'utf8'));
      assert.ok(papers.get(id).includes('| ' + unit + ' |'), 'unknown unit ' + unit);
    }
    if (item.task === 'voice') voices.push(item);
  }
  assert.deepEqual([...archiveTasks].sort(), ['compound', 'meaning', 'voice']);
  // Hold candidate, target topic and genre constant; change the voice reference.
  const crossed = voices.some(a => voices.some(b => a.source !== b.source && a.genre === b.genre
    && a.topic_target === b.topic_target && a.brief === b.brief && a.variants.some(positive =>
      positive.expected === 'accept' && b.variants.some(negative => negative.expected === 'repair' && negative.text === positive.text))));
  assert.ok(crossed, 'voice controls must distinguish the models of writing on the same task');
});

test('HTTP judge can send its payload only to loopback and refuses endpoint credentials', async t => {
  const r = run(), seen = [];
  t.mock.method(globalThis, 'fetch', async (url, req) => {
    seen.push(url.hostname);
    assert.equal(req.redirect, 'error');
    return new Response('', { status: 503 });
  });
  const { judge: invoke } = require('../calibrate');
  const base = { EDITOR_EVAL_JUDGE_MODEL: 'test', EDITOR_EVAL_JUDGE_API_KEY: 'local-test-only' };
  for (const endpoint of ['http://judge.invalid/v1','http://localhost.attacker.invalid/v1',
    'https://user:test@judge.invalid/v1', 'http://user:test@127.0.0.1/v1']) {
    await assert.rejects(invoke(r.out, path.join(r.dir, crypto.randomUUID()), { ...base, EDITOR_EVAL_JUDGE_BASE_URL: endpoint }), /endpoint|HTTPS/);
  }
  assert.deepEqual(seen, []);
  for (const address of ['http://localhost/v1','http://127.255.2.3/v1','http://[::1]/v1','https://judge.invalid/v1']) {
    await invoke(r.out, path.join(r.dir, crypto.randomUUID()), { ...base, EDITOR_EVAL_JUDGE_BASE_URL: address });
  }
  assert.deepEqual(seen, ['localhost','127.255.2.3','[::1]','judge.invalid']);
});

test('production critic verdicts are stratified by completed analyzer checks', () => {
  const r = run();
  const passed = r.row(cases[0].variants[0].text, 'accept', { checks_complete: true });
  const incorrect = r.row(cases[0].variants[1].text, 'accept', { checks_complete: false, skipped_analyzers: ['vale'] });
  const unavailable = r.row(cases[1].variants[0].text, 'unavailable');
  const report = rows => ({ reviewer: 'service', reviewer_type: 'production-critic', rows });
  const result = score(r, report([passed, incorrect, unavailable]));
  assert.equal(result.status, 0, result.stderr);
  const critic = result.report.by_reviewer_type['production-critic'][0];
  assert.equal(critic.metrics_scope, 'critic_only');
  assert.equal(critic.publication_approved, false);
  assert.equal(critic.tasks.meaning.false_accept.count, 1);
  assert.equal(critic.pipeline_checks.complete.count, 1);
  assert.equal(critic.pipeline_checks.complete.tasks.meaning.false_accept.rate, null);
  assert.equal(critic.pipeline_checks.incomplete.count, 1);
  assert.equal(critic.pipeline_checks.incomplete.tasks.meaning.false_accept.rate, 1);
  assert.deepEqual(critic.pipeline_checks.incomplete.skipped_analyzers, { vale: 1 });
  assert.equal(critic.pipeline_checks.unavailable, 1);
  assert.equal(critic.pipeline_checks.missing, 2);
  for (const value of [null, undefined, 'false', 0]) assert.notEqual(score(r, report([{ ...passed, checks_complete: value }])).status, 0);
});

test('judge does not forward packet or authorization across a redirect', async t => {
  const r = run(), out = path.join(r.dir, 'redirect.json');
  const destination = await localJudge(t, (items, res) => reply(res, JSON.stringify({ rows: items.map(judged) })));
  const original = await localJudge(t, (_items, res) => {
    res.writeHead(307, { location: destination.url + '/chat/completions' }); res.end();
  });
  await judge(r.out, out, original);
  assert.equal(original.requests.length, 1);
  assert.equal(destination.requests.length, 0);
  assert.ok(read(out).rows.every(row => row.decision === 'unavailable'));
});

test('production voice is outside assignment even when omitted; technical failures stay assigned', () => {
  const r = run(), unassigned = r.row(cases[2].variants[0].text, 'unavailable', { reason: 'task_not_assigned' });
  const failed = r.row(cases[1].variants[0].text, 'unavailable', { reason: 'new_technical_failure' });
  const prod = rows => ({ reviewer_type: 'production-critic', reviewer: 'service', rows });
  for (const rows of [[failed, unassigned], [failed]]) {
    const result = score(r, prod(rows));
    assert.equal(result.status, 0, result.stderr);
    const entry = result.report.by_reviewer_type['production-critic'][0];
    assert.equal(entry.coverage.packet_items, 6);
    assert.equal(entry.coverage.assigned, 5);
    assert.equal(entry.coverage.unavailable, 1);
    assert.equal(entry.coverage.missing, 4);
    assert.equal(entry.coverage.not_assigned, 1);
    assert.deepEqual(entry.not_assigned.map(v => v.id), [unassigned.id]);
    assert.deepEqual(entry.unavailable.map(v => v.id), [failed.id]);
    assert.equal(entry.tasks.voice.coverage.assigned, 0);
  }
  for (const edit of [{ decision: 'accept', checks_complete: true }, { decision: 'reject' }, { reason: 'invalid_content' },
    { candidate_quote: 'quote' }, { scores: {} }, { verdict: 'repair' }]) {
    assert.notEqual(score(r, prod([{ ...unassigned, ...edit }])).status, 0);
  }
});

test('voice judgments by human and model require exact evidence on both sides', () => {
  const r = run(), voice = r.packet.items.find(row => row.task === 'voice');
  const good = r.row(voice.candidate, 'repair', { candidate_quote: voice.candidate, source_quote: voice.source });
  for (const type of ['model', 'human']) {
    const report = row => ({ reviewer_type: type, reviewer: 'reviewer', rows: [row] });
    assert.equal(score(r, report(good)).status, 0);
    for (const wrong of [undefined, '', 'выдуманная цитата']) {
      assert.notEqual(score(r, report({ ...good, source_quote: wrong })).status, 0);
    }
  }
});
