import fc from 'fast-check';

import { type ReplayPacket, type TagPair } from '../../src/index.js';

/**
 * A model of a game's packet list that is independent of the parser: it is
 * serialised to XML by `gameXml` and the parser's output is compared with
 * `toExpectedPackets`, which assigns indexes by its own pre-order walk.
 */
export type ModelPacket =
  | { kind: 'TagChange'; entity: number; tag: number; value: number; hasChangeDef?: boolean }
  | { kind: 'FullEntity'; id: number; cardId?: string; tags: TagPair[] }
  | { kind: 'ShowEntity'; entity: number; cardId: string; tags: TagPair[] }
  | { kind: 'HideEntity'; entity: number; zone: number }
  | { kind: 'MetaData'; meta: number; data: number; info: number[] }
  | { kind: 'Block'; entity: number; blockType: number; target?: number; children: ModelPacket[] }
  | { kind: 'SubSpell'; source: number; targets: number[]; children: ModelPacket[] };

export interface ModelGame {
  readonly id: number;
  readonly playerName: string;
  readonly packets: ModelPacket[];
}

const CARD_ID = fc.stringMatching(/^[A-Z]{2,4}_[0-9]{3}[a-z]?$/);
const ENTITY = fc.integer({ min: 1, max: 400 });
const TAG = fc.integer({ min: 1, max: 5000 });
const VALUE = fc.integer({ min: -2147483648, max: 2147483647 });
const TAG_PAIRS = fc.array(fc.record({ tag: TAG, value: VALUE }), { maxLength: 6 });

const leaf: fc.Arbitrary<ModelPacket> = fc.oneof(
  {
    arbitrary: fc.record({
      kind: fc.constant('TagChange' as const),
      entity: ENTITY,
      tag: TAG,
      value: VALUE,
    }),
    weight: 6,
  },
  fc.record({
    kind: fc.constant('TagChange' as const),
    entity: ENTITY,
    tag: TAG,
    value: VALUE,
    hasChangeDef: fc.constant(true),
  }),
  fc.record({ kind: fc.constant('FullEntity' as const), id: ENTITY, tags: TAG_PAIRS }),
  fc.record({
    kind: fc.constant('FullEntity' as const),
    id: ENTITY,
    cardId: CARD_ID,
    tags: TAG_PAIRS,
  }),
  fc.record({
    kind: fc.constant('ShowEntity' as const),
    entity: ENTITY,
    cardId: CARD_ID,
    tags: TAG_PAIRS,
  }),
  fc.record({
    kind: fc.constant('HideEntity' as const),
    entity: ENTITY,
    zone: fc.integer({ min: 1, max: 7 }),
  }),
  fc.record({
    kind: fc.constant('MetaData' as const),
    meta: fc.integer({ min: 0, max: 30 }),
    data: fc.integer({ min: 0, max: 5000 }),
    info: fc.array(ENTITY, { maxLength: 3 }),
  }),
);

export const modelPacket: fc.Arbitrary<ModelPacket> = fc.letrec<{ packet: ModelPacket }>((tie) => ({
  packet: fc.oneof(
    { depthIdentifier: 'packet', depthSize: 'small', withCrossShrink: true },
    { arbitrary: leaf, weight: 5 },
    {
      arbitrary: fc.record({
        kind: fc.constant('Block' as const),
        entity: ENTITY,
        blockType: fc.integer({ min: 0, max: 15 }),
        children: fc.array(tie('packet'), { maxLength: 4 }),
      }),
      weight: 2,
    },
    {
      arbitrary: fc.record({
        kind: fc.constant('Block' as const),
        entity: ENTITY,
        blockType: fc.integer({ min: 0, max: 15 }),
        target: ENTITY,
        children: fc.array(tie('packet'), { maxLength: 3 }),
      }),
      weight: 1,
    },
    {
      arbitrary: fc.record({
        kind: fc.constant('SubSpell' as const),
        source: ENTITY,
        targets: fc.array(ENTITY, { maxLength: 2 }),
        children: fc.array(tie('packet'), { maxLength: 3 }),
      }),
      weight: 1,
    },
  ),
})).packet;

// Control characters are not allowed in XML 1.0 attribute values; lone surrogates cannot be encoded as UTF-8.
// eslint-disable-next-line no-control-regex
const CONTROL_OR_SURROGATE = /[\u0000-\u001f\ud800-\udfff]/;

/** Player names exercise attribute escaping and multi-byte UTF-8 (Cyrillic, CJK, emoji). */
export const playerName: fc.Arbitrary<string> = fc.oneof(
  fc.constant('Alice#1234'),
  fc.constant('Игрок#12'),
  fc.constant('玩家#7'),
  fc.constant('Tom & "Jerry" <3'),
  fc.constant("O'Neil \u{1F0CF}"),
  fc
    .string({ minLength: 1, maxLength: 12, unit: 'grapheme' })
    .filter((name) => !CONTROL_OR_SURROGATE.test(name)),
);

export const modelGame: fc.Arbitrary<ModelGame> = fc.record({
  id: fc.integer({ min: 1, max: 99999999 }),
  playerName,
  packets: fc.array(modelPacket, { maxLength: 12 }),
});

export function escapeAttribute(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function tagsXml(tags: readonly TagPair[]): string {
  return tags
    .map((pair) => `<Tag tag="${String(pair.tag)}" value="${String(pair.value)}"/>`)
    .join('');
}

export function packetXml(packet: ModelPacket): string {
  switch (packet.kind) {
    case 'TagChange':
      return `<TagChange entity="${String(packet.entity)}" tag="${String(packet.tag)}" value="${String(packet.value)}"${packet.hasChangeDef ? ' hasChangeDef="true"' : ''}/>`;
    case 'FullEntity':
      return `<FullEntity id="${String(packet.id)}"${packet.cardId === undefined ? '' : ` cardID="${packet.cardId}"`}>${tagsXml(packet.tags)}</FullEntity>`;
    case 'ShowEntity':
      return `<ShowEntity entity="${String(packet.entity)}" cardID="${packet.cardId}">${tagsXml(packet.tags)}</ShowEntity>`;
    case 'HideEntity':
      return `<HideEntity entity="${String(packet.entity)}" zone="${String(packet.zone)}"/>`;
    case 'MetaData':
      return `<MetaData meta="${String(packet.meta)}" data="${String(packet.data)}" infoCount="${String(packet.info.length)}">${packet.info.map((entity, index) => `<Info index="${String(index)}" entity="${String(entity)}"/>`).join('')}</MetaData>`;
    case 'Block':
      return `<Block entity="${String(packet.entity)}" type="${String(packet.blockType)}"${packet.target === undefined ? '' : ` target="${String(packet.target)}"`}>${packet.children.map(packetXml).join('')}</Block>`;
    case 'SubSpell':
      return `<SubSpell source="${String(packet.source)}" targetCount="${String(packet.targets.length)}">${packet.targets.map((entity, index) => `<SubSpellTarget index="${String(index)}" entity="${String(entity)}"/>`).join('')}${packet.children.map(packetXml).join('')}</SubSpell>`;
  }
}

export const DOCTYPE =
  '<!DOCTYPE hsreplay SYSTEM "https://hearthsim.info/hsreplay/dtd/hsreplay-1.7.dtd">';

export function gameXml(game: ModelGame, extraTopLevel = ''): string {
  return `<?xml version="1.0" encoding="utf-8"?>\n${DOCTYPE}\n<HSReplay build="1" version="1.7"><Game id="${String(game.id)}"><GameEntity id="1"><Tag tag="202" value="1"/></GameEntity><Player id="2" playerID="1" name="${escapeAttribute(game.playerName)}"><Tag tag="50" value="1"/></Player>${game.packets.map(packetXml).join('')}${extraTopLevel}</Game></HSReplay>`;
}

const ref = (id: number) => ({ kind: 'id' as const, id });

/** Expected parser output, with indexes assigned by an independent pre-order walk. */
export function toExpectedPackets(game: ModelGame): ReplayPacket[] {
  let next = 0;
  const convert = (packet: ModelPacket): ReplayPacket => {
    const index = next++;
    switch (packet.kind) {
      case 'TagChange':
        return {
          index,
          type: 'TAG_CHANGE',
          entity: ref(packet.entity),
          tag: packet.tag,
          value: packet.value,
          ...(packet.hasChangeDef ? { hasChangeDef: true } : {}),
        };
      case 'FullEntity':
        return {
          index,
          type: 'FULL_ENTITY',
          id: packet.id,
          ...(packet.cardId === undefined ? {} : { cardId: packet.cardId }),
          tags: packet.tags,
        };
      case 'ShowEntity':
        return {
          index,
          type: 'SHOW_ENTITY',
          entity: ref(packet.entity),
          cardId: packet.cardId,
          tags: packet.tags,
        };
      case 'HideEntity':
        return { index, type: 'HIDE_ENTITY', entity: ref(packet.entity), zone: packet.zone };
      case 'MetaData':
        return {
          index,
          type: 'META_DATA',
          meta: packet.meta,
          data: packet.data,
          infoCount: packet.info.length,
          info: packet.info.map((entity, position) => ({ index: position, entity: ref(entity) })),
        };
      case 'Block':
        return {
          index,
          type: 'BLOCK',
          entity: ref(packet.entity),
          blockType: packet.blockType,
          ...(packet.target === undefined ? {} : { target: ref(packet.target) }),
          children: packet.children.map(convert),
        };
      case 'SubSpell':
        return {
          index,
          type: 'SUB_SPELL',
          source: ref(packet.source),
          targetCount: packet.targets.length,
          targets: packet.targets.map((entity, position) => ({
            index: position,
            entity: ref(entity),
          })),
          children: packet.children.map(convert),
        };
    }
  };
  const prelude: ReplayPacket[] = [
    { index: next++, type: 'GAME_ENTITY', id: 1, tags: [{ tag: 202, value: 1 }] },
    {
      index: next++,
      type: 'PLAYER',
      id: 2,
      playerId: 1,
      name: game.playerName,
      tags: [{ tag: 50, value: 1 }],
    },
  ];
  return [...prelude, ...game.packets.map(convert)];
}

/** Cut positions for splitting `length` bytes into chunks of 1..`maxChunk` bytes. */
export function chunking(length: number, maxChunk: number): fc.Arbitrary<number[]> {
  return fc
    .array(fc.integer({ min: 1, max: maxChunk }), { minLength: 1, maxLength: Math.max(1, length) })
    .map((sizes) => {
      const cuts: number[] = [];
      let offset = 0;
      for (const size of sizes) {
        if (offset >= length) break;
        offset = Math.min(length, offset + size);
        cuts.push(offset);
      }
      if (cuts[cuts.length - 1] !== length) cuts.push(length);
      return cuts;
    });
}

export function splitBytes(bytes: Uint8Array, cuts: readonly number[]): Uint8Array[] {
  const chunks: Uint8Array[] = [];
  let start = 0;
  for (const cut of cuts) {
    chunks.push(bytes.subarray(start, cut));
    start = cut;
  }
  return chunks;
}
