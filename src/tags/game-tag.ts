/**
 * Central place for GameTag ids. Raw packets carry numeric tags untouched;
 * this module gives them names.
 *
 * The list is deliberately partial: it holds the tags the state engine and
 * fundamental analysis depend on, all cross-checked against the HearthSim
 * `GameTag` enum. Unknown tags stay numeric and are never rejected. Extend
 * with `createTagRegistry` when you need more names.
 */
export const GameTag = {
  PREMIUM: 12,
  PLAYSTATE: 17,
  LAST_AFFECTED_BY: 18,
  STEP: 19,
  TURN: 20,
  FATIGUE: 22,
  CURRENT_PLAYER: 23,
  FIRST_PLAYER: 24,
  RESOURCES_USED: 25,
  RESOURCES: 26,
  HERO_ENTITY: 27,
  MAXHANDSIZE: 28,
  STARTHANDSIZE: 29,
  PLAYER_ID: 30,
  TEAM_ID: 31,
  TRIGGER_VISUAL: 32,
  DEFENDING: 36,
  PROPOSED_DEFENDER: 37,
  ATTACKING: 38,
  PROPOSED_ATTACKER: 39,
  ATTACHED: 40,
  EXHAUSTED: 43,
  DAMAGE: 44,
  HEALTH: 45,
  ATK: 47,
  COST: 48,
  ZONE: 49,
  CONTROLLER: 50,
  OWNER: 51,
  DEFINITION: 52,
  ENTITY_ID: 53,
  ELITE: 114,
  MAXRESOURCES: 115,
  CARD_SET: 183,
  DURABILITY: 187,
  SILENCED: 188,
  WINDFURY: 189,
  TAUNT: 190,
  STEALTH: 191,
  SPELLPOWER: 192,
  DIVINE_SHIELD: 194,
  CHARGE: 197,
  NEXT_STEP: 198,
  CLASS: 199,
  CARDRACE: 200,
  FACTION: 201,
  CARDTYPE: 202,
  RARITY: 203,
  STATE: 204,
  SUMMONED: 205,
  FREEZE: 208,
  ENRAGED: 212,
  OVERLOAD: 215,
  DEATHRATTLE: 217,
  BATTLECRY: 218,
  SECRET: 219,
  COMBO: 220,
  ZONE_POSITION: 263,
  MULLIGAN_STATE: 305,
  NUM_TURNS_IN_PLAY: 273,
  CREATOR: 338,
  TAG_LAST_KNOWN_COST_IN_HAND: 466,
} as const;

export type GameTagName = keyof typeof GameTag;
export type GameTagId = (typeof GameTag)[GameTagName];

/** `Zone` enum values (tag 49). */
export const Zone = {
  INVALID: 0,
  PLAY: 1,
  DECK: 2,
  HAND: 3,
  GRAVEYARD: 4,
  REMOVEDFROMGAME: 5,
  SETASIDE: 6,
  SECRET: 7,
} as const;

export type ZoneId = (typeof Zone)[keyof typeof Zone];

/** `CardType` enum values (tag 202). */
export const CardType = {
  INVALID: 0,
  GAME: 1,
  PLAYER: 2,
  HERO: 3,
  MINION: 4,
  SPELL: 5,
  ENCHANTMENT: 6,
  WEAPON: 7,
  ITEM: 8,
  TOKEN: 9,
  HERO_POWER: 10,
  BLANK: 11,
  GAME_MODE_BUTTON: 12,
  MOVE_MINION_HOVER_TARGET: 13,
  LETTUCE_ABILITY: 14,
  BATTLEGROUND_SPELL: 15,
  LOCATION: 16,
  BATTLEGROUND_QUEST_REWARD: 17,
  BATTLEGROUND_ANOMALY: 18,
  BATTLEGROUND_TRINKET: 19,
} as const;

export type CardTypeId = (typeof CardType)[keyof typeof CardType];

/** Bidirectional lookup between tag ids and names, extensible with custom names. */
export interface TagRegistry {
  name(tag: number): string | undefined;
  id(name: string): number | undefined;
  /** `ZONE` for known tags, `TAG_1234` otherwise. */
  describe(tag: number): string;
}

export function createTagRegistry(extra: Readonly<Record<string, number>> = {}): TagRegistry {
  const byId = new Map<number, string>();
  const byName = new Map<string, number>();
  for (const [name, id] of [...Object.entries(GameTag), ...Object.entries(extra)]) {
    byId.set(id, name);
    byName.set(name, id);
  }
  return {
    name: (tag) => byId.get(tag),
    id: (name) => byName.get(name),
    describe: (tag) => byId.get(tag) ?? `TAG_${String(tag)}`,
  };
}

export const defaultTagRegistry: TagRegistry = createTagRegistry();
