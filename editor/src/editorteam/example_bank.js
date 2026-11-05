// Local language examples. Human attestations follow publication_benchmark's
// reviewer/time/explicit-confirmation convention; these do not approve facts.
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const FIELDS = ['id', 'before', 'after', 'reason', 'context', 'game', 'profile', 'editorial_mode', 'scope', 'split', 'synthetic', 'source', 'source_sha256'];
const FUNCTIONS = ['opening', 'decision', 'explanation', 'aside', 'transition', 'conclusion'];
const sha = (text) => crypto.createHash('sha256').update(text).digest('hex');
// Absent optional metadata keeps existing attestations byte-compatible.
const digest = (row) => sha(JSON.stringify([...FIELDS.map((key) => row[key]),
  ...(Object.hasOwn(row, 'editorial_function') ? [['editorial_function', row.editorial_function]] : [])]));
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
    if (Object.hasOwn(row, 'editorial_function') && !FUNCTIONS.includes(row.editorial_function)) throw new Error('invalid editorial function');
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
    ...(Object.hasOwn(row, 'editorial_function') ? { editorial_function: row.editorial_function } : {}),
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
  if (Object.hasOwn(vars, 'editorial_function') && !FUNCTIONS.includes(vars.editorial_function)) throw new Error('invalid editorial function');
  if (document.examples.some((row) => row.status !== 'approved' || row.synthetic || row.split !== 'train')) throw new Error('use an exported approved training bank');
  const source = norm(String(vars.text || ''));
  const words = (text) => new Set(norm(text).match(/[\p{L}\p{N}]{4,}/gu) || []);
  const wanted = words(source);
  return document.examples.filter((row) => row.game === vars.game && row.profile === vars.profile && row.editorial_mode === vars.editorial_mode
    && (!vars.editorial_function || row.editorial_function === vars.editorial_function)
    && row.id !== vars.id && row.source !== vars.source_url && row.source_sha256 !== vars.source_sha256
    && !(vars.exclude_sources || []).includes(row.source)
    && ![row.before, row.after].some((text) => {
      const example = norm(text);
      return source === example || (Math.min(source.length, example.length) >= 80 && (source.includes(example) || example.includes(source)));
    })
    && [row.before, row.after, row.reason, row.context].join('').length <= 1800)
    .map((row) => ({ row, score: [...words(`${row.before} ${row.after} ${row.context}`)].filter((word) => wanted.has(word)).length }))
    .filter(({ score }) => vars.editorial_function || score > 0).sort((a, b) => b.score - a.score || a.row.id.localeCompare(b.row.id))
    .slice(0, 3).map(({ row }) => structuredClone(row));
}

function writeNew(output, value) {
  fs.writeFileSync(output, JSON.stringify(value, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
}

function capture(options) {
  if (fs.existsSync(options.out)) throw new Error('capture output already exists');
  if ((options.synthetic === true) === (options.realSource === true)) throw new Error('declare exactly one of --real-source or --synthetic');
  const artifacts = {}, texts = {}, contents = {};
  for (const name of ['draft', 'ai', 'final']) {
    const bytes = fs.readFileSync(options[name]);
    const text = bytes.toString('utf8');
    if (!text.trim() || !Buffer.from(text).equals(bytes)) throw new Error('nonempty UTF-8 article files required');
    contents[name] = bytes;
    texts[name] = text;
    artifacts[name] = { file: `${name}.md`, sha256: sha(bytes) };
  }
  const sourceHash = sha(JSON.stringify(artifacts));
  const review = prepare([{ was: texts.ai, became: texts.final, reason: options.reason, context: options.context || '', scope: 'local',
    ...(options.editorial_function !== undefined ? { editorial_function: options.editorial_function } : {}) }], {
    ...options, source_sha256: sourceHash,
  });
  fs.mkdirSync(options.out, { mode: 0o700 });
  for (const [name, bytes] of Object.entries(contents)) fs.writeFileSync(path.join(options.out, `${name}.md`), bytes, { flag: 'wx', mode: 0o600 });
  writeNew(path.join(options.out, 'review.json'), review);
  writeNew(path.join(options.out, 'manifest.json'), { schema_version: 1, artifacts, source_records_sha256: sourceHash, source: options.source,
    review_sha256: sha(fs.readFileSync(path.join(options.out, 'review.json'))),
    synthetic: options.synthetic === true, human_approved: false, created_at: new Date().toISOString() });
  return { saved: options.out, examples: 1, approved: 0 };
}

function verifyCapture(directory) {
  const manifest = JSON.parse(fs.readFileSync(path.join(directory, 'manifest.json'), 'utf8'));
  const reviewBytes = fs.readFileSync(path.join(directory, 'review.json'));
  if (manifest.schema_version !== 1 || sha(reviewBytes) !== manifest.review_sha256) throw new Error('capture review hash mismatch');
  const review = validate(JSON.parse(reviewBytes));
  for (const name of ['draft', 'ai', 'final']) {
    const file = path.join(directory, `${name}.md`);
    if (manifest.artifacts?.[name]?.file !== `${name}.md` || fs.lstatSync(file).isSymbolicLink()
      || sha(fs.readFileSync(file)) !== manifest.artifacts[name].sha256) throw new Error('capture artifact hash mismatch');
  }
  const row = review.examples[0];
  if (review.examples.length !== 1 || row.source !== manifest.source || row.synthetic !== manifest.synthetic
    || row.source_sha256 !== manifest.source_records_sha256 || sha(JSON.stringify(manifest.artifacts)) !== manifest.source_records_sha256
    || row.before !== fs.readFileSync(path.join(directory, 'ai.md'), 'utf8') || row.after !== fs.readFileSync(path.join(directory, 'final.md'), 'utf8')) throw new Error('capture review hash mismatch');
  return { valid: true, id: row.id, status: row.status };
}

function main(argv) {
  const [command] = argv;
  const option = (name) => { const index = argv.indexOf(name); return index >= 0 ? argv[index + 1] : undefined; };
  if (command === 'select') {
    const input = JSON.parse(fs.readFileSync(0, 'utf8'));
    console.log(JSON.stringify(select(input.bank, input.vars)));
    return;
  }
  if (command === 'verify-capture') {
    console.log(JSON.stringify(verifyCapture(option('--input'))));
    return;
  }
  if (command === 'capture') {
    console.log(JSON.stringify(capture({ draft: option('--draft'), ai: option('--ai'), final: option('--final'), out: option('--out'),
      source: option('--source'), reason: option('--reason'), context: option('--context'), game: option('--game'), profile: option('--profile'),
      editorial_function: option('--editorial-function'),
      editorial_mode: option('--mode'), synthetic: argv.includes('--synthetic'), realSource: argv.includes('--real-source') })));
    return;
  }
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
module.exports = { prepare, approve, exportApproved, select, validate, writeNew, digest, capture, verifyCapture, main };
