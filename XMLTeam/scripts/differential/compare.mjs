// Compares this library with python-hsreplay over the corpus (or given files).
//
//   PYTHON=.venv/bin/python node scripts/differential/compare.mjs [--report-dir DIR] [replay.xml ...]
//
// Every file ends in one of four outcomes:
//   MATCH                  both sides agree
//   DIVERGENCE             both parse, results differ            → failure
//   OUR_FAILURE            this library cannot parse the file     → failure
//   REFERENCE_UNSUPPORTED  the reference cannot parse the file    → failure unless the manifest
//                          entry lists REFERENCE_UNSUPPORTED in knownAnomalies
// Writes differential-report.json and differential-report.md when --report-dir is given.
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = fileURLToPath(new URL('.', import.meta.url));
const python = process.env.PYTHON ?? 'python3';
const args = process.argv.slice(2);
const reportDirIndex = args.indexOf('--report-dir');
const reportDir = reportDirIndex >= 0 ? args.splice(reportDirIndex, 2)[1] : undefined;

const manifestUrl = new URL('../../test/corpus/manifest.json', import.meta.url);
const manifest = JSON.parse(readFileSync(manifestUrl, 'utf8'));
const allowlist = new Set(
  manifest.entries
    .filter((e) => e.knownAnomalies.includes('REFERENCE_UNSUPPORTED'))
    .map((e) => fileURLToPath(new URL(e.file, manifestUrl))),
);
const files =
  args.length > 0
    ? args.map((file) => resolve(file))
    : manifest.entries.map((e) => fileURLToPath(new URL(e.file, manifestUrl)));

const results = [];
for (const file of files) {
  const label = file.split('/').slice(-2).join('/');
  const result = { file: label, outcome: 'MATCH', details: [] };
  let ours;
  let reference;
  try {
    ours = JSON.parse(
      execFileSync('node', [`${here}dump-ours.mjs`, file], { maxBuffer: 1 << 28 }).toString(),
    );
  } catch (error) {
    result.outcome = 'OUR_FAILURE';
    result.details = [String(error.message).split('\n')[0]];
    results.push(result);
    continue;
  }
  try {
    reference = JSON.parse(
      execFileSync(python, [`${here}dump-reference.py`, file], {
        maxBuffer: 1 << 28,
        stdio: ['ignore', 'pipe', 'pipe'],
      }).toString(),
    );
  } catch (error) {
    result.outcome = 'REFERENCE_UNSUPPORTED';
    result.allowlisted = allowlist.has(file);
    result.details = [
      String(error.stderr ?? error.message)
        .trim()
        .split('\n')
        .slice(-1)[0],
    ];
    results.push(result);
    continue;
  }
  const differences = compareDocuments(ours, reference);
  if (differences.length > 0) {
    result.outcome = 'DIVERGENCE';
    result.details = differences.slice(0, 20);
  } else {
    result.details = [
      `entities=${ours.games[0]?.entities.length ?? 0} packets=${ours.games[0]?.packets.length ?? 0}`,
    ];
  }
  results.push(result);
}

const summary = {
  MATCH: 0,
  DIVERGENCE: 0,
  REFERENCE_UNSUPPORTED: 0,
  REFERENCE_UNSUPPORTED_ALLOWLISTED: 0,
  OUR_FAILURE: 0,
};
for (const r of results) {
  if (r.outcome === 'REFERENCE_UNSUPPORTED' && r.allowlisted)
    summary.REFERENCE_UNSUPPORTED_ALLOWLISTED++;
  else summary[r.outcome]++;
  const tag = r.outcome + (r.allowlisted ? ' (allowlisted)' : '');
  console.log(`${r.file}\t${tag}\t${r.details[0] ?? ''}`);
  if (r.outcome === 'DIVERGENCE') for (const d of r.details.slice(1, 12)) console.log(`    ${d}`);
}
console.log(JSON.stringify(summary));
const failed = summary.DIVERGENCE + summary.OUR_FAILURE + summary.REFERENCE_UNSUPPORTED;

if (reportDir) {
  mkdirSync(reportDir, { recursive: true });
  const versions = referenceVersions();
  const report = { generatedAt: new Date().toISOString(), python: versions, summary, results };
  writeFileSync(
    join(reportDir, 'differential-report.json'),
    `${JSON.stringify(report, null, 2)}\n`,
  );
  const rows = results.map(
    (r) =>
      `| ${r.file} | ${r.outcome}${r.allowlisted ? ' (allowlisted)' : ''} | ${(r.details[0] ?? '').replace(/\|/g, '\\|')} |`,
  );
  writeFileSync(
    join(reportDir, 'differential-report.md'),
    `# Differential report\n\n${report.generatedAt} · reference: ${versions}\n\n| outcome | files |\n| --- | ---: |\n${Object.entries(
      summary,
    )
      .map(([k, v]) => `| ${k} | ${v} |`)
      .join('\n')}\n\n| file | outcome | detail |\n| --- | --- | --- |\n${rows.join('\n')}\n`,
  );
}
process.exit(failed === 0 ? 0 : 1);

function referenceVersions() {
  try {
    return execFileSync(python, [
      '-c',
      'import importlib.metadata as m; print(", ".join(f"{p} {m.version(p)}" for p in ("hsreplay","hslog","hearthstone")))',
    ])
      .toString()
      .trim();
  } catch {
    return 'unknown';
  }
}

function compareDocuments(ours, reference) {
  const out = [];
  if (ours.games.length !== reference.games.length)
    out.push(`game count ${ours.games.length} vs ${reference.games.length}`);
  ours.games.forEach((game, index) => {
    const other = reference.games[index];
    if (!other) return;
    out.push(...compareGame(game, other).map((line) => `game ${index}: ${line}`));
  });
  return out;
}

function compareGame(ours, reference) {
  const out = [];
  if (JSON.stringify(ours.players) !== JSON.stringify(reference.players))
    out.push(`players ${JSON.stringify(ours.players)} vs ${JSON.stringify(reference.players)}`);
  if (JSON.stringify(ours.result) !== JSON.stringify(reference.result))
    out.push(`result ${JSON.stringify(ours.result)} vs ${JSON.stringify(reference.result)}`);
  const ourEntities = new Map(ours.entities.map((e) => [e.id, e]));
  const refEntities = new Map(reference.entities.map((e) => [e.id, e]));
  for (const id of new Set([...ourEntities.keys(), ...refEntities.keys()])) {
    const a = ourEntities.get(id);
    const b = refEntities.get(id);
    if (!a || !b) {
      out.push(`entity ${id} only in ${a ? 'ours' : 'reference'}`);
      continue;
    }
    if (a.cardId !== b.cardId) out.push(`entity ${id} cardId ${a.cardId} vs ${b.cardId}`);
    for (const tag of new Set([...Object.keys(a.tags), ...Object.keys(b.tags)])) {
      if (a.tags[tag] !== b.tags[tag])
        out.push(`entity ${id} tag ${tag}: ${a.tags[tag]} vs ${b.tags[tag]}`);
    }
  }
  const length = Math.min(ours.packets.length, reference.packets.length);
  if (ours.packets.length !== reference.packets.length)
    out.push(`packet count ${ours.packets.length} vs ${reference.packets.length}`);
  for (let i = 0; i < length; i++) {
    const a = JSON.stringify(ours.packets[i]);
    const b = JSON.stringify(reference.packets[i]);
    if (a !== b) {
      out.push(`packet #${i}: ${a} vs ${b}`);
      if (out.length > 40) break;
    }
  }
  return out;
}
