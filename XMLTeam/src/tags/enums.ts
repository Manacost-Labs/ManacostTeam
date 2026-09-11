/**
 * Enum value tables for the raw numbers found in packets and tags. Like
 * `GameTag`, they are partial on purpose: every value is cross-checked
 * against the HearthSim enums or the real fixture, and anything unknown stays
 * numeric. Names, not interpretation.
 */
import { GameTag } from './game-tag.js';

export type EnumTable = Readonly<Record<string, number>>;

/** `Step` values (tags 19 STEP and 198 NEXT_STEP). */
export const Step = {
  INVALID: 0,
  BEGIN_FIRST: 1,
  BEGIN_SHUFFLE: 2,
  BEGIN_DRAW: 3,
  BEGIN_MULLIGAN: 4,
  MAIN_BEGIN: 5,
  MAIN_READY: 6,
  MAIN_RESOURCE: 7,
  MAIN_DRAW: 8,
  MAIN_START: 9,
  MAIN_ACTION: 10,
  MAIN_COMBAT: 11,
  MAIN_END: 12,
  MAIN_NEXT: 13,
  FINAL_WRAPUP: 14,
  FINAL_GAMEOVER: 15,
  MAIN_CLEANUP: 16,
  MAIN_START_TRIGGERS: 17,
  MAIN_SET_ACTION_STEP_TYPE: 18,
  MAIN_PRE_ACTION: 19,
  MAIN_POST_ACTION: 20,
} as const;

/** Steps of the main phase, during which normal game actions (draws, plays, attacks) happen. */
export const MAIN_STEPS: ReadonlySet<number> = new Set([
  Step.MAIN_BEGIN,
  Step.MAIN_READY,
  Step.MAIN_RESOURCE,
  Step.MAIN_DRAW,
  Step.MAIN_START,
  Step.MAIN_ACTION,
  Step.MAIN_COMBAT,
  Step.MAIN_END,
  Step.MAIN_NEXT,
  Step.MAIN_CLEANUP,
  Step.MAIN_START_TRIGGERS,
  Step.MAIN_SET_ACTION_STEP_TYPE,
  Step.MAIN_PRE_ACTION,
  Step.MAIN_POST_ACTION,
]);

/** `PlayState` values (tag 17). */
export const PlayState = {
  INVALID: 0,
  PLAYING: 1,
  WINNING: 2,
  LOSING: 3,
  WON: 4,
  LOST: 5,
  TIED: 6,
  DISCONNECTED: 7,
  CONCEDED: 8,
} as const;

/** `State` values of the game entity (tag 204). */
export const GameEntityState = {
  INVALID: 0,
  LOADING: 1,
  RUNNING: 2,
  COMPLETE: 3,
} as const;

/** `MulliganState` values (tag 305). */
export const MulliganState = {
  INVALID: 0,
  INPUT: 1,
  DEALING: 2,
  WAITING: 3,
  DONE: 4,
} as const;

/** `BlockType` values of `Block.type`, from HearthSim's `hearthstone.enums.BlockType`. */
export const BlockType = {
  INVALID: 0,
  ATTACK: 1,
  JOUST: 2,
  POWER: 3,
  SCRIPT: 4,
  TRIGGER: 5,
  DEATHS: 6,
  PLAY: 7,
  FATIGUE: 8,
  RITUAL: 9,
  REVEAL_CARD: 10,
  GAME_RESET: 11,
  MOVE_MINION: 12,
  DECK_ACTION: 13,
} as const;

/** `MetaDataType` values of `MetaData.meta`, from HearthSim's `hearthstone.enums.MetaDataType`. */
export const MetaDataType = {
  TARGET: 0,
  DAMAGE: 1,
  HEALING: 2,
  JOUST: 3,
  CLIENT_HISTORY: 4,
  SHOW_BIG_CARD: 5,
  EFFECT_TIMING: 6,
  HISTORY_TARGET: 7,
  OVERRIDE_HISTORY: 8,
  HISTORY_TARGET_DONT_DUPLICATE_UNTIL_END: 9,
  BEGIN_ARTIFICIAL_HISTORY_TILE: 10,
  BEGIN_ARTIFICIAL_HISTORY_TRIGGER_TILE: 11,
  END_ARTIFICIAL_HISTORY_TILE: 12,
  START_DRAW: 13,
  BURNED_CARD: 14,
  EFFECT_SELECTION: 15,
  BEGIN_LISTENING_FOR_TURN_EVENTS: 16,
  HOLD_DRAWN_CARD: 17,
  CONTROLLER_AND_ZONE_CHANGE: 18,
  ARTIFICIAL_PAUSE: 19,
  SLUSH_TIME: 20,
  ARTIFICIAL_HISTORY_INTERRUPT: 21,
  POISONOUS: 22,
  CRITICAL_HIT: 23,
  HISTORY_TRIGGER_SOURCE: 24,
  HISTORY_SOURCE_OWNER: 25,
  HISTORY_REMOVE_ENTITIES: 26,
  SPEND_HEALTH: 27,
  SPEND_ARMOR: 28,
} as const;

/** `ChoiceType` values of `Choices.type` / `SendChoices.type`. */
export const ChoiceType = {
  INVALID: 0,
  MULLIGAN: 1,
  GENERAL: 2,
} as const;

/** `OptionType` values of `Option.type`. */
export const OptionType = {
  PASS: 1,
  END_TURN: 2,
  POWER: 3,
} as const;

/** `GameType` values of `Game.type`. */
export const GameType = {
  UNKNOWN: 0,
  VS_AI: 1,
  VS_FRIEND: 2,
  TUTORIAL: 4,
  ARENA: 5,
  TEST_AI_VS_AI: 6,
  RANKED: 7,
  CASUAL: 8,
  TAVERNBRAWL: 16,
  TB_1P_VS_AI: 17,
  TB_2P_COOP: 18,
  BATTLEGROUNDS: 23,
  BATTLEGROUNDS_FRIENDLY: 24,
} as const;

/** `FormatType` values of `Game.format`. */
export const FormatType = {
  UNKNOWN: 0,
  WILD: 1,
  STANDARD: 2,
  CLASSIC: 3,
  TWIST: 4,
} as const;

/** Name of a value in a table, or `undefined` when the value is not listed. */
export function enumName(table: EnumTable, value: number): string | undefined {
  for (const [name, id] of Object.entries(table)) {
    if (id === value) return name;
  }
  return undefined;
}

/** Tags whose values are enums, so a value can be described by name. */
export const TAG_VALUE_ENUMS: ReadonlyMap<number, EnumTable> = new Map<number, EnumTable>([
  [GameTag.STEP, Step],
  [GameTag.NEXT_STEP, Step],
  [GameTag.PLAYSTATE, PlayState],
  [GameTag.STATE, GameEntityState],
  [GameTag.MULLIGAN_STATE, MulliganState],
]);

/** `"WON"` for PLAYSTATE=4, `"4"` for tags without a known table or unknown values. */
export function describeTagValue(tag: number, value: number): string {
  const table = TAG_VALUE_ENUMS.get(tag);
  return (table && enumName(table, value)) ?? String(value);
}
