const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

module.exports = function load() {
  const fixture = fs.readFileSync(path.join(__dirname, '../fixtures/RESEARCH_EDITOR_PILOT.inputs.json'), 'utf8').replace(/\r\n/g, '\n');
  const frozen = JSON.parse(fs.readFileSync(path.join(__dirname, '../fixtures/RESEARCH_EDITOR_PILOT.baseline.json'), 'utf8'));
  if (crypto.createHash('sha256').update(fixture).digest('hex') !== frozen.fixture_lf_sha256) throw new Error('frozen pilot inputs changed');
  const cases = JSON.parse(fixture);
  return cases.map(row => ({description: `Controlled synthetic ${row.genre}: ${row.id}`, vars: {
    id: row.id, text: row.text, reference: row.text, question: row.question,
    synthetic: true, evidence_kind: 'controlled_synthetic', split: 'development',
    game: 'hearthstone', profile: 'constructed-guide', language: 'ru-RU',
    genre: row.genre, resource_budget: row.resource_budget,
    expected_properties: {}, protected_entities: [],
  }}));
};
