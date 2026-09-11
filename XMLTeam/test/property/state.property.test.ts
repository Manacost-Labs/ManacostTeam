import fc from 'fast-check';
import { describe, expect, it } from 'vitest';

import './setup.js';
import { DiagnosticCollector } from '../../src/diagnostics.js';
import {
  applyPacket,
  collectTagHistory,
  createTimeline,
  flattenPackets,
  GameState,
  isContainerPacket,
  parseReplayDocument,
  restoreState,
  snapshotState,
} from '../../src/index.js';
import { gameXml, modelGame } from './arbitraries.js';

function dump(state: GameState): unknown {
  return {
    game: state.gameEntityId,
    players: [...state.playerEntityIds],
    entities: [...state.entities].map((entity) => [
      entity.id,
      entity.cardId,
      [...entity.tags],
      entity.player,
    ]),
  };
}

describe('state properties', () => {
  it('restores a snapshot to an equal, independent state (roundtrip)', () => {
    fc.assert(
      fc.property(modelGame, (game) => {
        const replay = parseReplayDocument(gameXml(game)).games[0]!;
        const snapshot = snapshotState(replay.state, replay.packetCount - 1);
        const restored = restoreState(snapshot);
        expect(dump(restored)).toEqual(dump(replay.state));
        for (const entity of restored.entities) entity.tags.set(49, -1);
        expect(dump(restoreState(snapshot))).toEqual(dump(replay.state));
      }),
    );
  });

  it('gives the same state at any index as applying the leaf packets up to it, for any checkpoint interval (oracle)', () => {
    fc.assert(
      fc.property(
        modelGame.chain((game) => {
          const replay = parseReplayDocument(gameXml(game)).games[0]!;
          return fc.tuple(
            fc.constant(replay),
            fc.integer({ min: -1, max: replay.packetCount - 1 }),
            fc.integer({ min: 1, max: replay.packetCount + 2 }),
          );
        }),
        ([replay, index, interval]) => {
          const timeline = createTimeline(replay, { checkpointInterval: interval });
          const expected = new GameState();
          const diagnostics = new DiagnosticCollector();
          for (const packet of flattenPackets(replay.packets).slice(0, index + 1)) {
            if (!isContainerPacket(packet)) applyPacket(expected, packet, diagnostics);
          }
          expect(dump(timeline.stateAt(index))).toEqual(dump(expected));
        },
      ),
    );
  });

  it('records in the tag history exactly the last value the state holds for every tag (invariant)', () => {
    fc.assert(
      fc.property(modelGame, (game) => {
        const replay = parseReplayDocument(gameXml(game)).games[0]!;
        const history = collectTagHistory(replay.packets);
        for (const entity of replay.entities) {
          for (const [tag, value] of entity.tags)
            expect(history.get(entity.id)?.get(tag)?.at(-1)?.value).toBe(value);
        }
        for (const [entityId, byTag] of history) {
          for (const [tag, records] of byTag) {
            expect(replay.entities.get(entityId)?.tags.get(tag)).toBe(records.at(-1)?.value);
            for (let i = 1; i < records.length; i++) {
              expect(records[i]!.packetIndex).toBeGreaterThan(records[i - 1]!.packetIndex);
            }
          }
        }
      }),
    );
  });
});
