import fc from 'fast-check';
import { describe, expect, it } from 'vitest';

import './setup.js';
import {
  flattenPackets,
  isContainerPacket,
  parseReplayDocument,
  parseReplayStream,
  type ReplayDocument,
  walkPackets,
} from '../../src/index.js';
import { chunking, gameXml, modelGame, splitBytes, toExpectedPackets } from './arbitraries.js';

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

describe('parser properties', () => {
  it('parses a serialised model back to the model, with pre-order indexes (roundtrip)', () => {
    fc.assert(
      fc.property(modelGame, (game) => {
        const replay = parseReplayDocument(gameXml(game)).games[0]!;
        expect(replay.packets).toEqual(toExpectedPackets(game));
        expect(replay.metadata.players[0]?.name).toBe(game.playerName);
        expect(replay.diagnostics.filter((d) => d.level === 'error')).toEqual([]);
      }),
    );
  });

  it('flattens to unique, gap-free indexes in document order (invariant)', () => {
    fc.assert(
      fc.property(modelGame, (game) => {
        const replay = parseReplayDocument(gameXml(game)).games[0]!;
        const flat = flattenPackets(replay.packets);
        expect(flat.map((packet) => packet.index)).toEqual(flat.map((_, position) => position));
        expect(flat).toHaveLength(replay.packetCount);
        for (const { packet, parent, depth } of walkPackets(replay.packets)) {
          if (parent) {
            expect(packet.index).toBeGreaterThan(parent.index);
            expect(depth).toBeGreaterThan(0);
          }
          if (isContainerPacket(packet)) {
            const descendants = flattenPackets(packet.children);
            const last = descendants.at(-1);
            if (last) expect(last.index - packet.index).toBe(descendants.length);
          }
        }
      }),
    );
  });

  it('streams to the same document for any byte chunking, including splits inside UTF-8 sequences and tags (oracle)', async () => {
    await fc.assert(
      fc.asyncProperty(
        modelGame.chain((game) => {
          const bytes = new TextEncoder().encode(gameXml(game));
          return fc.tuple(
            fc.constant(game),
            fc.constant(bytes),
            fc.oneof(chunking(bytes.length, 64), chunking(bytes.length, 4096)),
          );
        }),
        async ([game, bytes, cuts]) => {
          const expected = comparable(parseReplayDocument(gameXml(game)));
          const streamed = await parseReplayStream(splitBytes(bytes, cuts));
          expect(comparable(streamed)).toEqual(expected);
        },
      ),
      { numRuns: 150 },
    );
  });

  it('streams one byte at a time to the same document (oracle)', async () => {
    await fc.assert(
      fc.asyncProperty(modelGame, async (game) => {
        const xml = gameXml(game);
        const bytes = new TextEncoder().encode(xml);
        const chunks = Array.from(bytes, (byte) => Uint8Array.of(byte));
        expect(comparable(await parseReplayStream(chunks))).toEqual(
          comparable(parseReplayDocument(xml)),
        );
      }),
      { numRuns: 25 },
    );
  });

  it('is deterministic across repeated parses of the same input', () => {
    fc.assert(
      fc.property(modelGame, (game) => {
        const xml = gameXml(game);
        expect(comparable(parseReplayDocument(xml))).toEqual(comparable(parseReplayDocument(xml)));
      }),
      { numRuns: 30 },
    );
  });
});
