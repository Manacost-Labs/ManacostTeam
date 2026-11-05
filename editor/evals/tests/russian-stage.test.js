const assert = require('node:assert/strict');
const test = require('node:test');
const { summary } = require('../russian_stage.js');

test('technical success does not become human or model acceptance', () => {
  const report = summary([{ name: 'fixtures', exit_code: 0 }], { examples: [{ status: 'pending' }] }, [{ meta: { synthetic: true } }]);
  assert.equal(report.technical_status, 'PASSED');
  assert.equal(report.stage_status, 'HUMAN_ACCEPTANCE_PENDING');
  assert.equal(report.human_acceptance.status, 'NOT_RUN');
  assert.equal(report.human_acceptance.real_pairs_available, 0);
  assert.equal(report.live_model_eval.status, 'NOT_RUN');
  assert.equal(report.quality_improvement_confirmed, false);
});

test('a failed technical check remains a failed gate', () => {
  const report = summary([{ name: 'fixtures', exit_code: 1 }], { examples: [] }, []);
  assert.equal(report.technical_status, 'FAILED');
  assert.equal(report.stage_status, 'TECHNICAL_FAILURE');
});
