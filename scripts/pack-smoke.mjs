// Packs the library, installs the tarball into a throw-away project and
// imports both entry points from it, so a broken `exports` map or a file
// missing from `files` fails CI even when the source tests pass.
import { execFileSync } from 'node:child_process';
import { cpSync, mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const work = mkdtempSync(join(tmpdir(), 'hsreplay-pack-'));
const run = (command, args, cwd) =>
  execFileSync(command, args, { cwd, stdio: ['ignore', 'pipe', 'inherit'] }).toString();

try {
  run('pnpm', ['pack', '--pack-destination', work], root);
  const tarball = readdirSync(work).find((name) => name.endsWith('.tgz'));
  if (!tarball) throw new Error('pnpm pack produced no tarball');
  console.log(`packed ${tarball}`);

  const project = join(work, 'consumer');
  mkdirSync(project);
  writeFileSync(
    join(project, 'package.json'),
    JSON.stringify({ name: 'consumer', private: true, type: 'module' }),
  );
  cpSync(join(root, 'test.xml'), join(project, 'test.xml'));
  run('npm', ['install', '--no-audit', '--no-fund', '--silent', join(work, tarball)], project);

  writeFileSync(
    join(project, 'smoke.mjs'),
    `import { parseReplay, extractEvents, SemanticEventType } from '@manacost/hearthstone-replay';
import { parseReplayFile, parseReplayFileStream } from '@manacost/hearthstone-replay/node';
import { readFileSync } from 'node:fs';

const xml = readFileSync('test.xml', 'utf8');
const inMemory = parseReplay(xml);
const fromFile = await parseReplayFile('test.xml');
const streamed = await parseReplayFileStream('test.xml');
if (inMemory.packetCount !== fromFile.packetCount || fromFile.packetCount !== streamed.packetCount) {
  throw new Error('entry points disagree on the packet count');
}
const events = extractEvents(fromFile);
if (!events.some((event) => event.type === SemanticEventType.GAME_ENDED)) {
  throw new Error('no GAME_ENDED event from the packaged build');
}
console.log('package smoke test ok:', fromFile.packetCount, 'packets,', events.length, 'events');
`,
  );
  console.log(run('node', ['smoke.mjs'], project).trim());
} finally {
  rmSync(work, { recursive: true, force: true });
}
