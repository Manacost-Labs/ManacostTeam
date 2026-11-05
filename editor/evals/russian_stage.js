// Technical gate and explicit outstanding editorial acceptance. No model calls.
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const bank = require('./example_bank.js');
const { loadPairs } = require('./pairs.js');

function summary(checks, review, pairs) {
  const passed = checks.length > 0 && checks.every((row) => row.exit_code === 0);
  return {
    schema_version: 1, stage: 'russian-text-quality',
    technical_status: passed ? 'PASSED' : 'FAILED',
    stage_status: passed ? 'HUMAN_ACCEPTANCE_PENDING' : 'TECHNICAL_FAILURE',
    checks,
    bank: { pending: review.examples.filter((row) => row.status === 'pending').length, approved: review.examples.filter((row) => row.status === 'approved' && !row.synthetic && row.split === 'train').length },
    human_acceptance: { status: 'NOT_RUN', real_pairs_available: pairs.filter((row) => row.meta.synthetic === false).length,
      required_real_materials: 20, calibration: 12, holdout: 8, clean_controls: 5,
      reason: 'No human acceptance evidence supplied. Real pairs, independent fact checks and blind human ratings are required.' },
    live_model_eval: { status: 'NOT_RUN', reason: 'This gate does not run a model or consume API budget.' },
    quality_improvement_confirmed: false, production_approved: false,
  };
}

function main(argv) {
  const option = (name) => { const index = argv.indexOf(name); return index >= 0 ? argv[index + 1] : undefined; };
  const output = option('--out');
  if (!output || fs.existsSync(output)) throw new Error('--out must point to a new report');
  const root = path.resolve(__dirname, '..');
  const python = option('--python') || path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const commands = [
    ['node-evals', process.execPath, '--test', ...['evals', 'pairs', 'publication', 'example-bank', 'russian', 'russian-stage'].map((name) => `evals/tests/${name}.test.js`)],
    ['native-publication', python, '-m', 'pytest', '-q', 'tests/test_publication_run.py'],
    ['russian-contracts', process.execPath, 'evals/cases/russian.js', '--check'],
  ];
  const checks = commands.map(([name, command, ...args]) => {
    const result = spawnSync(command, args, { cwd: root, encoding: 'utf8', timeout: 120000, maxBuffer: 2 * 1024 * 1024 });
    return { name, command: [command, ...args], exit_code: result.status ?? -1,
      stdout_tail: String(result.stdout || '').slice(-1800), stderr_tail: String(result.stderr || result.error?.message || '').slice(-600) };
  });
  const review = bank.validate(JSON.parse(fs.readFileSync(path.join(__dirname, 'examples/review.json'), 'utf8')));
  const report = summary(checks, review, loadPairs(option('--pairs')));
  fs.mkdirSync(path.dirname(path.resolve(output)), { recursive: true, mode: 0o700 });
  bank.writeNew(output, report);
  console.log(JSON.stringify({ saved: output, technical_status: report.technical_status, stage_status: report.stage_status }));
  return report.technical_status !== 'PASSED' ? 1 : argv.includes('--technical-only') ? 0 : 2;
}

if (require.main === module) {
  try { process.exitCode = main(process.argv.slice(2)); } catch (error) { console.error(`error: ${error.message}`); process.exitCode = 1; }
}
module.exports = { summary };
