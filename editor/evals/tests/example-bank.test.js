const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const bank = require('../example_bank.js');

function prepared() {
  return bank.prepare([{ was: 'осуществлять добор', became: 'добирать карты', reason: 'Прямой глагол', context: 'Объяснение действия игрока' }], {
    source: 'https://example.org/synthetic-fixture', source_sha256: 'a'.repeat(64),
    game: 'hearthstone', profile: 'constructed-guide', editorial_mode: 'GUIDE', synthetic: true,
  });
}

function approved() {
  const review = prepared();
  // Test-only attestation, never a real editorial approval.
  review.examples[0].synthetic = false;
  return bank.approve(review, review.examples[0].id, 'synthetic-test-reviewer', true, '2026-11-05T12:00:00Z');
}

test('recorded corrections are pending until an explicit human attestation', () => {
  const review = prepared();
  assert.equal(review.examples[0].status, 'pending');
  assert.equal(review.examples[0].approval, null);
  assert.throws(() => bank.exportApproved(review), /approved/);
  assert.throws(() => bank.approve(review, review.examples[0].id, 'owner', false), /human/);
  assert.throws(() => bank.approve(review, review.examples[0].id, '', true), /reviewer/);
});

test('synthetic entries cannot become production style examples', () => {
  const review = prepared();
  const attested = bank.approve(review, review.examples[0].id, 'fixture', true);
  assert.throws(() => bank.exportApproved(attested), /approved/);
});

test('approval binds the exact text, rationale, context, source and split', () => {
  const review = approved();
  assert.equal(bank.exportApproved(review).examples.length, 1);
  for (const [field, value] of Object.entries({ before: 'новый исходник', after: 'новая правка', reason: 'другое основание', context: 'иной контекст', source_sha256: 'b'.repeat(64), split: 'holdout', profile: 'meta-report' })) {
    const modified = structuredClone(review);
    modified.examples[0][field] = value;
    assert.throws(() => bank.exportApproved(modified), /hash|approval/);
  }
});

test('holdout is excluded and malformed attestations fail closed', () => {
  const review = prepared();
  review.examples[0].synthetic = false;
  review.examples[0].split = 'holdout';
  const checked = bank.approve(review, review.examples[0].id, 'fixture', true);
  assert.throws(() => bank.exportApproved(checked), /approved/);
  for (const value of ['yesterday', '2026-11-05T12:00:00']) {
    assert.throws(() => bank.approve(review, review.examples[0].id, 'fixture', true, value), /timestamp/);
  }
});

test('holding out one row excludes the entire source group', () => {
  const review = approved();
  const held = structuredClone(prepared().examples[0]);
  held.id = 'held-out-row';
  held.split = 'holdout';
  review.examples.push(held);
  assert.throws(() => bank.exportApproved(review), /approved/);
});

test('selection is bounded, deterministic and skips long examples without truncation', () => {
  let review = bank.prepare(Array.from({ length: 5 }, (_, index) => ({
    was: `Пример добора ${index}`, became: `Объяснение добора ${index}`, reason: 'Синтетическая проверка лимита',
  })), { source: 'fixture', source_sha256: 'c'.repeat(64), game: 'hearthstone', profile: 'constructed-guide', editorial_mode: 'GUIDE' });
  review.examples[0].reason = 'Длинная причина. '.repeat(200);
  for (const row of review.examples) review = bank.approve(review, row.id, 'synthetic-test-reviewer', true);
  const exported = bank.exportApproved(review);
  const vars = { text: 'Понятное объяснение добора игроку.', game: 'hearthstone', profile: 'constructed-guide', editorial_mode: 'GUIDE' };
  const selected = bank.select(exported, vars);
  assert.equal(selected.length, 3);
  assert.ok(selected.every((row) => row.id !== review.examples[0].id));
  assert.deepEqual(selected, bank.select(exported, vars));
});

test('selection matches game/profile/mode and excludes the evaluated source', () => {
  const exported = bank.exportApproved(approved());
  const vars = { game: 'hearthstone', profile: 'constructed-guide', editorial_mode: 'GUIDE', text: 'Как объяснить добор карт игроку?' };
  assert.equal(bank.select(exported, vars).length, 1);
  for (const changes of [{ game: 'wow' }, { profile: 'meta-report' }, { editorial_mode: 'REPORT' }, { text: 'осуществлять добор' }, { text: 'добирать карты' }, { text: 'совсем посторонняя тема' }]) {
    assert.equal(bank.select(exported, { ...vars, ...changes }).length, 0);
  }
});

test('a short local correction remains usable inside a new article but long source overlaps are excluded', () => {
  const exported = bank.exportApproved(approved());
  const vars = { game: 'hearthstone', profile: 'constructed-guide', editorial_mode: 'GUIDE', text: 'Здесь редактор предлагает осуществлять добор в другом игровом контексте.' };
  assert.equal(bank.select(exported, vars).length, 1);
  const review = approved();
  review.examples[0].before = 'Контекст добора и сохранения ресурсов. '.repeat(4);
  const checked = bank.exportApproved(bank.approve(review, review.examples[0].id, 'synthetic-test-reviewer', true));
  assert.equal(bank.select(checked, { ...vars, text: review.examples[0].before + ' Продолжение того же исходника.' }).length, 0);
});

test('duplicates, empty rationales and altered exported data are rejected', () => {
  const review = approved();
  review.examples.push(structuredClone(review.examples[0]));
  assert.throws(() => bank.exportApproved(review), /duplicate/);
  assert.throws(() => bank.prepare([{ was: 'до', became: 'после', reason: '' }], { source: 'fixture' }), /reason|source/);
  const exported = bank.exportApproved(approved());
  exported.examples[0].after += ' Подмена.';
  assert.throws(() => bank.select(exported, { text: 'добор карт' }), /hash|approval/);
});

test('writing a review or exported bank never overwrites existing data', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'language-bank-'));
  try {
    const output = path.join(directory, 'review.json');
    bank.writeNew(output, prepared());
    const original = fs.readFileSync(output);
    assert.throws(() => bank.writeNew(output, approved()), /EEXIST/);
    assert.deepEqual(fs.readFileSync(output), original);
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});

test('the committed seed has recorded provenance and no inferred approvals', () => {
  const seed = JSON.parse(fs.readFileSync(path.join(__dirname, '../examples/review.json'), 'utf8'));
  assert.equal(seed.examples.length, 10);
  assert.ok(seed.examples.every((row) => row.status === 'pending' && row.approval === null));
  assert.throws(() => bank.exportApproved(seed), /approved/);
});

test('capture freezes draft/AI/final bytes and prepares only pending learning data', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'language-capture-'));
  try {
    const files = { draft: 'Исходный черновик.\r\n', ai: 'Вариант модели.\n', final: 'Финальная правка.\n' };
    for (const [name, text] of Object.entries(files)) fs.writeFileSync(path.join(directory, `${name}.md`), text);
    const output = path.join(directory, 'captured');
    bank.capture({ draft: path.join(directory, 'draft.md'), ai: path.join(directory, 'ai.md'), final: path.join(directory, 'final.md'), out: output,
      source: 'synthetic-fixture', game: 'hearthstone', profile: 'guide', editorial_mode: 'GUIDE', reason: 'Тест протокола', synthetic: true });
    for (const [name, text] of Object.entries(files)) assert.equal(fs.readFileSync(path.join(output, `${name}.md`), 'utf8'), text);
    const pending = JSON.parse(fs.readFileSync(path.join(output, 'review.json'), 'utf8'));
    assert.equal(pending.examples[0].before, files.ai);
    assert.equal(pending.examples[0].after, files.final);
    assert.equal(pending.examples[0].status, 'pending');
    assert.equal(pending.examples[0].approval, null);
    assert.equal(pending.examples[0].synthetic, true);
    assert.throws(() => bank.capture({ out: output }), /exist/);
    const manifest = JSON.parse(fs.readFileSync(path.join(output, 'manifest.json'), 'utf8'));
    assert.equal(manifest.human_approved, false);
    assert.equal(manifest.artifacts.draft.sha256, require('node:crypto').createHash('sha256').update(files.draft).digest('hex'));
    assert.equal(bank.verifyCapture(output).valid, true);
    const frozenReview = fs.readFileSync(path.join(output, 'review.json'));
    const modified = JSON.parse(frozenReview);
    modified.examples[0].context = 'Подмена контекста.';
    fs.writeFileSync(path.join(output, 'review.json'), JSON.stringify(modified));
    assert.throws(() => bank.verifyCapture(output), /hash/);
    fs.writeFileSync(path.join(output, 'review.json'), frozenReview);
    fs.appendFileSync(path.join(output, 'draft.md'), 'Подмена.');
    assert.throws(() => bank.verifyCapture(output), /hash/);
  } finally { fs.rmSync(directory, { recursive: true, force: true }); }
});

test('capture requires an explicit real or synthetic source declaration', () => {
  assert.throws(() => bank.capture({ out: 'not-written' }), /real-source|synthetic/);
  assert.throws(() => bank.capture({ out: 'not-written', realSource: true, synthetic: true }), /real-source|synthetic/);
});

test('canonical selection CLI uses stdin and is ready for native publication tasks', () => {
  const { execFileSync } = require('node:child_process');
  const result = JSON.parse(execFileSync(process.execPath, [path.join(__dirname, '../example_bank.js'), 'select'], {
    input: JSON.stringify({ bank: bank.exportApproved(approved()), vars: { game: 'hearthstone', profile: 'constructed-guide', editorial_mode: 'GUIDE', text: 'Как объяснить добор карт игроку?' } }), encoding: 'utf8',
  }));
  assert.equal(result.length, 1);
});

test('prompt provider sends approved examples only when enabled and records the exact examples', async () => {
  const Provider = require('../providers/prompt-direct.js');
  const prompt = fs.readFileSync(path.join(__dirname, '../prompts/candidate.txt'), 'utf8').trim();
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'language-provider-'));
  const file = path.join(directory, 'bank.json');
  bank.writeNew(file, bank.exportApproved(approved()));
  const vars = { text: 'Как объяснить добор карт игроку?', game: 'hearthstone', profile: 'constructed-guide', editorial_mode: 'GUIDE' };
  const previousEnv = { ...process.env };
  const previousFetch = global.fetch;
  const calls = [];
  try {
    delete process.env.EDITOR_EVAL_OFFLINE;
    process.env.EDITOR_EVAL_CANDIDATE_PROVIDER = 'ollama';
    process.env.EDITOR_EVAL_CANDIDATE_MODEL = 'synthetic-test';
    process.env.EDITOR_EVAL_CANDIDATE_BASE_URL = 'http://127.0.0.1:11434/v1';
    global.fetch = async (url, options = {}) => {
      if (String(url).endsWith('/chat/completions')) {
        calls.push(JSON.parse(options.body));
        return new Response(JSON.stringify({ choices: [{ message: { content: vars.text } }] }));
      }
      return new Response(JSON.stringify(String(url).endsWith('/health') ? { ok: true, checks_complete: true } : { accepted: true }));
    };
    const off = await new Provider({ config: { examples: 'off', exampleBank: file } }).callApi(prompt, { vars });
    const on = await new Provider({ config: { examples: 'on', exampleBank: file } }).callApi(prompt, { vars });
    assert.deepEqual(off.metadata.example_ids, []);
    assert.equal(on.metadata.example_ids.length, 1);
    assert.deepEqual(on.metadata.style_example_texts, ['добирать карты']);
    assert.equal(off.metadata.comparison_variant, 'baseline');
    assert.equal(on.metadata.comparison_variant, 'candidate');
    const { pairUp } = require('../blind_review.js');
    assert.equal(pairUp([
      { vars: { ...vars, id: 'synthetic-language-comparison' }, response: off },
      { vars: { ...vars, id: 'synthetic-language-comparison' }, response: on },
    ]).length, 1);
    assert.equal(calls[0].messages[1].content, vars.text);
    assert.match(calls[1].messages[1].content, /добирать карты/);
    assert.match(calls[1].messages[0].content, /только для формы/);
    assert.notEqual(new Provider({ config: { examples: 'on' } }).id(), new Provider({ config: { examples: 'off' } }).id());
    await assert.rejects(new Provider({ config: { examples: 'on', exampleBank: file } }).callApi(prompt, { vars: { ...vars, game: 'wow' } }), /eligible/);
    await assert.rejects(new Provider({ config: { examples: 'typo', exampleBank: file } }).callApi(prompt, { vars }), /examples must/);
  } finally {
    global.fetch = previousFetch;
    for (const key of Object.keys(process.env)) if (!(key in previousEnv)) delete process.env[key];
    Object.assign(process.env, previousEnv);
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
