import { type ReplayPacket, ReplayPacketType } from '../parser/packets/types.js';
import { walkPackets } from '../parser/packets/walk.js';
import { type Replay } from '../replay.js';
import {
  BlockType,
  ChoiceType,
  type EnumTable,
  FormatType,
  GameType,
  MetaDataType,
  OptionType,
  PlayState,
  Step,
} from '../tags/enums.js';
import { CardType, defaultTagRegistry, GameTag, type TagRegistry, Zone } from '../tags/game-tag.js';

/** Where an unknown value was first seen. */
export interface UnknownOccurrence {
  readonly count: number;
  /** Labels of the replays it appeared in, in first-seen order. */
  readonly files: readonly string[];
  readonly firstFile: string;
  readonly firstPacketIndex: number | undefined;
}

export interface UnknownReport {
  /** Element names in packet position the parser does not know. */
  readonly nodes: Readonly<Record<string, UnknownOccurrence>>;
  /** `Element.attribute` pairs the parser does not know. */
  readonly attributes: Readonly<Record<string, UnknownOccurrence>>;
  /** `Element>Child` pairs the parser did not expect. */
  readonly children: Readonly<Record<string, UnknownOccurrence>>;
  /** GameTag ids missing from the registry. */
  readonly tags: Readonly<Record<string, UnknownOccurrence>>;
  /** `Enum.value` pairs missing from the enum tables, e.g. `BlockType.13`. */
  readonly enumValues: Readonly<Record<string, UnknownOccurrence>>;
  readonly replayCount: number;
}

export interface AnalyzeUnknownsOptions {
  readonly tagRegistry?: TagRegistry;
}

export interface LabeledReplay {
  readonly label: string;
  readonly packets: readonly ReplayPacket[];
}

interface MutableOccurrence {
  count: number;
  files: string[];
  firstFile: string;
  firstPacketIndex: number | undefined;
}
type Bucket = Map<string, MutableOccurrence>;

const TAG_VALUE_TABLES: readonly (readonly [tag: number, name: string, table: EnumTable])[] = [
  [GameTag.ZONE, 'Zone', Zone],
  [GameTag.CARDTYPE, 'CardType', CardType],
  [GameTag.STEP, 'Step', Step],
  [GameTag.NEXT_STEP, 'Step', Step],
  [GameTag.PLAYSTATE, 'PlayState', PlayState],
];

/**
 * Collects everything the library does not have a name for across a set of
 * replays. Run it over a corpus after a Hearthstone patch to see what the
 * registry and enum tables are missing, with frequencies and a first
 * occurrence to look at.
 */
export function analyzeUnknowns(
  replays: Iterable<LabeledReplay | Replay>,
  options: AnalyzeUnknownsOptions = {},
): UnknownReport {
  const registry = options.tagRegistry ?? defaultTagRegistry;
  const buckets = {
    nodes: new Map<string, MutableOccurrence>(),
    attributes: new Map<string, MutableOccurrence>(),
    children: new Map<string, MutableOccurrence>(),
    tags: new Map<string, MutableOccurrence>(),
    enumValues: new Map<string, MutableOccurrence>(),
  };
  let replayCount = 0;
  let unlabeled = 0;

  for (const replay of replays) {
    replayCount++;
    const label =
      'label' in replay
        ? replay.label
        : (replay.metadata.game.id ?? `replay-${String(++unlabeled)}`).toString();
    const record = (bucket: Bucket, key: string, packetIndex: number | undefined): void => {
      const existing = bucket.get(key);
      if (existing) {
        existing.count++;
        if (existing.files[existing.files.length - 1] !== label) existing.files.push(label);
      } else {
        bucket.set(key, {
          count: 1,
          files: [label],
          firstFile: label,
          firstPacketIndex: packetIndex,
        });
      }
    };
    const recordTag = (tag: number, value: number, packetIndex: number): void => {
      if (registry.name(tag) === undefined) record(buckets.tags, String(tag), packetIndex);
      for (const [enumTag, name, table] of TAG_VALUE_TABLES) {
        if (tag === enumTag && !hasValue(table, value))
          record(buckets.enumValues, `${name}.${String(value)}`, packetIndex);
      }
    };
    const recordEnum = (
      name: string,
      table: EnumTable,
      value: number | undefined,
      packetIndex: number | undefined,
    ): void => {
      if (value !== undefined && !hasValue(table, value))
        record(buckets.enumValues, `${name}.${String(value)}`, packetIndex);
    };

    for (const { packet } of walkPackets(replay.packets)) {
      if (packet.unknownAttributes) {
        for (const name of Object.keys(packet.unknownAttributes))
          record(buckets.attributes, `${elementName(packet)}.${name}`, packet.index);
      }
      if (packet.unknownChildren) {
        for (const child of packet.unknownChildren)
          record(buckets.children, `${elementName(packet)}>${child.name}`, packet.index);
      }
      switch (packet.type) {
        case ReplayPacketType.UNKNOWN:
          record(buckets.nodes, packet.name, packet.index);
          for (const name of Object.keys(packet.attributes))
            record(buckets.attributes, `${packet.name}.${name}`, packet.index);
          break;
        case ReplayPacketType.GAME_ENTITY:
        case ReplayPacketType.PLAYER:
        case ReplayPacketType.FULL_ENTITY:
        case ReplayPacketType.SHOW_ENTITY:
        case ReplayPacketType.CHANGE_ENTITY:
          for (const { tag, value } of packet.tags) recordTag(tag, value, packet.index);
          break;
        case ReplayPacketType.TAG_CHANGE:
          recordTag(packet.tag, packet.value, packet.index);
          break;
        case ReplayPacketType.HIDE_ENTITY:
          recordEnum('Zone', Zone, packet.zone, packet.index);
          break;
        case ReplayPacketType.BLOCK:
          recordEnum('BlockType', BlockType, packet.blockType, packet.index);
          if (packet.triggerKeyword !== undefined && packet.triggerKeyword !== 0)
            recordTag(packet.triggerKeyword, 0, packet.index);
          break;
        case ReplayPacketType.META_DATA:
          recordEnum('MetaDataType', MetaDataType, packet.meta, packet.index);
          break;
        case ReplayPacketType.CHOICES:
          recordEnum('ChoiceType', ChoiceType, packet.choiceType, packet.index);
          break;
        case ReplayPacketType.SEND_CHOICES:
          recordEnum('ChoiceType', ChoiceType, packet.choiceType, packet.index);
          break;
        case ReplayPacketType.OPTIONS:
          for (const option of packet.options)
            recordEnum('OptionType', OptionType, option.optionType, packet.index);
          break;
        case ReplayPacketType.SUB_SPELL:
        case ReplayPacketType.CHOSEN_ENTITIES:
        case ReplayPacketType.SEND_OPTION:
        case ReplayPacketType.SHUFFLE_DECK:
          break;
      }
    }
    if ('metadata' in replay) {
      recordEnum('GameType', GameType, replay.metadata.game.gameType, undefined);
      recordEnum('FormatType', FormatType, replay.metadata.game.format, undefined);
    }
  }

  return {
    nodes: freeze(buckets.nodes),
    attributes: freeze(buckets.attributes),
    children: freeze(buckets.children),
    tags: freeze(buckets.tags),
    enumValues: freeze(buckets.enumValues),
    replayCount,
  };
}

function hasValue(table: EnumTable, value: number): boolean {
  return Object.values(table).includes(value);
}

const ELEMENT_NAMES: Readonly<Record<Exclude<ReplayPacketType, 'UNKNOWN'>, string>> = {
  GAME_ENTITY: 'GameEntity',
  PLAYER: 'Player',
  FULL_ENTITY: 'FullEntity',
  SHOW_ENTITY: 'ShowEntity',
  HIDE_ENTITY: 'HideEntity',
  CHANGE_ENTITY: 'ChangeEntity',
  TAG_CHANGE: 'TagChange',
  BLOCK: 'Block',
  SUB_SPELL: 'SubSpell',
  META_DATA: 'MetaData',
  CHOICES: 'Choices',
  CHOSEN_ENTITIES: 'ChosenEntities',
  SEND_CHOICES: 'SendChoices',
  OPTIONS: 'Options',
  SEND_OPTION: 'SendOption',
  SHUFFLE_DECK: 'ShuffleDeck',
};

/** XML element name of a packet, so keys read like the file (`TagChange.GameTagName`). */
function elementName(packet: ReplayPacket): string {
  return packet.type === ReplayPacketType.UNKNOWN ? packet.name : ELEMENT_NAMES[packet.type];
}

function freeze(bucket: Bucket): Readonly<Record<string, UnknownOccurrence>> {
  const sorted = [...bucket.entries()].sort(
    (a, b) => b[1].count - a[1].count || a[0].localeCompare(b[0]),
  );
  return Object.fromEntries(
    sorted.map(([key, value]) => [key, { ...value, files: [...value.files] }]),
  );
}
