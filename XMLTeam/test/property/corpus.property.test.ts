import { readFileSync } from 'node:fs';
import fc from 'fast-check';
import { describe, expect, it } from 'vitest';

import './setup.js';
import {
  createTimeline,
  isStrictViolation,
  parseReplayDocument,
  parseReplayStream,
  type ReplayDocument,
} from '../../src/index.js';
import { loadManifest, resolveCorpusPath } from '../corpus/manifest.js';
import { chunking, splitBytes } from './arbitraries.js';

/** A few real replays of different eras and sizes; the full corpus is covered by fixed chunking in test/corpus. */
const SAMPLE = [
  'edge/hslog.xml',
  'edge/no_block.annotated.xml',
  'converted/puzzle_player.xml',
  'edge/battlegrounds_short_game.annotated.hsreplay.xml',
  'mercenaries/mercenaries_pve.annotated.xml',
];

function comparable(document: ReplayDocument): unknown {
  return {
    version: document.version,
    build: document.build,
    diagnostics: document.diagnostics,
    games: document.games.map((game) => ({
      metadata: game.metadata,
      packets: game.packets,
      packetCount: game.packetCount,
      diagnostics: game.diagnostics,
      entities: [...game.entities].map((entity) => [
        entity.id,
        entity.cardId,
        [...entity.tags],
        entity.player,
      ]),
    })),
  };
}

const entries = loadManifest().entries.filter((entry) => SAMPLE.includes(entry.file));

describe('corpus properties', () => {
  it('samples every listed replay', () => {
    expect(entries.map((entry) => entry.file).sort()).toEqual([...SAMPLE].sort());
  });

  it.each(entries.map((entry) => [entry.file, entry] as const))(
    '%s streams identically under random byte chunking (oracle)',
    async (_file, entry) => {
      const xml = readFileSync(resolveCorpusPath(entry), 'utf8');
      const bytes = new TextEncoder().encode(xml);
      const expected = comparable(parseReplayDocument(xml));
      await fc.assert(
        fc.asyncProperty(
          fc.oneof(
            chunking(bytes.length, 64),
            chunking(bytes.length, 4096),
            chunking(bytes.length, 65536),
          ),
          async (cuts) => {
            expect(comparable(await parseReplayStream(splitBytes(bytes, cuts)))).toEqual(expected);
          },
        ),
        { numRuns: 12 },
      );
    },
  );

  it.each(entries.map((entry) => [entry.file, entry] as const))(
    '%s: the state at a random packet does not depend on the checkpoint interval (oracle)',
    (_file, entry) => {
      const game = parseReplayDocument(readFileSync(resolveCorpusPath(entry), 'utf8')).games[0]!;
      const reference = createTimeline(game, { checkpointInterval: 1 });
      fc.assert(
        fc.property(
          fc.integer({ min: -1, max: game.packetCount - 1 }),
          fc.integer({ min: 1, max: Math.max(1, game.packetCount) }),
          (index, interval) => {
            const timeline = createTimeline(game, { checkpointInterval: interval });
            const dump = (state: ReturnType<typeof timeline.stateAt>) =>
              [...state.entities].map((entity) => [entity.id, entity.cardId, [...entity.tags]]);
            expect(dump(timeline.stateAt(index))).toEqual(dump(reference.stateAt(index)));
          },
        ),
        { numRuns: 20 },
      );
    },
  );

  it('parses every sampled file identically in strict mode when lenient mode recorded no violation', () => {
    for (const entry of entries) {
      const xml = readFileSync(resolveCorpusPath(entry), 'utf8');
      const lenient = parseReplayDocument(xml);
      const violated = [
        ...lenient.diagnostics,
        ...lenient.games.flatMap((g) => g.diagnostics),
      ].some(isStrictViolation);
      if (!violated)
        expect(comparable(parseReplayDocument(xml, { strict: true }))).toEqual(comparable(lenient));
    }
  });
});
