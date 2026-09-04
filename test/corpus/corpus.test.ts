import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { DiagnosticCollector } from '../../src/diagnostics.js';
import {
  applyPackets,
  createTimeline,
  type EntityStore,
  extractEvents,
  flattenPackets,
  GameState,
  isContainerPacket,
  isStrictViolation,
  parseReplayDocument,
  parseReplayStream,
  type ReplayDocument,
  type ReplayPacket,
  ReplayPacketType,
  ReplayValidationError,
  SEMANTIC_RULES,
  SemanticEventType,
  walkPackets,
} from '../../src/index.js';
import { type CorpusEntry, loadManifest, MANIFEST_URL, resolveCorpusPath } from './manifest.js';

const manifest = loadManifest();
const UPDATE_COUNTS = process.env.UPDATE_CORPUS_COUNTS === '1';

function eventCounts(entry: CorpusEntry, document: ReplayDocument): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const game of document.games) {
    for (const event of extractEvents(game)) counts[event.type] = (counts[event.type] ?? 0) + 1;
  }
  const sorted = Object.fromEntries(Object.entries(counts).sort(([a], [b]) => a.localeCompare(b)));
  if (UPDATE_COUNTS) {
    const updated = {
      ...manifest,
      entries: manifest.entries.map((candidate) =>
        candidate.file === entry.file ? { ...candidate, eventCounts: sorted } : candidate,
      ),
    };
    Object.assign(manifest, updated);
    writeFileSync(MANIFEST_URL, `${JSON.stringify(updated, null, 2)}\n`);
  }
  return sorted;
}

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
      entities: entityDump(game),
    })),
  };
}

function entityDump(game: { readonly entities: EntityStore }): unknown {
  return [...game.entities].map((entity) => [
    entity.id,
    entity.cardId,
    [...entity.tags],
    entity.player,
  ]);
}

function* byteChunks(xml: string, size: number): Generator<Uint8Array> {
  const bytes = new TextEncoder().encode(xml);
  for (let offset = 0; offset < bytes.length; offset += size)
    yield bytes.subarray(offset, offset + size);
}

function subtreeSize(packet: ReplayPacket): number {
  return isContainerPacket(packet)
    ? 1 + packet.children.reduce((sum, child) => sum + subtreeSize(child), 0)
    : 1;
}

describe.each(manifest.entries.map((entry) => [entry.file, entry] as const))(
  'corpus %s',
  (_file, entry: CorpusEntry) => {
    const path = resolveCorpusPath(entry);
    const xml = readFileSync(path, 'utf8');
    const document = parseReplayDocument(xml);

    it('matches the manifest checksum and metadata', () => {
      expect(createHash('sha256').update(readFileSync(path)).digest('hex')).toBe(entry.sha256);
      expect(document.version ?? null).toBe(entry.hsreplayVersion);
      expect(document.build ?? null).toBe(entry.build);
      expect(document.games.length).toBeGreaterThan(0);
      expect(document.games[0]?.metadata.game.gameType ?? null).toBe(entry.gameType);
      expect(document.games[0]?.metadata.game.format ?? null).toBe(entry.formatType);
    });

    it('is parsed without unknown or malformed packets', () => {
      for (const game of document.games) {
        const flat = flattenPackets(game.packets);
        expect(flat.filter((packet) => packet.type === ReplayPacketType.UNKNOWN)).toEqual([]);
        expect(flat.filter((packet) => packet.unknownChildren !== undefined)).toEqual([]);
        expect(
          [...document.diagnostics, ...game.diagnostics].filter((d) => d.level === 'error'),
        ).toEqual([]);
      }
    });

    it('assigns strictly increasing, gap-free packet indexes in document order', () => {
      for (const game of document.games) {
        const flat = flattenPackets(game.packets);
        expect(flat).toHaveLength(game.packetCount);
        flat.forEach((packet, position) => {
          expect(packet.index).toBe(position);
        });
        for (const { packet, parent } of walkPackets(game.packets)) {
          if (parent) expect(packet.index).toBeGreaterThan(parent.index);
          if (isContainerPacket(packet)) {
            packet.children.forEach((child, position) => {
              const previous = packet.children[position - 1];
              expect(child.index).toBe(
                previous ? previous.index + subtreeSize(previous) : packet.index + 1,
              );
            });
          }
        }
      }
    });

    it('keeps entity ids consistent between packets and the entity store', () => {
      for (const game of document.games) {
        const created = new Set<number>();
        const placeholders = new Set(
          game.diagnostics.filter((d) => d.code === 'UNKNOWN_ENTITY').map((d) => d.packetIndex),
        );
        for (const packet of flattenPackets(game.packets)) {
          if (
            packet.type === ReplayPacketType.GAME_ENTITY ||
            packet.type === ReplayPacketType.PLAYER ||
            packet.type === ReplayPacketType.FULL_ENTITY
          ) {
            created.add(packet.id);
          } else if (
            packet.type === ReplayPacketType.TAG_CHANGE ||
            packet.type === ReplayPacketType.SHOW_ENTITY
          ) {
            if (packet.entity.kind === 'id' && !created.has(packet.entity.id)) {
              expect(placeholders.has(packet.index)).toBe(true);
              created.add(packet.entity.id);
            }
          }
        }
        for (const entity of game.entities) {
          expect(created.has(entity.id)).toBe(true);
          const entityIdTag = entity.tags.get(53);
          if (entityIdTag !== undefined) expect(entityIdTag).toBe(entity.id);
        }
        expect(game.state.players.length).toBeGreaterThanOrEqual(1);
      }
    });

    it('reconstructs the final state through the timeline and through a fresh sequential apply', () => {
      for (const game of document.games) {
        const timeline = createTimeline(game, { checkpointInterval: 700 });
        expect(entityDump(timeline.stateAt(game.packetCount - 1))).toEqual(entityDump(game));
        const fresh = new GameState();
        applyPackets(fresh, game.packets, new DiagnosticCollector());
        expect(entityDump(fresh)).toEqual(entityDump(game));
      }
    });

    it('streams to the same document as the in-memory parser', async () => {
      const streamed = await parseReplayStream(byteChunks(xml, 4096));
      expect(comparable(streamed)).toEqual(comparable(document));
    });

    it('parses deterministically, and strict mode either throws or agrees with lenient mode', () => {
      expect(comparable(parseReplayDocument(xml))).toEqual(comparable(document));
      const violations = [
        ...document.diagnostics,
        ...document.games.flatMap((game) => game.diagnostics),
      ].filter(isStrictViolation);
      if (violations.length === 0) {
        expect(comparable(parseReplayDocument(xml, { strict: true }))).toEqual(
          comparable(document),
        );
      } else {
        expect(() => parseReplayDocument(xml, { strict: true })).toThrow(ReplayValidationError);
      }
    });

    it('yields the semantic event counts recorded in the manifest', () => {
      // Recorded on the current rules (UPDATE_CORPUS_COUNTS=1 pnpm test:corpus rewrites them).
      // A difference means a rule changed its behaviour on a real replay, intended or not.
      expect(eventCounts(entry, document)).toEqual(entry.eventCounts);
    });

    it('yields semantic events that satisfy the layer invariants', () => {
      for (const game of document.games) {
        const events = extractEvents(game);
        const blocks = new Set(
          flattenPackets(game.packets)
            .filter((packet) => packet.type === ReplayPacketType.BLOCK)
            .map((packet) => packet.index),
        );
        expect(
          events.filter((event) => event.type === SemanticEventType.GAME_STARTED),
        ).toHaveLength(1);
        const started = events.findIndex((event) => event.type === SemanticEventType.GAME_STARTED);
        const ended = events.findIndex((event) => event.type === SemanticEventType.GAME_ENDED);
        if (ended >= 0) expect(ended).toBeGreaterThan(started);
        const resets = events.filter((event) => event.type === SemanticEventType.GAME_RESET).length;
        expect(resets > 0).toBe(entry.knownAnomalies.includes('GAME_RESET'));

        let lastTurn = 0;
        let lastPacket = -1;
        let resetSinceLastTurn = false;
        for (const event of events) {
          expect(event.packetIndex).toBeGreaterThanOrEqual(0);
          expect(event.packetIndex).toBeLessThan(game.packetCount);
          expect(event.packetIndex).toBeGreaterThanOrEqual(lastPacket);
          lastPacket = event.packetIndex;
          if (event.blockIndex !== undefined) {
            expect(blocks.has(event.blockIndex)).toBe(true);
            expect(event.blockIndex).toBeLessThan(event.packetIndex + 1);
          }
          expect(SEMANTIC_RULES[event.evidence.rule].level).toBe(event.evidence.level);
          expect(event.evidence.packetIndices).toContain(event.packetIndex);
          for (const index of event.evidence.packetIndices)
            expect(index).toBeLessThan(game.packetCount);
          if ('entity' in event && typeof event.entity === 'number')
            expect(game.entities.has(event.entity)).toBe(true);
          if (event.type === SemanticEventType.GAME_RESET) resetSinceLastTurn = true;
          if (event.type === SemanticEventType.TURN_STARTED) {
            // Turns only go backwards after a GAME_RESET block or in logs documented as inconsistent.
            if (!resetSinceLastTurn && !entry.knownAnomalies.includes('TURN_NOT_MONOTONIC')) {
              expect(event.turn).toBeGreaterThanOrEqual(lastTurn);
            }
            lastTurn = event.turn;
            resetSinceLastTurn = false;
          }
          if (
            event.type === SemanticEventType.CARD_DRAWN ||
            event.type === SemanticEventType.ENTITY_DIED
          ) {
            expect(event.evidence.level).toBe('derived');
          }
          if (event.type === SemanticEventType.ENTITY_DIED) expect(event.cardType).toBeDefined();
        }
      }
    });
  },
);

describe('corpus manifest', () => {
  it('lists every replay file exactly once with a checksum and known anomalies', () => {
    const files = manifest.entries.map((entry) => entry.file);
    expect(new Set(files).size).toBe(files.length);
    for (const entry of manifest.entries) {
      expect(entry.sha256).toMatch(/^[0-9a-f]{64}$/);
      expect(Array.isArray(entry.knownAnomalies)).toBe(true);
    }
    expect(manifest.entries.length).toBeGreaterThanOrEqual(10);
  });
});
