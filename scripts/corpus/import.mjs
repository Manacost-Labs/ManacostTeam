// Imports one or more replay files into the corpus with a manifest entry.
//
//   pnpm corpus:import ./replay.xml --source "<url>" --repository "<owner/repo>" --commit <sha> --license CC0-1.0 [--notes "..."] [--mode arena] [--edge] [--locale en_US] [--dry-run]
//
// Refuses licenses that are not on the accepted list, duplicates (by SHA-256)
// and files the parser cannot read without errors. Metadata comes from the
// file itself; features and anomalies are confirmed from the packets.
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, join } from 'node:path';
import { parseArgs } from 'node:util';

import {
  ACCEPTED_LICENSES,
  CORPUS_DIR,
  describeReplay,
  folderFor,
  gameMode,
  loadManifest,
  MANIFEST_URL,
  sha256,
} from './lib.mjs';

const { values, positionals } = parseArgs({
  allowPositionals: true,
  options: {
    source: { type: 'string' },
    repository: { type: 'string' },
    commit: { type: 'string' },
    license: { type: 'string' },
    notes: { type: 'string', default: '' },
    mode: { type: 'string' },
    locale: { type: 'string' },
    folder: { type: 'string' },
    edge: { type: 'boolean', default: false },
    'allow-errors': { type: 'boolean', default: false },
    'dry-run': { type: 'boolean', default: false },
  },
});

if (positionals.length === 0 || !values.source || !values.license) {
  console.error(
    'usage: corpus:import <file.xml ...> --source <url> --license <spdx> [--repository owner/repo] [--commit sha] [--notes ...] [--mode ...] [--folder ...] [--edge] [--locale ...] [--dry-run]',
  );
  process.exit(2);
}
if (!ACCEPTED_LICENSES.has(values.license)) {
  console.error(
    `license ${values.license} is not on the accepted list: ${[...ACCEPTED_LICENSES].join(', ')}`,
  );
  process.exit(2);
}

const manifest = loadManifest();
const known = new Map(manifest.entries.map((entry) => [entry.sha256, entry.file]));
let added = 0;

for (const file of positionals) {
  const bytes = readFileSync(file);
  const hash = sha256(bytes);
  const duplicate = known.get(hash);
  if (duplicate) {
    console.log(`skip ${basename(file)}: identical to ${duplicate}`);
    continue;
  }
  const xml = bytes.toString('utf8');
  let info;
  try {
    info = describeReplay(xml);
  } catch (error) {
    console.log(`skip ${basename(file)}: parser failed: ${error.message}`);
    continue;
  }
  if ((info.errorDiagnostics > 0 || info.unknownPackets > 0) && !values['allow-errors']) {
    console.log(
      `skip ${basename(file)}: ${info.errorDiagnostics} error diagnostics, ${info.unknownPackets} unknown packets (use --allow-errors to import as an edge case)`,
    );
    continue;
  }
  const mode = gameMode(info.gameType, info.formatType, values.mode);
  const folder = values.folder ?? folderFor(mode, values.edge);
  const target = `${folder}/${basename(file)}`;
  if (
    manifest.entries.some((entry) => entry.file === target) ||
    existsSync(join(CORPUS_DIR, target))
  ) {
    console.log(`skip ${basename(file)}: ${target} already exists with different content`);
    continue;
  }
  const entry = {
    file: target,
    source: values.source,
    sourceRepository: values.repository ?? null,
    sourceCommit: values.commit ?? null,
    license: values.license,
    hsreplayVersion: info.hsreplayVersion,
    build: info.build,
    gameType: info.gameType,
    formatType: info.formatType,
    gameMode: mode,
    locale: values.locale ?? null,
    annotated: info.annotated,
    features: info.features,
    notes: values.notes,
    sizeBytes: bytes.length,
    sha256: hash,
    knownAnomalies: info.knownAnomalies,
    duplicateOf: null,
    eventCounts: info.eventCounts,
  };
  console.log(
    `${values['dry-run'] ? 'would add' : 'add'} ${target}  build=${info.build ?? 'null'} mode=${mode ?? 'null'} features=${info.features.join(',')} anomalies=${info.knownAnomalies.join(',') || '-'}`,
  );
  if (!values['dry-run']) {
    mkdirSync(join(CORPUS_DIR, folder), { recursive: true });
    copyFileSync(file, join(CORPUS_DIR, target));
    manifest.entries.push(entry);
    known.set(hash, target);
  }
  added++;
}

if (!values['dry-run'] && added > 0) {
  manifest.entries.sort((a, b) => a.file.localeCompare(b.file));
  writeFileSync(MANIFEST_URL, `${JSON.stringify(manifest, null, 2)}\n`);
}
console.log(`${added} file(s) ${values['dry-run'] ? 'would be ' : ''}added`);
