const cases = require('./russian.json');
module.exports = () => cases.map(({ control, regression, source, ...row }) => ({
  description: `synthetic Russian ${row.id}`,
  vars: { ...row, text: source, reference: control, expected_properties: { preserve_facts: true, preserve_game_terms: true } },
}));

if (require.main === module) {
  const check = require('../assertions/russian.js');
  const controls = cases.filter((row) => check(row.control, { vars: row }).pass).length;
  const rejected = cases.filter((row) => !check(row.regression, { vars: row }).pass).length;
  console.log(JSON.stringify({ cases: cases.length, controls_passed: controls, regressions_rejected: rejected,
    synthetic: true, model_called: false, quality_improvement_confirmed: false }));
  if (controls !== cases.length || rejected !== cases.length) process.exitCode = 1;
}
