#!/usr/bin/env node
// Слепая человеческая оценка настоящего A/B-прогона.
//
//   node evals/blind_review.js prepare результат.json --out build/blind
//     → pairs.json и pairs.md с парами A/B без названий вариантов,
//       key.json с ключом рандомизации (хранить отдельно от оценщика).
//   node evals/blind_review.js import build/blind/ratings.json --key build/blind/key.json --out build/blind
//     → report.json и report.md: средние оценки по вариантам и предпочтения.
//
// Пары «черновик → эталон» (evals/pairs, рубрика evals/rubric/interest.json):
//   node evals/blind_review.js pairs --out build/blind-pairs [--editor offline|prompt|pipeline|cmd]
//       [--editor-cmd "команда"] [--judge offline|api] [--real-only] [--swap-order]
//     → правка ИИ по каждой паре, слепые A/B (ИИ против эталона), LLM-судья и его метрика.
//   node evals/blind_review.js rate build/blind-pairs --reviewer имя
//     → владелец оценивает A/B в терминале; ответы сохраняются в ratings.json после каждой пары.
//   node evals/blind_review.js gate --baseline старый/report.json --candidate новый/report.json [--rater human|model]
//     → exit 0, только если доля пар «ИИ не хуже человека» выросла на том же наборе пар.
//
// Формат ratings.json:
//   [{"id":"corpus-05","A":{"readability":4,"naturalness":5,"usefulness":4,"voice":5},
//     "B":{...},"preferred":"A|B|tie","comment":""}]
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const readline = require('node:readline');
const { loadPairs, regressionHits, PAIRS_DIR } = require('./pairs.js');

const RUBRIC = JSON.parse(fs.readFileSync(path.join(__dirname, 'rubric/interest.json'), 'utf8'));
const RUBRIC_IDS = RUBRIC.criteria.map((c) => c.id);
const RUBRIC_LABELS = Object.fromEntries(RUBRIC.criteria.map((c) => [c.id, c.label]));
const CRITERIA = ['readability', 'naturalness', 'usefulness', 'voice', 'conditions', 'restraint'];
const CRITERIA_RU = {
  readability: 'читаемость', naturalness: 'естественность русского', usefulness: 'полезность для игрока', voice: 'сохранение авторского голоса',
  conditions: 'сохранность условий и исключений', restraint: 'обоснованность вмешательства в сильные фрагменты',
};

function loadResults(file) {
  const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
  const results = raw?.results?.results || raw?.results || [];
  return Array.isArray(results) ? results : [];
}

function variantOf(result) {
  const metadata = result.response?.metadata || {};
  if (metadata.comparison_variant) return metadata.comparison_variant;
  if (metadata.editorial_mode) return `${metadata.prompt_version || 'pipeline'}:${metadata.editorial_mode}:${metadata.retrieval_variant || 'unknown'}`;
  if (metadata.retrieval_variant) return metadata.retrieval_variant;
  const label = String(result.provider?.label || '');
  if (/без retrieval|no-retrieval/i.test(label)) return 'no-retrieval';
  if (/retrieval/i.test(label)) return 'retrieval';
  return String(result.prompt?.label || label || 'unknown');
}

function pairUp(results) {
  const byCase = new Map();
  for (const result of results) {
    const id = result.vars?.id ?? `test-${result.testIdx}`;
    if (!byCase.has(id)) byCase.set(id, {});
    const variant = variantOf(result);
    if (byCase.get(id)[variant]) throw new Error(`duplicate case/variant: ${id}/${variant}`);
    byCase.get(id)[variant] = result;
  }
  const pairs = [];
  for (const [id, variants] of byCase) {
    const names = Object.keys(variants);
    if (names.length !== 2) continue;
    const left = variants[names[0]].vars || {}, right = variants[names[1]].vars || {};
    if (['text', 'current_patch'].some(field => left[field] !== right[field])
      || JSON.stringify(left.research_handoff) !== JSON.stringify(right.research_handoff)) {
      throw new Error(`paired inputs differ: ${id}`);
    }
    pairs.push({ id, source: String(variants[names[0]].vars?.text || ''), variants: names, outputs: names.map((name) => String(variants[name].response?.output || '')) });
  }
  return pairs;
}

// randomBit использует криптографический источник: оценщик не должен
// угадывать сторону по порядку кейсов.
function randomBit() {
  return crypto.randomBytes(1)[0] % 2;
}

function prepare(file, outDir, random = randomBit, options = {}) {
  for (const name of ['pairs.json', 'key.json', 'pairs.md', 'ratings.template.json']) {
    if (fs.existsSync(path.join(outDir, name))) throw new Error(`frozen review output exists: ${name}`);
  }
  fs.mkdirSync(outDir, { recursive: true });
  const pairs = pairUp(loadResults(file));
  const criteria = options.criteria || CRITERIA;
  const labels = options.labels || CRITERIA_RU;
  const blind = [];
  const key = [];
  for (const pair of pairs) {
    const flip = random() === 1;
    const [first, second] = flip ? [1, 0] : [0, 1];
    blind.push({ id: pair.id, source: pair.source, A: pair.outputs[first], B: pair.outputs[second], criteria });
    key.push({ id: pair.id, A: pair.variants[first], B: pair.variants[second] });
    if (options.swapOrder) {
      const id = `${pair.id}::swapped`;
      blind.push({ id, source: pair.source, A: pair.outputs[second], B: pair.outputs[first], criteria });
      key.push({ id, case_id: pair.id, order: 'swapped', A: pair.variants[second], B: pair.variants[first] });
    }
  }
  fs.writeFileSync(path.join(outDir, 'pairs.json'), JSON.stringify(blind, null, 2) + '\n');
  fs.writeFileSync(path.join(outDir, 'key.json'), JSON.stringify({ created_at: new Date().toISOString(), source_file: path.basename(file),
    ...(options.protocol ? { protocol: options.protocol, criteria, labels, run: options.run || {} } : {}), pairs: key }, null, 2) + '\n');
  const lines = ['# Слепая оценка редактуры', '', 'Оцените каждую пару по шкале 1–5 и укажите, какой вариант предпочли (A, B или tie). Названия вариантов скрыты; ключ хранится отдельно.',
    'Подкрепите предпочтение конкретными фрагментами. Для пользы проверьте: что делать, почему, при каких условиях и когда выбрать иначе. Голос оценивается по связности мысли и узнаваемой позиции автора, а не счетчикам слов.',
    'Время измеряется отдельно: один редактор не получает последовательно обе версии одного материала. Используйте независимых редакторов и first_exposure. Переставленные пары — проверка устойчивости суждения, не замер скорости.',
    'Заполнять reviewed, reviewer и reviewed_at может только человек. Пустые строки остаются pending и не считаются ничьей. Модельный judge хранится отдельно.', '',
    ...(options.protocol === 'pairs' ? ['Исходник — черновик. Один из вариантов — правка человека, другой — правка ИИ. Рубрика «интересно / механично», 1 — механично, 5 — интересно:', '',
      ...RUBRIC.criteria.map((c) => `- ${c.label}: ${c.question}`), ''] : [])];
  for (const item of blind) {
    lines.push(`## ${item.id}`, '', '### Исходник', '', item.source, '', '### Вариант A', '', item.A, '', '### Вариант B', '', item.B, '');
    lines.push('| Критерий | A (1–5) | B (1–5) |', '| --- | --- | --- |');
    for (const criterion of criteria) lines.push(`| ${labels[criterion] || criterion} | | |`);
    lines.push('', 'Предпочтение: A / B / tie', '');
  }
  fs.writeFileSync(path.join(outDir, 'pairs.md'), lines.join('\n'));
  const template = blind.map((item) => ({ id: item.id, review_status: 'pending', reviewer: null, reviewed_at: null,
    A: Object.fromEntries(criteria.map((c) => [c, null])), B: Object.fromEntries(criteria.map((c) => [c, null])), preferred: null, evidence: [], comment: '' }));
  fs.writeFileSync(path.join(outDir, 'ratings.template.json'), JSON.stringify(template, null, 2) + '\n');
  return { pairs: blind.length, out: outDir };
}

function importRatings(ratingsFile, keyFile, outDir) {
  fs.mkdirSync(outDir, { recursive: true });
  const ratings = JSON.parse(fs.readFileSync(ratingsFile, 'utf8'));
  const key = JSON.parse(fs.readFileSync(keyFile, 'utf8'));
  if (!Array.isArray(ratings) || !Array.isArray(key.pairs)) throw new Error('ratings and key pairs must be arrays');
  if (new Set(key.pairs.map(row => row.id)).size !== key.pairs.length
    || key.pairs.some(row => typeof row.A !== 'string' || typeof row.B !== 'string' || row.A === row.B)) throw new Error('unique valid blind key required');
  const criteriaList = Array.isArray(key.criteria) && key.criteria.length ? key.criteria : CRITERIA;
  const labels = key.labels || CRITERIA_RU;
  const sides = new Map(key.pairs.map((item) => [item.id, item]));
  const totals = {};
  const preferences = {};
  let rated = 0;
  const skipped = [];
  const pending = [], observations = [], seen = new Set();
  let attested = 0;
  for (const rating of ratings) {
    const side = sides.get(rating.id);
    if (!side) {
      skipped.push(rating.id);
      continue;
    }
    if (rating.review_status === 'pending' || (rating.review_status === undefined && rating.preferred == null)) {
      pending.push(rating.id);
      continue;
    }
    if (rating.review_status !== undefined && !['reviewed', 'model'].includes(rating.review_status)) throw new Error('invalid review_status');
    const isHuman = rating.review_status === 'reviewed';
    const isModel = rating.review_status === 'model';
    if (isModel) {
      if (typeof rating.reviewer !== 'string' || !/^judge:\S/.test(rating.reviewer)) throw new Error('model reviewer must be judge:<model>');
      if (!Array.isArray(rating.evidence) || !rating.evidence.length || rating.evidence.some(value => typeof value !== 'string' || !value.trim())) throw new Error('specific evidence required');
    }
    if (isHuman) {
      if (typeof rating.reviewer !== 'string' || !rating.reviewer.trim()) throw new Error('human reviewer required');
      if (typeof rating.reviewed_at !== 'string' || !/(Z|[+-]\d\d:\d\d)$/.test(rating.reviewed_at) || !Number.isFinite(Date.parse(rating.reviewed_at))) throw new Error('reviewed_at ISO timestamp required');
      if (!Array.isArray(rating.evidence) || !rating.evidence.length || rating.evidence.some(value => typeof value !== 'string' || !value.trim())) throw new Error('specific evidence required');
      attested += 1;
    }
    const identity = JSON.stringify([rating.id, rating.reviewer || 'legacy']);
    if (seen.has(identity)) throw new Error('duplicate reviewer/presentation');
    seen.add(identity);
    if (!['A', 'B', 'tie'].includes(rating.preferred)) throw new Error('preferred must be A, B or tie');
    rated += 1;
    for (const letter of ['A', 'B']) {
      const variant = side[letter];
      totals[variant] = totals[variant] || Object.fromEntries(criteriaList.map((c) => [c, { sum: 0, count: 0 }]));
      for (const criterion of criteriaList) {
        const value = rating[letter]?.[criterion];
        if ((isHuman || isModel) && (!Number.isInteger(value) || value < 1 || value > 5)) throw new Error(`rating ${criterion} must be 1..5`);
        if (Number.isFinite(value) && value >= 1 && value <= 5) {
          totals[variant][criterion].sum += value;
          totals[variant][criterion].count += 1;
        }
      }
    }
    const preferred = String(rating.preferred || 'tie').toUpperCase();
    const winner = preferred === 'A' || preferred === 'B' ? side[preferred] : 'tie';
    preferences[winner] = (preferences[winner] || 0) + 1;
    observations.push({ case_id: side.case_id || side.id, presentation_id: side.id, order: side.order || 'original',
      reviewer: rating.reviewer || null, human_attested: isHuman, rater: isHuman ? 'human' : isModel ? 'model' : 'legacy', winner, evidence: rating.evidence || [], comment: rating.comment || '' });
  }
  const averages = {};
  for (const [variant, criteria] of Object.entries(totals)) {
    averages[variant] = {};
    for (const [criterion, total] of Object.entries(criteria)) {
      averages[variant][criterion] = total.count ? Number((total.sum / total.count).toFixed(2)) : null;
    }
  }
  const byCase = new Map();
  for (const observation of observations) {
    if (!byCase.has(observation.case_id)) byCase.set(observation.case_id, []);
    byCase.get(observation.case_id).push(observation);
  }
  const disagreements = [...byCase].filter(([, rows]) => new Set(rows.map(row => row.winner)).size > 1)
    .map(([case_id, rows]) => ({ case_id, observations: rows }));
  const modelRated = observations.filter((row) => row.rater === 'model').length;
  const metric = key.protocol === 'pairs'
    ? Object.fromEntries(['human', 'model'].map((rater) => [rater, aiNotWorse(observations, rater, key.run || {})]))
    : undefined;
  const report = { rated, skipped, pending, averages, preferences, observations, disagreements, ...(metric ? { metric, run: key.run || {} } : {}),
    human_attested_ratings: attested, human_review_status: attested ? 'recorded_requires_interpretation' : 'pending',
    legacy_unattested_ratings: rated - attested - modelRated, model_judge_ratings: modelRated, quality_improvement_confirmed: false, key_file: path.basename(keyFile) };
  fs.writeFileSync(path.join(outDir, 'report.json'), JSON.stringify(report, null, 2) + '\n');
  const lines = ['# Итог слепой оценки', '', `Записей: ${rated}; с подтверждением человека: ${attested}; ожидают: ${pending.length}; ${modelRated ? `LLM-судьи: ${modelRated}; ` : ''}старых без подтверждения: ${rated - attested - modelRated}.`,
    `Разногласий по материалам: ${disagreements.length}. Улучшение качества автоматически не подтверждается.`,
    ...(skipped.length ? [`Пропущено без ключа: ${skipped.join(', ')}`] : []),
    ...(metric ? ['', '## ИИ не хуже человека', '', ...Object.entries(metric).map(([rater, value]) => `- ${rater === 'human' ? 'владелец' : 'LLM-судья'}: ${metricLine(value)}`)] : []),
    '', '## Средние оценки (1–5)', '', `| Вариант | ${criteriaList.map((c) => labels[c] || c).join(' | ')} |`, `| --- | ${criteriaList.map(() => '---').join(' | ')} |`];
  for (const [variant, criteria] of Object.entries(averages)) {
    lines.push(`| ${variant} | ${criteriaList.map((c) => criteria[c] ?? '—').join(' | ')} |`);
  }
  lines.push('', '## Предпочтения', '');
  for (const [variant, count] of Object.entries(preferences)) lines.push(`- ${variant}: ${count}`);
  lines.push('');
  fs.writeFileSync(path.join(outDir, 'report.md'), lines.join('\n'));
  return report;
}

// Пара засчитывается, если по всем показам ИИ выиграл не реже человека
// (ничья — не хуже). Измерением считается только прогон настоящего
// редактора на парах владельца и не offline-судьёй.
function aiNotWorse(observations, rater, run) {
  const byCase = new Map();
  for (const row of observations) {
    if (row.rater !== rater) continue;
    const counts = byCase.get(row.case_id) || { ai: 0, human: 0, tie: 0 };
    counts[row.winner] = (counts[row.winner] || 0) + 1;
    byCase.set(row.case_id, counts);
  }
  if (!byCase.size) return null;
  const caseIds = [...byCase.keys()].sort();
  const notWorse = caseIds.filter((id) => byCase.get(id).ai >= byCase.get(id).human).length;
  const offlineJudge = rater === 'model' && observations.some((row) => row.rater === 'model' && row.reviewer === 'judge:offline');
  const synthetic = (run.synthetic_ids || []).filter((id) => byCase.has(id));
  return { cases: caseIds.length, ai_not_worse: notWorse, share: Number((notWorse / caseIds.length).toFixed(3)), case_ids: caseIds,
    synthetic_cases: synthetic.length, measured: run.editor !== undefined && run.editor !== 'offline' && !offlineJudge && !synthetic.length };
}

function metricLine(value) {
  if (!value) return 'нет оценок';
  const flag = value.measured ? '' : ' (НЕ ИЗМЕРЕНИЕ: offline-редактор/судья или синтетические пары)';
  return `${value.ai_not_worse}/${value.cases} = ${Math.round(value.share * 100)}%${flag}`;
}

async function runEditor(mode, pair, options = {}) {
  const { id, type } = pair.meta;
  if (mode === 'offline') return { output: pair.draft, metadata: { editor: 'offline-identity' } };
  if (mode === 'cmd') {
    if (!options.editorCmd) throw new Error('--editor-cmd is required for --editor cmd');
    const run = spawnSync(options.editorCmd, { shell: true, input: pair.draft, encoding: 'utf8',
      env: { ...process.env, PAIR_ID: id, PAIR_TYPE: type }, maxBuffer: 16 * 1024 * 1024 });
    if (run.error) throw run.error;
    if (run.status !== 0) throw new Error(`editor command failed for ${id} (exit ${run.status}): ${String(run.stderr).slice(0, 500)}`);
    if (!run.stdout.trim()) throw new Error(`editor command returned empty output for ${id}`);
    return { output: run.stdout.trim() + '\n', metadata: { editor: 'cmd' } };
  }
  if (mode === 'prompt' || mode === 'pipeline') {
    const { PROMPTS } = require('./providers/prompt-direct.js');
    const Provider = require(mode === 'prompt' ? './providers/prompt-direct.js' : './providers/pipeline-e2e.js');
    const result = await new Provider({ config: {} }).callApi(PROMPTS.candidate, { vars: { id, text: pair.draft, editorial_mode: type } });
    return { output: result.output, metadata: { editor: mode, ...result.metadata } };
  }
  throw new Error(`unknown editor mode: ${mode}`);
}

function judgePrompt() {
  return [
    'Ты слепой судья редактуры русскоязычных текстов о Hearthstone. Дан черновик и две отредактированные версии A и B.',
    'Не знаешь, кто их правил. Оцени каждую версию по рубрике «интересно / механично» целыми числами 1–5',
    `(1 — ${RUBRIC.scale.anchors['1']}; 5 — ${RUBRIC.scale.anchors['5']}):`,
    ...RUBRIC.criteria.map((c) => `- ${c.id}: ${c.question}`),
    'Затем выбери лучшую версию для игрока: "A", "B" или "tie". Порядок A/B случаен и ничего не значит.',
    'Новые факты, которых нет в черновике, — дефект, а не плюс.',
    'Ответь только JSON: {"A":{<критерий>:n,...},"B":{...},"preferred":"A|B|tie","evidence":["конкретный фрагмент и почему"]}',
  ].join('\n');
}

function parseJudgeReply(content) {
  const text = String(content || '');
  const start = text.indexOf('{'), end = text.lastIndexOf('}');
  if (start < 0 || end < start) throw new Error(`judge returned no JSON: ${text.slice(0, 200)}`);
  const reply = JSON.parse(text.slice(start, end + 1));
  for (const side of ['A', 'B']) for (const id of RUBRIC_IDS) {
    if (!Number.isInteger(reply[side]?.[id]) || reply[side][id] < 1 || reply[side][id] > 5) throw new Error(`judge ${side}.${id} must be 1..5`);
  }
  if (!['A', 'B', 'tie'].includes(reply.preferred)) throw new Error('judge preferred must be A, B or tie');
  if (!Array.isArray(reply.evidence) || !reply.evidence.some((item) => typeof item === 'string' && item.trim())) throw new Error('judge evidence required');
  return reply;
}

// OpenAI-совместимый судья; переменные EDITOR_EVAL_JUDGE_MODEL, _BASE_URL, _API_KEY.
async function apiJudge(item, env = process.env) {
  const model = env.EDITOR_EVAL_JUDGE_MODEL;
  if (!model) throw new Error('EDITOR_EVAL_JUDGE_MODEL is required for --judge api');
  const baseURL = (env.EDITOR_EVAL_JUDGE_BASE_URL || 'https://api.openai.com/v1').replace(/\/$/, '');
  const apiKey = env.EDITOR_EVAL_JUDGE_API_KEY || env.EDITOR_EVAL_API_KEY || env.OPENAI_API_KEY;
  const headers = { 'content-type': 'application/json', ...(apiKey ? { authorization: `Bearer ${apiKey}` } : {}) };
  const response = await fetch(`${baseURL}/chat/completions`, { method: 'POST', headers, body: JSON.stringify({ model, temperature: 0,
    messages: [{ role: 'system', content: judgePrompt() }, { role: 'user', content: `ЧЕРНОВИК:\n${item.source}\n\nВЕРСИЯ A:\n${item.A}\n\nВЕРСИЯ B:\n${item.B}` }] }) });
  const body = await response.json();
  if (!response.ok) throw new Error(`judge HTTP ${response.status}: ${JSON.stringify(body?.error || body).slice(0, 300)}`);
  return { model, reply: parseJudgeReply(body?.choices?.[0]?.message?.content) };
}

// offline-судья только проверяет протокол: всегда ничья, метрика помечается как не измерение.
async function offlineJudge() {
  const scores = Object.fromEntries(RUBRIC_IDS.map((id) => [id, 3]));
  return { model: 'offline', reply: { A: scores, B: scores, preferred: 'tie', evidence: ['offline: модель не вызывалась'] } };
}

async function runPairs(options = {}) {
  const outDir = options.outDir || 'build/blind-pairs';
  const editor = options.editor || 'offline';
  if (fs.existsSync(path.join(outDir, 'key.json'))) throw new Error(`frozen review output exists: ${outDir}`);
  let pairs = loadPairs(options.pairsDir || PAIRS_DIR);
  if (options.realOnly) pairs = pairs.filter((pair) => !pair.meta.synthetic);
  if (!pairs.length) throw new Error('no pairs to review (только синтетические? добавьте пары владельца)');
  // private/ раскрывает, где ИИ; владелец не открывает его до конца оценки.
  const privateDir = path.join(outDir, 'private');
  fs.mkdirSync(path.join(privateDir, 'ai'), { recursive: true });
  const results = [], log = [];
  for (const pair of pairs) {
    const edit = await runEditor(editor, pair, options);
    fs.writeFileSync(path.join(privateDir, 'ai', `${pair.meta.id}.md`), edit.output);
    const vars = { id: pair.meta.id, text: pair.draft, type: pair.meta.type };
    results.push({ vars, prompt: { label: 'human' }, response: { output: pair.reference } },
      { vars, prompt: { label: 'ai' }, response: { output: edit.output, metadata: edit.metadata } });
    log.push({ id: pair.meta.id, type: pair.meta.type, synthetic: pair.meta.synthetic, unchanged: edit.output.trim() === pair.draft.trim(),
      regression_hits: regressionHits(pair.meta, edit.output), editor_metadata: edit.metadata });
  }
  const resultsFile = path.join(privateDir, 'results.json');
  fs.writeFileSync(resultsFile, JSON.stringify({ results }, null, 2) + '\n');
  const run = { editor, judge: options.judgeFn ? 'custom' : options.judge || 'offline', synthetic_ids: pairs.filter((p) => p.meta.synthetic).map((p) => p.meta.id) };
  prepare(resultsFile, outDir, options.random || randomBit, { swapOrder: options.swapOrder, criteria: RUBRIC_IDS, labels: RUBRIC_LABELS, protocol: 'pairs', run });
  const judge = options.judgeFn || (run.judge === 'api' ? apiJudge : run.judge === 'offline' ? offlineJudge : null);
  if (!judge) throw new Error(`unknown judge mode: ${run.judge}`);
  const ratings = [];
  for (const item of JSON.parse(fs.readFileSync(path.join(outDir, 'pairs.json'), 'utf8'))) {
    const { model, reply } = await judge(item);
    ratings.push({ id: item.id, review_status: 'model', reviewer: `judge:${model}`, reviewed_at: new Date().toISOString(),
      A: reply.A, B: reply.B, preferred: reply.preferred, evidence: reply.evidence, comment: '' });
  }
  const judgeDir = path.join(outDir, 'judge');
  fs.mkdirSync(judgeDir, { recursive: true });
  fs.writeFileSync(path.join(judgeDir, 'ratings.json'), JSON.stringify(ratings, null, 2) + '\n');
  const judgeReport = importRatings(path.join(judgeDir, 'ratings.json'), path.join(outDir, 'key.json'), judgeDir);
  const summary = { pairs: pairs.length, run, regressions: log.filter((row) => row.regression_hits.length), editor_log: log, judge_metric: judgeReport.metric.model };
  fs.writeFileSync(path.join(privateDir, 'summary.json'), JSON.stringify(summary, null, 2) + '\n');
  return summary;
}

// Интерактивная слепая оценка владельцем. Показывает только pairs.json
// (без ключа), пишет ratings.json после каждой пары, повторный запуск
// продолжает с первой неоценённой.
async function rate(dir, io = {}) {
  const input = io.input || process.stdin, output = io.output || process.stdout;
  const blind = JSON.parse(fs.readFileSync(path.join(dir, 'pairs.json'), 'utf8'));
  const ratingsFile = path.join(dir, 'ratings.json');
  const ratings = fs.existsSync(ratingsFile) ? JSON.parse(fs.readFileSync(ratingsFile, 'utf8')) : [];
  const rl = readline.createInterface({ input, terminal: false });
  const lines = rl[Symbol.asyncIterator]();
  const ask = async (question, accept = (value) => value) => {
    for (;;) {
      output.write(question);
      const { value, done } = await lines.next();
      if (done) throw new Error('input ended; progress saved in ratings.json');
      const answer = accept(value.trim());
      if (answer !== undefined) return answer;
      output.write('  не понял, ещё раз\n');
    }
  };
  try {
    const reviewer = io.reviewer || await ask('Ваше имя: ', (value) => value || undefined);
    const done = new Set(ratings.filter((row) => row.reviewer === reviewer).map((row) => row.id));
    const score = (value) => (/^[1-5]$/.test(value) ? Number(value) : undefined);
    const todo = blind.filter((item) => !done.has(item.id));
    for (const [index, item] of todo.entries()) {
      const rubric = RUBRIC.criteria.filter((c) => item.criteria.includes(c.id));
      output.write(`\n===== ${index + 1}/${todo.length}: ${item.id} =====\n\n--- Черновик ---\n${item.source}\n\n--- A ---\n${item.A}\n\n--- B ---\n${item.B}\n\n`);
      const row = { id: item.id, review_status: 'reviewed', reviewer, reviewed_at: null, A: {}, B: {}, preferred: null, evidence: [], comment: '' };
      for (const criterion of rubric) {
        output.write(`${criterion.label}: ${criterion.question}\n`);
        for (const side of ['A', 'B']) row[side][criterion.id] = await ask(`  ${side} [1–5]: `, score);
      }
      row.preferred = await ask('Что лучше для игрока? A / B / tie: ', (value) => {
        const upper = value.toUpperCase();
        return upper === 'A' || upper === 'B' ? upper : upper === 'TIE' ? 'tie' : undefined;
      });
      row.evidence = [await ask('Почему (конкретный фрагмент): ', (value) => value || undefined)];
      row.comment = await ask('Комментарий (можно пусто): ');
      row.reviewed_at = (io.now ? io.now() : new Date()).toISOString();
      ratings.push(row);
      fs.writeFileSync(ratingsFile, JSON.stringify(ratings, null, 2) + '\n');
    }
    output.write(`\nГотово: ${ratings.length} оценок в ${ratingsFile}. Итог: node evals/blind_review.js import ${ratingsFile} --key ${path.join(dir, 'key.json')} --out ${path.join(dir, 'human')}\n`);
    return { rated: todo.length, file: ratingsFile };
  } finally {
    rl.close();
  }
}

// Правило редактуры принимается, только если метрика выросла на тех же парах.
function gate(baselineReport, candidateReport, rater = 'human') {
  const before = baselineReport.metric?.[rater], after = candidateReport.metric?.[rater];
  if (!before || !after) throw new Error(`metric.${rater} missing in report`);
  if (!before.measured || !after.measured) throw new Error('gate requires measured runs: real editor, real judge or owner, no synthetic pairs');
  if (JSON.stringify(before.case_ids) !== JSON.stringify(after.case_ids)) throw new Error('reports cover different pairs');
  return { accepted: after.share > before.share, rater, baseline: before.share, candidate: after.share, cases: after.cases };
}

function main(argv) {
  const [command, file] = argv.slice(2);
  const option = (name, fallback) => {
    const index = argv.indexOf(name);
    return index >= 0 && argv[index + 1] ? argv[index + 1] : fallback;
  };
  if (command === 'prepare' && file) {
    const result = prepare(file, option('--out', 'build/blind'), randomBit, {swapOrder: argv.includes('--swap-order')});
    console.log(`pairs: ${result.pairs}, written to ${result.out} (key.json хранить отдельно)`);
    return 0;
  }
  if (command === 'import' && file) {
    const outDir = option('--out', path.dirname(file));
    const result = importRatings(file, option('--key', path.join(outDir, 'key.json')), outDir);
    console.log(JSON.stringify(result, null, 2));
    return 0;
  }
  if (command === 'pairs') {
    return runPairs({ pairsDir: option('--pairs', PAIRS_DIR), outDir: option('--out', 'build/blind-pairs'), editor: option('--editor', 'offline'),
      editorCmd: option('--editor-cmd'), judge: option('--judge', 'offline'), realOnly: argv.includes('--real-only'), swapOrder: argv.includes('--swap-order') })
      .then((summary) => {
        const dir = option('--out', 'build/blind-pairs');
        console.log(`pairs: ${summary.pairs}; editor: ${summary.run.editor}; judge: ${summary.run.judge}`);
        console.log(`LLM-судья, ИИ не хуже человека: ${metricLine(summary.judge_metric)}`);
        if (summary.regressions.length) console.log(`регрессии (вернулись убранные владельцем фразы): ${summary.regressions.map((row) => row.id).join(', ')}`);
        console.log(`Главный сигнал — владелец: node evals/blind_review.js rate ${dir} --reviewer <имя>`);
        return 0;
      });
  }
  if (command === 'rate' && file) {
    return rate(file, { reviewer: option('--reviewer') }).then(() => 0);
  }
  if (command === 'gate') {
    const read = (name) => JSON.parse(fs.readFileSync(option(name), 'utf8'));
    const result = gate(read('--baseline'), read('--candidate'), option('--rater', 'human'));
    console.log(`${result.accepted ? 'ACCEPT' : 'REJECT'}: ${result.rater} ${result.baseline} → ${result.candidate} на ${result.cases} парах`);
    return result.accepted ? 0 : 1;
  }
  console.error('usage: blind_review.js prepare результат.json --out dir | import ratings.json --key key.json --out dir | pairs --out dir | rate dir | gate --baseline r.json --candidate r.json');
  return 2;
}

if (require.main === module) {
  Promise.resolve().then(() => main(process.argv)).then((code) => { process.exitCode = code; }, (error) => {
    console.error(error.stack || error);
    process.exitCode = 1;
  });
}

module.exports = { prepare, importRatings, pairUp, CRITERIA, RUBRIC, runPairs, rate, gate, parseJudgeReply, aiNotWorse };
