// Packs the library, installs the tarball into a throw-away project and
// checks it the way consumers use it: Node import of both entry points,
// TypeScript compilation against the shipped declarations, and a browser
// bundle of the core entry that must not pull in any node: module.
import { execFileSync } from 'node:child_process';
import {
  cpSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const work = mkdtempSync(join(tmpdir(), 'hsreplay-pack-'));
const run = (command, args, cwd) =>
  execFileSync(command, args, { cwd, stdio: ['ignore', 'pipe', 'inherit'] }).toString();
const FORBIDDEN_IN_TARBALL = [
  /^package\/\.claude\//,
  /^package\/test\//,
  /^package\/scripts\//,
  /^package\/coverage\//,
  /^package\/docs\//,
  /\.xml$/,
];

try {
  run('pnpm', ['pack', '--pack-destination', work], root);
  const tarball = readdirSync(work).find((name) => name.endsWith('.tgz'));
  if (!tarball) throw new Error('pnpm pack produced no tarball');
  const listing = run('tar', ['-tzf', join(work, tarball)])
    .trim()
    .split('\n');
  const leaked = listing.filter((entry) =>
    FORBIDDEN_IN_TARBALL.some((pattern) => pattern.test(entry)),
  );
  if (leaked.length > 0)
    throw new Error(`tarball contains files that must not ship:\n${leaked.join('\n')}`);
  console.log(
    `packed ${tarball} (${listing.length} entries, only dist/, README.md, LICENSE, package.json)`,
  );

  const project = join(work, 'consumer');
  mkdirSync(project);
  writeFileSync(
    join(project, 'package.json'),
    JSON.stringify({ name: 'consumer', private: true, type: 'module' }),
  );
  cpSync(join(root, 'test.xml'), join(project, 'test.xml'));
  run('npm', ['install', '--no-audit', '--no-fund', '--silent', join(work, tarball)], project);

  // 1. Node import of both entry points.
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
if (!events.some((event) => event.type === SemanticEventType.GAME_ENDED)) throw new Error('no GAME_ENDED event from the packaged build');
console.log('node import ok:', fromFile.packetCount, 'packets,', events.length, 'events');
`,
  );
  console.log(run('node', ['smoke.mjs'], project).trim());

  // 2. TypeScript compilation against the shipped declarations.
  writeFileSync(
    join(project, 'consumer.ts'),
    `import { parseReplay, extractEvents, type SemanticEvent, type Replay } from '@manacost/hearthstone-replay';
import { parseReplayFile } from '@manacost/hearthstone-replay/node';

export async function summarise(path: string): Promise<{ packets: number; events: SemanticEvent[] }> {
  const replay: Replay = await parseReplayFile(path);
  const again = parseReplay('<HSReplay version="1.7"><Game id="1"/></HSReplay>');
  return { packets: replay.packetCount + again.packetCount, events: extractEvents(replay) };
}
`,
  );
  writeFileSync(
    join(project, 'tsconfig.json'),
    JSON.stringify({
      compilerOptions: {
        module: 'NodeNext',
        moduleResolution: 'NodeNext',
        target: 'ES2022',
        strict: true,
        noEmit: true,
        skipLibCheck: false,
        types: ['node'],
      },
      files: ['consumer.ts'],
    }),
  );
  const typescriptVersion = JSON.parse(
    readFileSync(join(root, 'node_modules', 'typescript', 'package.json'), 'utf8'),
  ).version;
  const typesNodeVersion = JSON.parse(
    readFileSync(join(root, 'node_modules', '@types', 'node', 'package.json'), 'utf8'),
  ).version;
  run(
    'npm',
    [
      'install',
      '--no-audit',
      '--no-fund',
      '--silent',
      '--save-dev',
      `typescript@${typescriptVersion}`,
      `@types/node@${typesNodeVersion}`,
    ],
    project,
  );
  run(
    'node',
    [join(project, 'node_modules', 'typescript', 'bin', 'tsc'), '-p', 'tsconfig.json'],
    project,
  );
  console.log('typescript compile ok');

  // 3. Browser bundle of the core entry: no node: imports may remain.
  const esbuild = await import(join(root, 'node_modules', 'esbuild', 'lib', 'main.js'));
  const result = await esbuild.build({
    stdin: {
      contents: `import { parseReplay, extractEvents } from '@manacost/hearthstone-replay'; console.log(extractEvents(parseReplay('<HSReplay version="1.7"><Game id="1"/></HSReplay>')).length);`,
      resolveDir: project,
      loader: 'js',
    },
    bundle: true,
    platform: 'browser',
    format: 'esm',
    write: false,
    logLevel: 'silent',
    metafile: true,
  });
  const inputs = Object.keys(result.metafile.inputs);
  const nodeBuiltins = inputs.filter(
    (input) => input.startsWith('node:') || /^(fs|path|crypto|stream|zlib|os)$/.test(input),
  );
  if (nodeBuiltins.length > 0)
    throw new Error(`core bundle references Node built-ins: ${nodeBuiltins.join(', ')}`);
  const text = result.outputFiles[0].text;
  if (/\bnode:[a-z]/.test(text) || /require\(["'](fs|path|crypto)["']\)/.test(text))
    throw new Error('core bundle still contains node: specifiers');
  console.log(
    `browser bundle ok: ${(text.length / 1024).toFixed(0)} KB, ${inputs.length} modules, no Node built-ins`,
  );
} finally {
  rmSync(work, { recursive: true, force: true });
}
