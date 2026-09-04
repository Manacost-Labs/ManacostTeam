// Reproducible baseline, not a performance gate. Run after `pnpm build`.
// Usage: node --expose-gc scripts/benchmark.mjs [replay.xml] [iterations]
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

async function measure(label, action, unit) {
  await action();
  const samples = [];
  for (let i = 0; i < iterations; i++) {
    const start = performance.now();
    await action();
    samples.push(performance.now() - start);
  }
  samples.sort((a, b) => a - b);
  const median = samples[Math.floor(samples.length / 2)];
  console.log(
    `${label.padEnd(20)} median ${median.toFixed(1).padStart(7)} ms   min ${samples[0].toFixed(1).padStart(7)} ms   ${unit(median).padStart(16)}`,
  );
  return median;
}

const replay = parseReplay(xml);
const events = extractEvents(replay);
console.log(`file        ${path}`);
console.log(`size        ${bytes} bytes (${megabytes.toFixed(2)} MB)`);
console.log(
  `packets     ${replay.packetCount}   entities ${replay.entities.size}   events ${events.length}`,
);
console.log(`iterations  ${iterations}   node ${process.version}`);
await measure(
  'parse',
  () => parseReplay(xml),
  (ms) => `${(megabytes / (ms / 1000)).toFixed(1)} MB/s`,
);
await measure(
  'parse (stream 64k)',
  () => parseReplayStream(chunks(xml, 65536)),
  (ms) => `${(megabytes / (ms / 1000)).toFixed(1)} MB/s`,
);
await measure(
  'extractEvents',
  () => extractEvents(replay),
  (ms) => `${Math.round(events.length / (ms / 1000)).toLocaleString('en-US')} events/s`,
);
if (globalThis.gc) {
  globalThis.gc();
  const before = process.memoryUsage().heapUsed;
  let peak = before;
  const kept = parseReplay(xml);
  peak = Math.max(peak, process.memoryUsage().heapUsed);
  const keptEvents = extractEvents(kept);
  peak = Math.max(peak, process.memoryUsage().heapUsed);
  globalThis.gc();
  const after = process.memoryUsage().heapUsed;
  console.log(
    `heap        retained ${((after - before) / 1_048_576).toFixed(1)} MB by one parsed replay + ${keptEvents.length} events; peak delta ${((peak - before) / 1_048_576).toFixed(1)} MB`,
  );
} else {
  console.log(
    'heap        run with `node --expose-gc scripts/benchmark.mjs` to measure retained and peak memory',
  );
}
