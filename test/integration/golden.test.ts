import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import {
  flattenPackets,
  GameTag,
  type ReplayPacket,
  ReplayPacketType,
  walkPackets,
} from '../../src/index.js';
import { parseReplayFile } from '../../src/node.js';
import { FIXTURE_PATH } from '../helpers.js';

const EXPECTED_PATH = fileURLToPath(new URL('../fixtures/test.expected.json', import.meta.url));
const UPDATE = process.env.UPDATE_GOLDEN === '1';

const SAMPLE_ENTITY_IDS = [1, 2, 3, 4, 31, 68, 72, 74, 209];
const TRACKED_TAGS: [entityId: number, tag: number][] = [
  [1, GameTag.STEP],
  [1, GameTag.TURN],
  [1, GameTag.STATE],
  [2, GameTag.PLAYSTATE],
  [3, GameTag.PLAYSTATE],
  [2, GameTag.RESOURCES],
  [68, GameTag.ZONE],
];

interface BlockShape {
  index: number;
  type: string;
  entity?: unknown;
  blockType?: number;
  children?: BlockShape[];
}

function shape(packet: ReplayPacket): BlockShape {
  const result: BlockShape = { index: packet.index, type: packet.type };
  if (packet.type === ReplayPacketType.BLOCK) {
    result.entity = packet.entity;
    result.blockType = packet.blockType;
  }
  if (packet.type === ReplayPacketType.BLOCK || packet.type === ReplayPacketType.SUB_SPELL) {
    result.children = packet.children.map(shape);
  }
  return result;
}

async function summarize(): Promise<unknown> {
  const replay = await parseReplayFile(FIXTURE_PATH);
  const flat = flattenPackets(replay.packets);

  const typeCounts: Record<string, number> = {};
  for (const packet of flat) typeCounts[packet.type] = (typeCounts[packet.type] ?? 0) + 1;

  const transitions: Record<string, number[]> = {};
  for (const [entityId, tag] of TRACKED_TAGS)
    transitions[`${String(entityId)}:${String(tag)}`] = [];
  for (const packet of flat) {
    if (packet.type !== ReplayPacketType.TAG_CHANGE || packet.entity.kind !== 'id') continue;
    transitions[`${String(packet.entity.id)}:${String(packet.tag)}`]?.push(packet.value);
  }

  const deepestBlock = [...walkPackets(replay.packets)].reduce((best, visit) =>
    visit.depth > best.depth ? visit : best,
  );
  const outermost = [...walkPackets(replay.packets)].find(
    (visit) =>
      visit.depth === 0 &&
      visit.packet.type === ReplayPacketType.BLOCK &&
      containsIndex(visit.packet, deepestBlock.packet.index),
  );

  const entities: Record<string, unknown> = {};
  for (const id of SAMPLE_ENTITY_IDS) {
    const entity = replay.entities.get(id);
    if (!entity) continue;
    entities[String(id)] = {
      cardId: entity.cardId ?? null,
      player: entity.player
        ? { playerId: entity.player.playerId, name: entity.player.name ?? null }
        : null,
      tags: Object.fromEntries([...entity.tags].map(([tag, value]) => [String(tag), value])),
    };
  }

  return {
    metadata: replay.metadata,
    packetCount: replay.packetCount,
    topLevelPacketCount: replay.packets.length,
    packetTypeCounts: typeCounts,
    entityCount: replay.entities.size,
    diagnosticCount: replay.diagnostics.length,
    maxDepth: deepestBlock.depth,
    firstPackets: flat.slice(0, 6).map(stripChildren),
    lastPackets: flat.slice(-6).map(stripChildren),
    blockStructure: outermost ? shape(outermost.packet) : null,
    entities,
    tagTransitions: transitions,
  };
}

function containsIndex(packet: ReplayPacket, index: number): boolean {
  return [...walkPackets([packet])].some((visit) => visit.packet.index === index);
}

function stripChildren(packet: ReplayPacket): unknown {
  if (packet.type === ReplayPacketType.BLOCK || packet.type === ReplayPacketType.SUB_SPELL) {
    const { children, ...rest } = packet;
    return { ...rest, childCount: children.length };
  }
  return packet;
}

describe('golden snapshot of test.xml', () => {
  it('matches test/fixtures/test.expected.json', async () => {
    const actual: unknown = JSON.parse(JSON.stringify(await summarize()));
    if (UPDATE) {
      writeFileSync(EXPECTED_PATH, `${JSON.stringify(actual, null, 2)}\n`);
    }
    const expected: unknown = JSON.parse(readFileSync(EXPECTED_PATH, 'utf8'));
    expect(actual).toEqual(expected);
  });
});
