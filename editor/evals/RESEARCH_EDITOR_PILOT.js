#!/usr/bin/env node
// Reproducible offline control experiment, using the existing evaluation tools.
// No model outputs, human ratings, research findings or quality gains are invented.
const fs = require('node:fs');
const path = require('node:path');
const load = require('./cases/research-editor-pilot.js');
const check = require('./assertions/deterministic.js');
const {prepare, importRatings} = require('./blind_review.js');
const {report} = require('./report.js');

function run(out) {
  if (fs.existsSync(out)) throw new Error('pilot output exists; choose a new directory');
  const cases = load();
  fs.mkdirSync(out, {recursive: true});
  const results = [], controls = [];
  for (const item of cases) {
    for (const variant of ['unchanged-control', 'number-damage-control']) {
      const output = item.vars.text + (variant === 'number-damage-control' ? ' 9999.' : '');
      const metadata = {model: 'identity', deterministic_only: true, accepted: null, checks_complete: false, comparison_variant: variant};
      const verdict = check(output, {vars: item.vars, metadata});
      results.push({vars: item.vars, prompt: {label: variant}, response: {output, metadata}});
      controls.push({id: item.vars.id, variant, pass: verdict.pass, failures: verdict.componentResults.filter(row => !row.pass).map(row => row.reason)});
    }
  }
  const input = path.join(out, 'controls.promptfoo.json');
  fs.writeFileSync(input, JSON.stringify({results}, null, 2));
  const blind = path.join(out, 'blind-controls');
  prepare(input, blind, undefined, {swapOrder: true});
  const human = importRatings(path.join(blind, 'ratings.template.json'), path.join(blind, 'key.json'), blind);
  for (const phase of ['research', 'editorial', 'full_process']) {
    const template = cases.flatMap(item => ['baseline', 'candidate'].map(variant => ({
      case_id: item.vars.id, variant, phase, patch: 'controlled-synthetic-2026-10-19',
      review_status: 'pending', reviewer: null, reviewed_at: null, exposure: null,
      editor_minutes: null, critical_errors: null, answer_seconds: null, answer_errors: null,
      unsupported_advice: null, lost_conditions: null, lost_exceptions: null, confidence_errors: null,
      unnecessary_edits: null, closed_questions: null, new_conditions: null, independent_sources: null,
      remaining_gaps: null, queries: null, tokens: null, elapsed_seconds: null, cost_usd: null,
      source_question: item.vars.question,
    })));
    fs.writeFileSync(path.join(out, `${phase}.ratings.template.json`), JSON.stringify(template, null, 2));
  }
  const summary = {scope: 'controlled synthetic workflow smoke; not a quality comparison', cases: cases.length,
    unchanged_pass: controls.filter(row => row.variant === 'unchanged-control' && row.pass).length,
    number_damage_rejected: controls.filter(row => row.variant === 'number-damage-control' && !row.pass).length,
    blind_presentations: human.pending.length, human_review_status: human.human_review_status,
    human_rated: human.rated, human_preferences: human.preferences, live_model_report: report(input),
    quality_improvement_confirmed: false, controls};
  fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(summary, null, 2));
  return summary;
}
if (require.main === module) {
  if (!process.argv[2]) throw new Error('usage: node evals/RESEARCH_EDITOR_PILOT.js NEW_OUTPUT_DIRECTORY');
  console.log(JSON.stringify(run(path.resolve(process.argv[2])), null, 2));
}
module.exports = {run};
