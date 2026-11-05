// Local language examples. Human attestations follow publication_benchmark's
// reviewer/time/explicit-confirmation convention; these do not approve facts.
const crypto = require('node:crypto');
const fs = require('node:fs');

const FIELDS = ['id', 'before', 'after', 'reason', 'context', 'game', 'profile', 'editorial_mode', 'scope', 'split', 'synthetic', 'source', 'source_sha256'];
const sha = (text) => crypto.createHash('sha256').update(text).digest('hex');
const digest = (row) => sha(JSON.stringify(FIELDS.map((key) => row[key])));
const norm = (text) => text.normalize('NFKC').toLocaleLowerCase('ru').replace(/ё/g, 'е').replace(/\s+/gu, ' ').trim();

function timestamp(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    || !Number.isFinite(Date.parse(value)) || new Date(`${value.slice(0, 10)}T00:00:00Z`).toISOString().slice(0, 10) !== value.slice(0, 10)) {
    throw new Error('review timestamp must be ISO with timezone');
  }
}

function validate(document) {
  if (document?.schema_version !== 1 || !Array.isArray(document.examples)) throw new Error('invalid example bank');
  const ids = new Set();
  for (const row of document.examples) {
    for (const key of FIELDS.filter((key) => !['context', 'synthetic'].includes(key))) {
      if (typeof row[key] !== 'string' || !row[key].trim()) throw new Error(`nonempty ${key} required`);
    }
    if (ids.has(row.id)) throw new Error('duplicate example id');
    ids.add(row.id);
    if (typeof row.context !== 'string' || typeof row.synthetic !== 'boolean'
      || !['train', 'holdout'].includes(row.split) || !['GUIDE', 'ANALYSIS', 'REPORT'].includes(row.editorial_mode)
      || !['pending', 'approved', 'rejected'].includes(row.status) || !/^[a-f0-9]{64}$/.test(row.source_sha256)) throw new Error('invalid example metadata');
    if (row.status === 'approved') {
      if (row.approval?.human_confirmed !== true || typeof row.approval.reviewer !== 'string' || !row.approval.reviewer.trim()) throw new Error('explicit human reviewer approval required');
      timestamp(row.approval.reviewed_at);
      if (row.approval.reviewed_sha256 !== digest(row)) throw new Error('approval hash changed; review the current example again');
    }
  }
  return document;
}

function prepare(corrections, context) {
  if (!Array.isArray(corrections) || !corrections.length) throw new Error('nonempty correction list required');
  return validate({ schema_version: 1, purpose: 'language_only_not_factual_evidence', examples: corrections.map((row, index) => ({
    id: `edit-${sha(JSON.stringify([context.source_sha256, index])).slice(0, 16)}`,
    before: row.was, after: row.became, reason: row.reason, context: row.context || '',
    game: context.game, profile: context.profile, editorial_mode: context.editorial_mode,
    scope: row.scope || 'local', split: 'train', synthetic: context.synthetic === true,
    source: context.source, source_sha256: context.source_sha256,
    status: 'pending', approval: null,
  })) });
}

function approve(document, id, reviewer, humanConfirmed, reviewedAt = new Date().toISOString()) {
  if (humanConfirmed !== true) throw new Error('explicit human review attestation required');
  if (typeof reviewer !== 'string' || !reviewer.trim()) throw new Error('reviewer required');
  timestamp(reviewedAt);
  const result = structuredClone(document);
  const row = result.examples.find((item) => item.id === id);
  if (!row) throw new Error('unknown example id');
  row.status = 'approved';
  row.approval = { human_confirmed: true, reviewer, reviewed_at: reviewedAt, reviewed_sha256: digest(row) };
  return validate(result);
}

function exportApproved(document) {
  validate(document);
  // An entire source/export group is excluded when any of it is held out.
  const held = document.examples.filter((row) => row.split === 'holdout');
  const examples = document.examples.filter((row) => row.status === 'approved' && row.synthetic === false && row.split === 'train'
    && !held.some((test) => test.source === row.source || test.source_sha256 === row.source_sha256));
  if (!examples.length) throw new Error('no human-approved non-synthetic training examples');
  return structuredClone({ schema_version: 1, purpose: 'language_only_not_factual_evidence', examples });
}

function select(document, vars) {
  validate(document);
  if (document.examples.some((row) => row.status !== 'approved' || row.synthetic || row.split !== 'train')) throw new Error('use an exported approved training bank');
  const source = norm(String(vars.text || ''));
  const words = (text) => new Set(norm(text).match(/[\p{L}\p{N}]{4,}/gu) || []);
  const wanted = words(source);
  return document.examples.filter((row) => row.game === vars.game && row.profile === vars.profile && row.editorial_mode === vars.editorial_mode
    && row.id !== vars.id && row.source !== vars.source_url && row.source_sha256 !== vars.source_sha256
    && ![row.before, row.after].some((text) => {
      const example = norm(text);
      return source === example || (Math.min(source.length, example.length) >= 80 && (source.includes(example) || example.includes(source)));
    })
    && [row.before, row.after, row.reason, row.context].join('').length <= 1800)
    .map((row) => ({ row, score: [...words(`${row.before} ${row.after} ${row.context}`)].filter((word) => wanted.has(word)).length }))
    .filter(({ score }) => score > 0).sort((a, b) => b.score - a.score || a.row.id.localeCompare(b.row.id))
    .slice(0, 3).map(({ row }) => structuredClone(row));
}

function writeNew(output, value) {
  fs.writeFileSync(output, JSON.stringify(value, null, 2) + '\n', { flag: 'wx' });
}

function main(argv) {
  const [command] = argv;
  const option = (name) => { const index = argv.indexOf(name); return index >= 0 ? argv[index + 1] : undefined; };
  if (!argv.includes('--input') || !argv.includes('--out')) throw new Error('required --input FILE --out NEW_FILE');
  const raw = fs.readFileSync(option('--input'), 'utf8');
  const input = JSON.parse(raw);
  let output;
  if (command === 'prepare') {
    output = prepare(input, { source: option('--source'), source_sha256: sha(raw), game: option('--game'), profile: option('--profile'), editorial_mode: option('--mode'), synthetic: argv.includes('--synthetic') });
  } else if (command === 'approve') {
    output = approve(input, option('--id'), option('--reviewer'), argv.includes('--attest-human-review'));
  } else if (command === 'export') {
    output = exportApproved(input);
  } else throw new Error('use prepare, approve or export');
  writeNew(option('--out'), output);
  console.log(JSON.stringify({ saved: option('--out'), examples: output.examples.length, approved: output.examples.filter((row) => row.status === 'approved').length }));
}

if (require.main === module) {
  try { main(process.argv.slice(2)); } catch (error) { console.error(`error: ${error.message}`); process.exitCode = 2; }
}
module.exports = { prepare, approve, exportApproved, select, validate, writeNew, digest };
