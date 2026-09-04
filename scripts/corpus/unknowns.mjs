// Compares the unknowns of the current corpus with a recorded baseline, so a
// Hearthstone patch (new fixtures) shows exactly what the library has not
// named yet.  pnpm corpus:unknowns            → diff against the baseline
//             pnpm corpus:unknowns --update   → rewrite the baseline
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { analyzeUnknowns, parseReplayDocument } from '../../dist/index.js';
import { loadManifest, MANIFEST_URL } from './lib.mjs';

const baselinePath = fileURLToPath(
  new URL('../../docs/generated/unknowns-baseline.json', import.meta.url),
);
const update = process.argv.includes('--update');
const manifest = loadManifest();
const labeled = [];
for (const entry of manifest.entries) {
  const document = parseReplayDocument(
    readFileSync(fileURLToPath(new URL(entry.file, MANIFEST_URL)), 'utf8'),
  );
  for (const game of document.games)
    labeled.push({
      label: entry.file,
      packets: game.packets,
      ...(entry.build === null ? {} : { build: entry.build }),
    });
}
const report = analyzeUnknowns(labeled);
const current = {};
for (const bucket of ['nodes', 'attributes', 'children', 'tags', 'enumValues']) {
  current[bucket] = Object.fromEntries(
    Object.entries(report[bucket]).map(([key, v]) => [
      key,
      {
        count: v.count,
        files: v.fileCount,
        firstBuild: v.firstBuild,
        lastBuild: v.lastBuild,
        firstFile: v.firstFile,
        samplePacketIndex: v.samplePacketIndex ?? null,
      },
    ]),
  );
}

if (update) {
  writeFileSync(
    baselinePath,
    `${JSON.stringify({ replayCount: report.replayCount, ...current }, null, 2)}\n`,
  );
  console.log(`baseline written to ${baselinePath}`);
  process.exit(0);
}

let baseline;
try {
  baseline = JSON.parse(readFileSync(baselinePath, 'utf8'));
} catch {
  console.log('no baseline yet; run with --update');
  process.exit(1);
}
let changes = 0;
for (const bucket of Object.keys(current)) {
  for (const [key, value] of Object.entries(current[bucket])) {
    const old = baseline[bucket]?.[key];
    if (!old) {
      changes++;
      console.log(
        `NEW  ${bucket} ${key}: count=${value.count} files=${value.files} builds=${value.firstBuild ?? 'null'}..${value.lastBuild ?? 'null'} first=${value.firstFile}#${value.samplePacketIndex ?? '-'}`,
      );
    } else if (old.count !== value.count || old.files !== value.files) {
      console.log(
        `GREW ${bucket} ${key}: count ${old.count}→${value.count} files ${old.files}→${value.files}`,
      );
    }
  }
  for (const key of Object.keys(baseline[bucket] ?? {})) {
    if (!current[bucket][key]) console.log(`GONE ${bucket} ${key}`);
  }
}
console.log(
  changes === 0 ? 'no new unknowns compared with the baseline' : `${changes} new unknown(s)`,
);
process.exit(changes === 0 ? 0 : 1);
