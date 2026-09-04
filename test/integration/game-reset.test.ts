import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { DiagnosticCollector } from '../../src/diagnostics.js';
import {
  applyPacket,
  BlockType,
  collectTagHistory,
  createTimeline,
  extractEvents,
  flattenPackets,
  GameState,
  GameTag,
  isContainerPacket,
  parseReplayDocument,
  ReplayPacketType,
  SemanticEventType,
} from '../../src/index.js';
import { loadManifest, resolveCorpusPath } from '../corpus/manifest.js';

const resetFiles = loadManifest().entries.filter((entry) =>
  entry.knownAnomalies.includes('GAME_RESET'),
);

function dump(state: GameState): unknown {
  return [...state.entities].map((entity) => [entity.id, entity.cardId, [...entity.tags]]);
}

describe.each(resetFiles.map((entry) => [entry.file, entry] as const))(
  'GAME_RESET in %s',
  (_file, entry) => {
    const game = parseReplayDocument(readFileSync(resolveCorpusPath(entry), 'utf8')).games[0]!;
    const flat = flattenPackets(game.packets);
    const resets = flat.filter(
      (packet) =>
        packet.type === ReplayPacketType.BLOCK && packet.blockType === BlockType.GAME_RESET,
    );
    const events = extractEvents(game);

    it('has at least one GAME_RESET block and reports it as an observed event', () => {
      expect(resets.length).toBeGreaterThan(0);
      const resetEvents = events.filter((event) => event.type === SemanticEventType.GAME_RESET);
      expect(resetEvents.map((event) => event.packetIndex)).toEqual(
        resets.map((packet) => packet.index),
      );
      expect(resetEvents.every((event) => event.evidence.level === 'observed')).toBe(true);
    });

    it('reconstructs the state just before, just after and well after each reset from checkpoints', () => {
      const timeline = createTimeline(game, { checkpointInterval: 250 });
      for (const reset of resets) {
        const lastChild =
          flattenPackets(isContainerPacket(reset) ? reset.children : []).at(-1)?.index ??
          reset.index;
        for (const index of [
          reset.index - 1,
          reset.index,
          lastChild,
          Math.min(lastChild + 300, game.packetCount - 1),
        ]) {
          const expected = new GameState();
          const diagnostics = new DiagnosticCollector();
          for (const packet of flat.slice(0, index + 1))
            if (!isContainerPacket(packet)) applyPacket(expected, packet, diagnostics);
          expect(dump(timeline.stateAt(index))).toEqual(dump(expected));
        }
      }
    });

    it('records the re-definitions in the tag history so the last value always matches the state', () => {
      const history = collectTagHistory(game.packets);
      let cleared = 0;
      for (const [entityId, byTag] of history) {
        for (const [tag, records] of byTag) {
          expect(game.entities.get(entityId)?.tags.get(tag)).toBe(records.at(-1)?.value);
          if (records.some((record) => record.value === undefined)) cleared++;
        }
      }
      expect(cleared).toBeGreaterThan(0);
    });

    it('never lets turns go backwards except right after a reset', () => {
      let lastTurn = 0;
      let resetSince = false;
      let decreases = 0;
      for (const event of events) {
        if (event.type === SemanticEventType.GAME_RESET) resetSince = true;
        if (event.type === SemanticEventType.TURN_STARTED) {
          if (event.turn < lastTurn) {
            expect(resetSince).toBe(true);
            decreases++;
          }
          lastTurn = event.turn;
          resetSince = false;
        }
      }
      expect(decreases).toBeGreaterThanOrEqual(0);
      expect(game.state.game?.tags.get(GameTag.TURN)).toBe(lastTurn);
    });
  },
);
