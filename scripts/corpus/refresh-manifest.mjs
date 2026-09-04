// Recomputes every derived manifest field (metadata from the file, features,
// anomalies, event counts, annotated flag) without moving files. Run after a
// rule change or a parser fix:  pnpm corpus:refresh
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describeReplay, loadManifest, MANIFEST_URL } from './lib.mjs';

const manifest = loadManifest();
let changed = 0;
for (const entry of manifest.entries) {
  const xml = readFileSync(fileURLToPath(new URL(entry.file, MANIFEST_URL)), 'utf8');
  const info = describeReplay(xml);
  const before = JSON.stringify([
    entry.features,
    entry.knownAnomalies,
    entry.eventCounts,
    entry.annotated,
  ]);
  const keepAnomalies = entry.knownAnomalies.filter((a) => a === 'REFERENCE_UNSUPPORTED');
  entry.hsreplayVersion = info.hsreplayVersion;
  entry.build = info.build;
  entry.gameType = info.gameType;
  entry.formatType = info.formatType;
  entry.features = info.features;
  entry.knownAnomalies = [...new Set([...info.knownAnomalies, ...keepAnomalies])].sort();
  entry.eventCounts = info.eventCounts;
  entry.annotated = info.annotated;
  if (
    before !==
    JSON.stringify([entry.features, entry.knownAnomalies, entry.eventCounts, entry.annotated])
  ) {
    changed++;
    console.log(`updated ${entry.file}`);
  }
}
writeFileSync(MANIFEST_URL, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`${changed} entries changed`);
