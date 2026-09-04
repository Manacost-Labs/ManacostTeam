import { type XmlElement } from '../xml/nodes.js';
import { type EntityRef } from './entity-ref.js';

export const ReplayPacketType = {
  GAME_ENTITY: 'GAME_ENTITY',
  PLAYER: 'PLAYER',
  FULL_ENTITY: 'FULL_ENTITY',
  SHOW_ENTITY: 'SHOW_ENTITY',
  HIDE_ENTITY: 'HIDE_ENTITY',
  CHANGE_ENTITY: 'CHANGE_ENTITY',
  TAG_CHANGE: 'TAG_CHANGE',
  BLOCK: 'BLOCK',
  SUB_SPELL: 'SUB_SPELL',
  META_DATA: 'META_DATA',
  CHOICES: 'CHOICES',
  CHOSEN_ENTITIES: 'CHOSEN_ENTITIES',
  SEND_CHOICES: 'SEND_CHOICES',
  OPTIONS: 'OPTIONS',
  SEND_OPTION: 'SEND_OPTION',
  SHUFFLE_DECK: 'SHUFFLE_DECK',
  UNKNOWN: 'UNKNOWN',
} as const;

export type ReplayPacketType = (typeof ReplayPacketType)[keyof typeof ReplayPacketType];

/** A raw `tag="…" value="…"` pair exactly as written in the XML. */
export interface TagPair {
  readonly tag: number;
  readonly value: number;
}

export interface BaseReplayPacket {
  /** Sequential document-order index, unique across the whole replay including nested packets. */
  readonly index: number;
  readonly type: ReplayPacketType;
  /** Raw RFC 3339 timestamp string, present only when the element carried `ts`. */
  readonly ts?: string;
  /** Attributes the parser did not recognise, preserved verbatim. */
  readonly unknownAttributes?: Readonly<Record<string, string>>;
  /** Child elements the parser did not expect under this element, preserved verbatim. */
  readonly unknownChildren?: readonly XmlElement[];
}

export interface DeckCard {
  readonly id: string;
  readonly count: number;
  readonly premium: number;
}

export interface DeckList {
  readonly type?: number;
  readonly cards: readonly DeckCard[];
}

export interface GameEntityPacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.GAME_ENTITY;
  readonly id: number;
  readonly tags: readonly TagPair[];
}

export interface PlayerPacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.PLAYER;
  /** Entity id of the player entity. Not the same thing as `playerId`. */
  readonly id: number;
  /** 1-based player number (`playerID` attribute). */
  readonly playerId: number;
  readonly name?: string;
  /** Battle.net account halves. Kept as strings: they exceed `Number.MAX_SAFE_INTEGER`. */
  readonly accountHi?: string;
  readonly accountLo?: string;
  readonly rank?: number;
  readonly legendRank?: number;
  readonly cardback?: number;
  readonly deck?: DeckList;
  readonly tags: readonly TagPair[];
}

export interface FullEntityPacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.FULL_ENTITY;
  readonly id: number;
  readonly cardId?: string;
  readonly tags: readonly TagPair[];
}

export interface ShowEntityPacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.SHOW_ENTITY;
  readonly entity: EntityRef;
  readonly cardId?: string;
  readonly tags: readonly TagPair[];
}

export interface ChangeEntityPacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.CHANGE_ENTITY;
  readonly entity: EntityRef;
  readonly cardId?: string;
  readonly tags: readonly TagPair[];
}

export interface HideEntityPacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.HIDE_ENTITY;
  readonly entity: EntityRef;
  /** Raw `Zone` enum value the entity moves to. */
  readonly zone: number;
}

export interface TagChangePacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.TAG_CHANGE;
  readonly entity: EntityRef;
  readonly tag: number;
  readonly value: number;
  readonly hasChangeDef?: boolean;
}

export interface BlockPacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.BLOCK;
  readonly entity: EntityRef;
  /** Raw `BlockType` (PowSubType) enum value from the `type` attribute. */
  readonly blockType: number;
  /** The `index` attribute of the block (action index), distinct from the packet `index`. */
  readonly actionIndex?: number;
  /** Kept verbatim. Current exporters write a placeholder string here, not a card id. */
  readonly effectCardId?: string;
  readonly effectIndex?: number;
  readonly target?: EntityRef;
  readonly subOption?: number;
  /** GameTag id that triggered the block. */
  readonly triggerKeyword?: number;
  readonly children: readonly ReplayPacket[];
}

export interface SubSpellTarget {
  readonly index: number;
  readonly entity: EntityRef;
}

export interface SubSpellPacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.SUB_SPELL;
  readonly spellPrefabGuid?: string;
  readonly source?: EntityRef;
  readonly targetCount?: number;
  readonly targets: readonly SubSpellTarget[];
  readonly children: readonly ReplayPacket[];
}

export interface MetaDataInfo {
  readonly index?: number;
  readonly entity: EntityRef;
}

export interface MetaDataPacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.META_DATA;
  /** Raw `MetaDataType` enum value. */
  readonly meta: number;
  readonly data: number;
  readonly infoCount?: number;
  readonly info: readonly MetaDataInfo[];
}

export interface ChoiceEntry {
  readonly index?: number;
  readonly entity: EntityRef;
}

export interface ChoicesPacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.CHOICES;
  readonly id: number;
  /** Player entity the choice is presented to. */
  readonly entity: EntityRef;
  readonly taskList?: number;
  /** Raw `ChoiceType` enum value. */
  readonly choiceType: number;
  readonly min: number;
  readonly max: number;
  readonly source: EntityRef;
  readonly choices: readonly ChoiceEntry[];
}

export interface ChosenEntitiesPacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.CHOSEN_ENTITIES;
  readonly id: number;
  readonly entity: EntityRef;
  readonly choices: readonly ChoiceEntry[];
}

export interface SendChoicesPacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.SEND_CHOICES;
  readonly id: number;
  readonly choiceType: number;
  readonly choices: readonly ChoiceEntry[];
}

export interface OptionTarget {
  readonly index: number;
  /** Missing in some real logs for invalid targets that only carry an error code. */
  readonly entity?: EntityRef;
  readonly error?: string;
  readonly errorParam?: number;
}

export interface SubOptionEntry {
  readonly index: number;
  readonly entity: EntityRef;
  readonly error?: string;
  readonly errorParam?: number;
  readonly targets: readonly OptionTarget[];
}

export interface OptionEntry {
  readonly index: number;
  /** Raw `OptionType` enum value. */
  readonly optionType: number;
  readonly entity?: EntityRef;
  /** `PlayReq` name such as `REQ_ENOUGH_MANA`, or `INVALID`. */
  readonly error?: string;
  readonly errorParam?: number;
  readonly subOptions: readonly SubOptionEntry[];
  readonly targets: readonly OptionTarget[];
}

export interface OptionsPacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.OPTIONS;
  readonly id: number;
  readonly options: readonly OptionEntry[];
}

export interface SendOptionPacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.SEND_OPTION;
  readonly option: number;
  readonly subOption?: number;
  readonly position?: number;
  readonly target?: EntityRef;
}

export interface ShuffleDeckPacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.SHUFFLE_DECK;
  readonly playerId: number;
}

/** Any element in packet position that the parser does not understand, kept losslessly. */
export interface UnknownPacket extends BaseReplayPacket {
  readonly type: typeof ReplayPacketType.UNKNOWN;
  readonly name: string;
  readonly attributes: Readonly<Record<string, string>>;
  readonly children: readonly XmlElement[];
  readonly line: number;
  readonly column: number;
}

export type ReplayPacket =
  | GameEntityPacket
  | PlayerPacket
  | FullEntityPacket
  | ShowEntityPacket
  | HideEntityPacket
  | ChangeEntityPacket
  | TagChangePacket
  | BlockPacket
  | SubSpellPacket
  | MetaDataPacket
  | ChoicesPacket
  | ChosenEntitiesPacket
  | SendChoicesPacket
  | OptionsPacket
  | SendOptionPacket
  | ShuffleDeckPacket
  | UnknownPacket;

/** Packets that contain further packets and therefore define the hierarchy. */
export type ContainerPacket = BlockPacket | SubSpellPacket;

export function isContainerPacket(packet: ReplayPacket): packet is ContainerPacket {
  return packet.type === ReplayPacketType.BLOCK || packet.type === ReplayPacketType.SUB_SPELL;
}
