const assert = require('node:assert/strict');
const test = require('node:test');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const check = require('../assertions/russian.js');
const cases = require('../cases/russian.json');

test('Russian contracts accept each fixture control and reject its targeted regression', () => {
  assert.ok(cases.length >= 12);
  assert.equal(new Set(cases.map((row) => row.id)).size, cases.length);
  for (const row of cases) {
    assert.equal(row.synthetic, true);
    assert.equal(check(row.control, { vars: row }).pass, true, row.id);
    assert.equal(check(row.regression, { vars: row }).pass, false, row.id);
  }
});

test('contracts are case-specific and do not create a universal word blacklist', () => {
  assert.equal(check('Важно отметить условие, процитированное автором.', { vars: { russian_contract: { required: [], forbidden: [] } } }).pass, true);
  assert.throws(() => check('Текст', { vars: {} }), /contract/);
});

test('required alternatives permit a declared paraphrase and reject their loss', () => {
  const vars = { russian_contract: { required: [['только если', 'при условии']], forbidden: [] } };
  assert.equal(check('Сработает при условии сохранения ресурса.', { vars }).pass, true);
  assert.equal(check('Сработает всегда.', { vars }).pass, false);
});

test('offline regression CLI reports fixture checks without claiming measured text quality', () => {
  const result = JSON.parse(execFileSync(process.execPath, [path.join(__dirname, '../cases/russian.js'), '--check'], { encoding: 'utf8' }));
  assert.equal(result.cases, cases.length);
  assert.equal(result.controls_passed, cases.length);
  assert.equal(result.regressions_rejected, cases.length);
  assert.equal(result.model_called, false);
  assert.equal(result.quality_improvement_confirmed, false);
});
