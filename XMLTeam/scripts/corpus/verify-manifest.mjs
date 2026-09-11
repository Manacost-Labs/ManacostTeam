// Verifies that every corpus file matches its manifest checksum and prints a summary.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const manifestUrl = new URL('../../test/corpus/manifest.json', import.meta.url);
const manifest = JSON.parse(readFileSync(manifestUrl, 'utf8'));
let bad = 0;
const modes = {};
const builds = new Set();
for (const entry of manifest.entries) {
  const path = fileURLToPath(new URL(entry.file, manifestUrl));
  const sha = createHash('sha256').update(readFileSync(path)).digest('hex');
  if (sha !== entry.sha256) {
    bad++;
    console.log(`MISMATCH ${entry.file}`);
  }
  modes[entry.gameMode ?? 'unknown'] = (modes[entry.gameMode ?? 'unknown'] ?? 0) + 1;
  if (entry.build !== null) builds.add(entry.build);
}
console.log(`${manifest.entries.length} replays, ${bad} checksum mismatches`);
console.log('modes:', modes);
console.log('builds:', [...builds].sort((a, b) => a - b).join(', '));
process.exit(bad === 0 ? 0 : 1);
