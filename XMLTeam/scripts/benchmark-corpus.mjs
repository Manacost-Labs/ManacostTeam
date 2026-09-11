// Parses the whole corpus once and reports throughput. Informational only.
// Usage: node --expose-gc scripts/benchmark-corpus.mjs
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { extractEvents, parseReplayDocument } from '../dist/index.js';

const manifestUrl = new URL('../test/corpus/manifest.json', import.meta.url);
const manifest = JSON.parse(readFileSync(manifestUrl, 'utf8'));
const files = manifest.entries.map((entry) => ({
  file: entry.file,
  xml: readFileSync(fileURLToPath(new URL(entry.file, manifestUrl)), 'utf8'),
}));
const totalBytes = files.reduce((sum, f) => sum + Buffer.byteLength(f.xml), 0);

let packets = 0;
let events = 0;
let games = 0;
let parseMs = 0;
let eventMs = 0;
const slowest = [];
for (const { file, xml } of files) {
  const start = performance.now();
  const document = parseReplayDocument(xml);
  const parsed = performance.now();
  for (const game of document.games) {
    games++;
    packets += game.packetCount;
    events += extractEvents(game).length;
  }
  const done = performance.now();
  parseMs += parsed - start;
  eventMs += done - parsed;
  slowest.push({ file, ms: done - start, bytes: Buffer.byteLength(xml) });
}
slowest.sort((a, b) => b.ms - a.ms);
const megabytes = totalBytes / 1_048_576;
console.log(`files       ${files.length}   games ${games}`);
console.log(
  `total       ${megabytes.toFixed(1)} MB   packets ${packets.toLocaleString('en-US')}   events ${events.toLocaleString('en-US')}`,
);
console.log(
  `parse       ${parseMs.toFixed(0)} ms   ${(megabytes / (parseMs / 1000)).toFixed(1)} MB/s`,
);
console.log(
  `events      ${eventMs.toFixed(0)} ms   ${Math.round(events / (eventMs / 1000)).toLocaleString('en-US')} events/s`,
);
console.log(`wall        ${(parseMs + eventMs).toFixed(0)} ms   node ${process.version}`);
console.log(
  'slowest     ' +
    slowest
      .slice(0, 3)
      .map((s) => `${s.file} ${s.ms.toFixed(0)} ms (${(s.bytes / 1_048_576).toFixed(1)} MB)`)
      .join('; '),
);
