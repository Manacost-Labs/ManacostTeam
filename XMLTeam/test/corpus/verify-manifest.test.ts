import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { expect, it } from 'vitest';

it('finishes manifest verification and preserves success and mismatch exit codes', () => {
  const root = mkdtempSync(join(tmpdir(), 'xml-manifest-'));
  try {
    const scripts = join(root, 'scripts', 'corpus');
    const corpus = join(root, 'test', 'corpus');
    mkdirSync(scripts, { recursive: true });
    mkdirSync(corpus, { recursive: true });
    const script = join(scripts, 'verify-manifest.mjs');
    copyFileSync(new URL('../../scripts/corpus/verify-manifest.mjs', import.meta.url), script);
    const xml = '<HSReplay>\n</HSReplay>\n';
    writeFileSync(join(corpus, 'replay.xml'), xml.replaceAll('\n', '\r\n'));
    writeFileSync(
      join(corpus, 'manifest.json'),
      JSON.stringify({
        entries: [{ file: 'replay.xml', sha256: createHash('sha256').update(xml).digest('hex') }],
      }),
    );
    const accepted = spawnSync(process.execPath, [script], { encoding: 'utf8', timeout: 5000 });
    expect(accepted.error).toBeUndefined();
    expect(accepted.status).toBe(0);
    expect(accepted.stdout).toContain('1 replays, 0 checksum mismatches');

    writeFileSync(join(corpus, 'replay.xml'), '<HSReplay>changed</HSReplay>');
    const rejected = spawnSync(process.execPath, [script], { encoding: 'utf8', timeout: 5000 });
    expect(rejected.error).toBeUndefined();
    expect(rejected.status).toBe(1);
    expect(rejected.stdout).toContain('MISMATCH replay.xml');
    expect(rejected.stdout).toContain('1 replays, 1 checksum mismatches');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
