// Compares this library with python-hsreplay over the corpus.
// Usage: PYTHON=/path/to/venv/bin/python node scripts/differential/compare.mjs [replay.xml ...]
// Without arguments every entry of test/corpus/manifest.json is compared.
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const here = fileURLToPath(new URL('.', import.meta.url));
const python = process.env.PYTHON ?? 'python3';
const files = process.argv.slice(2);
if (files.length === 0) {
  const manifest = JSON.parse(
    readFileSync(new URL('../../test/corpus/manifest.json', import.meta.url), 'utf8'),
  );
  for (const entry of manifest.entries)
    files.push(fileURLToPath(new URL(`../../test/corpus/${entry.file}`, import.meta.url)));
}

let failures = 0;
for (const file of files) {
  const label = file.split('/').slice(-2).join('/');
  let ours;
  let reference;
  try {
    ours = JSON.parse(
      execFileSync('node', [`${here}dump-ours.mjs`, file], { maxBuffer: 1 << 28 }).toString(),
    );
  } catch (error) {
    console.log(`${label}\tOURS FAILED\t${String(error.message).split('\n')[0]}`);
    failures++;
    continue;
  }
  try {
    reference = JSON.parse(
      execFileSync(python, [`${here}dump-reference.py`, file], { maxBuffer: 1 << 28 }).toString(),
    );
  } catch (error) {
    console.log(
      `${label}\tREFERENCE FAILED\t${
        String(error.stderr ?? error.message)
          .trim()
          .split('\n')
          .slice(-1)[0]
      }`,
    );
    continue;
  }
  const differences = compareDocuments(ours, reference);
  if (differences.length === 0) {
    console.log(
      `${label}\tOK\tentities=${ours.games[0]?.entities.length ?? 0} packets=${ours.games[0]?.packets.length ?? 0}`,
    );
  } else {
    failures++;
    console.log(`${label}\tDIFF`);
    for (const difference of differences.slice(0, 12)) console.log(`    ${difference}`);
    if (differences.length > 12) console.log(`    … ${differences.length - 12} more`);
  }
}
process.exit(failures === 0 ? 0 : 1);

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
