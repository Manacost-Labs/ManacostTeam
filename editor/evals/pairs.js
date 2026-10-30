#!/usr/bin/env node
// Пары «черновик → эталон» для измерения редактуры против человека.
//
//   node evals/pairs.js validate [evals/pairs]
//     → проверяет формат всех пар, exit 1 при ошибке.
//   node evals/pairs.js case --source черновик.md --ai правка-ии.md --fixed правка-владельца.md \
//       --type GUIDE --topic "…" --id slug [--date 2026-10-25] [--note "что исправлено"] [--dir evals/pairs]
//     → превращает правку владельца в регрессионную пару.
//
// Структура пары: <dir>/<id>/draft.md, reference.md, meta.json; формат — в pairs/README.md.
const fs = require('node:fs');
const path = require('node:path');

const PAIRS_DIR = path.join(__dirname, 'pairs');
const TYPES = ['GUIDE', 'ANALYSIS', 'REPORT'];
const ORIGINS = ['owner', 'owner-correction', 'synthetic'];
const META_KEYS = new Set(['id', 'type', 'topic', 'date', 'origin', 'synthetic', 'notes', 'regression', 'expected_edit']);
const ID_RE = /^[a-z0-9][a-z0-9-]*$/;

function readText(file) {
  return fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : null;
}

function validDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

// Возвращает список ошибок одной пары; пустой список — пара годна.
function validatePair(pairDir) {
  const errors = [];
  const name = path.basename(pairDir);
  const draft = readText(path.join(pairDir, 'draft.md'));
  const reference = readText(path.join(pairDir, 'reference.md'));
  const metaRaw = readText(path.join(pairDir, 'meta.json'));
  if (!draft?.trim()) errors.push('draft.md missing or empty');
  if (!reference?.trim()) errors.push('reference.md missing or empty');
  if (metaRaw === null) return [...errors, 'meta.json missing'];
  let meta;
  try {
    meta = JSON.parse(metaRaw);
  } catch (error) {
    return [...errors, `meta.json invalid JSON: ${error.message}`];
  }
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return [...errors, 'meta.json must be an object'];
  for (const key of Object.keys(meta)) if (!META_KEYS.has(key)) errors.push(`meta.${key} is not a known field`);
  if (meta.expected_edit !== undefined && meta.expected_edit !== 'none') errors.push('meta.expected_edit must be none when present');
  const same = draft?.trim() && draft.trim() === reference?.trim();
  if (meta.expected_edit === 'none') {
    if (!same) errors.push('meta.expected_edit=none requires draft.md and reference.md to be equal');
  } else if (same) errors.push('reference.md equals draft.md');
  if (meta.id !== name) errors.push(`meta.id must equal directory name ${name}`);
  if (!ID_RE.test(name)) errors.push('id must be a lowercase slug');
  if (!TYPES.includes(meta.type)) errors.push(`meta.type must be one of ${TYPES.join('|')}`);
  if (typeof meta.topic !== 'string' || !meta.topic.trim()) errors.push('meta.topic required');
  if (!validDate(meta.date)) errors.push('meta.date must be YYYY-MM-DD');
  if (!ORIGINS.includes(meta.origin)) errors.push(`meta.origin must be one of ${ORIGINS.join('|')}`);
  if (meta.synthetic !== (meta.origin === 'synthetic')) errors.push('meta.synthetic must be true exactly for origin=synthetic');
  if (meta.synthetic === true && !name.startsWith('synthetic-')) errors.push('synthetic pair id must start with synthetic-');
  if (meta.synthetic !== true && name.startsWith('synthetic-')) errors.push('only synthetic pairs may use the synthetic- prefix');
  if (meta.notes !== undefined && typeof meta.notes !== 'string') errors.push('meta.notes must be a string');
  if (meta.regression !== undefined) {
    const list = meta.regression?.must_not_contain;
    if (!Array.isArray(list) || !list.length || list.some((item) => typeof item !== 'string' || !item.trim())) {
      errors.push('meta.regression.must_not_contain must be a non-empty list of strings');
    }
    if (meta.origin !== 'owner-correction') errors.push('meta.regression is allowed only for origin=owner-correction');
  }
  return errors;
}

function pairDirs(dir) {
  if (!fs.existsSync(dir)) throw new Error(`pairs directory not found: ${dir}`);
  return fs.readdirSync(dir, { withFileTypes: true }).filter((entry) => entry.isDirectory())
    .map((entry) => path.join(dir, entry.name)).sort();
}

function validateAll(dir = PAIRS_DIR) {
  const report = {};
  for (const pairDir of pairDirs(dir)) {
    const errors = validatePair(pairDir);
    if (errors.length) report[path.basename(pairDir)] = errors;
  }
  return report;
}

function loadPairs(dir = PAIRS_DIR) {
  const invalid = validateAll(dir);
  if (Object.keys(invalid).length) throw new Error(`invalid pairs: ${JSON.stringify(invalid)}`);
  const pairs = pairDirs(dir).map((pairDir) => ({
    meta: JSON.parse(fs.readFileSync(path.join(pairDir, 'meta.json'), 'utf8')),
    draft: fs.readFileSync(path.join(pairDir, 'draft.md'), 'utf8'),
    reference: fs.readFileSync(path.join(pairDir, 'reference.md'), 'utf8'),
  }));
  if (!pairs.length) throw new Error(`no pairs in ${dir}`);
  return pairs;
}

function sentences(text) {
  return String(text).split(/(?<=[.!?…])\s+|\n+/u).map((item) => item.trim()).filter(Boolean);
}

const norm = (text) => text.toLowerCase().replace(/\s+/g, ' ').trim();

// Предложения правки ИИ, которые владелец убрал или переписал: кандидаты
// в запрет на повтор. shortcut: сравнение целыми предложениями; узкую фразу
// владелец вписывает в meta.json руками, когда предложение слишком длинное.
function rejectedSentences(aiText, fixedText) {
  const kept = new Set(sentences(fixedText).map(norm));
  return [...new Set(sentences(aiText).filter((item) => !kept.has(norm(item)) && /\p{L}/u.test(item)))];
}

function createCase({ source, ai, fixed, type, topic, id, date, note, expectedEdit, dir = PAIRS_DIR }) {
  const pairDir = path.join(dir, id);
  if (fs.existsSync(pairDir)) throw new Error(`pair exists: ${pairDir}`);
  const mustNotContain = rejectedSentences(ai, fixed);
  if (!mustNotContain.length) throw new Error('owner correction does not remove anything from the AI edit');
  const meta = { id, type, topic, date, origin: 'owner-correction', synthetic: false,
    ...(expectedEdit !== undefined ? { expected_edit: expectedEdit } : {}),
    ...(note ? { notes: note } : {}), regression: { must_not_contain: mustNotContain } };
  fs.mkdirSync(pairDir, { recursive: true });
  fs.writeFileSync(path.join(pairDir, 'draft.md'), source);
  fs.writeFileSync(path.join(pairDir, 'reference.md'), fixed);
  fs.writeFileSync(path.join(pairDir, 'ai_rejected.md'), ai);
  fs.writeFileSync(path.join(pairDir, 'meta.json'), JSON.stringify(meta, null, 2) + '\n');
  const errors = validatePair(pairDir);
  if (errors.length) {
    fs.rmSync(pairDir, { recursive: true });
    throw new Error(`created pair is invalid: ${errors.join('; ')}`);
  }
  return { dir: pairDir, must_not_contain: mustNotContain };
}

// Регрессия: в новой правке ИИ снова появилась фраза, которую владелец убрал.
function regressionHits(meta, output) {
  const text = norm(output);
  return (meta.regression?.must_not_contain || []).filter((phrase) => text.includes(norm(phrase)));
}

function main(argv) {
  const [command, positional] = argv.slice(2);
  const option = (name) => {
    const index = argv.indexOf(name);
    return index >= 0 ? argv[index + 1] : undefined;
  };
  if (command === 'validate') {
    const dir = positional && !positional.startsWith('--') ? positional : PAIRS_DIR;
    const invalid = validateAll(dir);
    const total = pairDirs(dir).length;
    for (const [id, errors] of Object.entries(invalid)) console.error(`${id}: ${errors.join('; ')}`);
    console.log(`pairs: ${total}, invalid: ${Object.keys(invalid).length}`);
    return Object.keys(invalid).length || !total ? 1 : 0;
  }
  if (command === 'case') {
    const missing = ['--source', '--ai', '--fixed', '--type', '--topic', '--id'].filter((name) => !option(name));
    if (missing.length) {
      console.error(`missing: ${missing.join(' ')}`);
      return 2;
    }
    const result = createCase({
      source: fs.readFileSync(option('--source'), 'utf8'), ai: fs.readFileSync(option('--ai'), 'utf8'),
      fixed: fs.readFileSync(option('--fixed'), 'utf8'), type: option('--type'), topic: option('--topic'),
      id: option('--id'), date: option('--date') || new Date().toISOString().slice(0, 10), note: option('--note'),
      expectedEdit: option('--expected-edit'),
      dir: option('--dir') || PAIRS_DIR,
    });
    console.log(`case written: ${result.dir}\nmust_not_contain: ${result.must_not_contain.length} (сузьте в meta.json до точной фразы)`);
    return 0;
  }
  console.error('usage: pairs.js validate [dir] | case --source f --ai f --fixed f --type GUIDE --topic t --id slug [--expected-edit none]');
  return 2;
}

if (require.main === module) {
  process.exitCode = main(process.argv);
}

module.exports = { validatePair, validateAll, loadPairs, createCase, rejectedSentences, regressionHits, PAIRS_DIR, TYPES };
