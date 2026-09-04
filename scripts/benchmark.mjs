// Reproducible baseline, not a performance gate. Run after `pnpm build`.
// Usage: node scripts/benchmark.mjs [replay.xml] [iterations]
import { readFileSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { extractEvents, parseReplay, parseReplayStream } from '../dist/index.js';

const path = process.argv[2] ?? fileURLToPath(new URL('../test.xml', import.meta.url));
const iterations = Number(process.argv[3] ?? 20);
const xml = readFileSync(path, 'utf8');
const bytes = statSync(path).size;
const megabytes = bytes / 1_048_576;

function* chunks(text, size) {
  for (let offset = 0; offset < text.length; offset += size)
    yield text.slice(offset, offset + size);
}

async function measure(label, action) {
  await action();
  const samples = [];
  for (let i = 0; i < iterations; i++) {
    const start = performance.now();
    await action();
    samples.push(performance.now() - start);
  }
  samples.sort((a, b) => a - b);
  const median = samples[Math.floor(samples.length / 2)];
  const min = samples[0];
  console.log(
    `${label.padEnd(18)} median ${median.toFixed(1).padStart(7)} ms   min ${min.toFixed(1).padStart(7)} ms   ${(megabytes / (median / 1000)).toFixed(1).padStart(6)} MB/s`,
  );
  return median;
}

const replay = parseReplay(xml);
console.log(`file        ${path}`);
console.log(`size        ${bytes} bytes (${megabytes.toFixed(2)} MB)`);
console.log(`packets     ${replay.packetCount}   entities ${replay.entities.size}`);
console.log(`iterations  ${iterations}   node ${process.version}`);
await measure('parse', () => parseReplay(xml));
await measure('parse (stream 64k)', () => parseReplayStream(chunks(xml, 65536)));
await measure('extractEvents', () => extractEvents(replay));
if (globalThis.gc) {
  globalThis.gc();
  const before = process.memoryUsage().heapUsed;
  const kept = parseReplay(xml);
  globalThis.gc();
  const after = process.memoryUsage().heapUsed;
  console.log(
    `heap        ${((after - before) / 1_048_576).toFixed(1)} MB retained by one parsed replay (${kept.packetCount} packets)`,
  );
} else {
  console.log(
    'heap        run with `node --expose-gc scripts/benchmark.mjs` to measure retained memory',
  );
}
