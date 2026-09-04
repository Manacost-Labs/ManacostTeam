import { type EntityRef } from '../parser/packets/entity-ref.js';
import { type SemanticEvidence } from './rules.js';

export const SemanticEventType = {
  GAME_STARTED: 'GAME_STARTED',
  GAME_ENDED: 'GAME_ENDED',
  GAME_RESET: 'GAME_RESET',
  TURN_STARTED: 'TURN_STARTED',
  CHOICE_OFFERED: 'CHOICE_OFFERED',
  CHOICE_MADE: 'CHOICE_MADE',
  OPTION_CHOSEN: 'OPTION_CHOSEN',
  CARD_PLAYED: 'CARD_PLAYED',
  HERO_POWER_USED: 'HERO_POWER_USED',
  ATTACK: 'ATTACK',
  CARD_DRAWN: 'CARD_DRAWN',
  ZONE_CHANGED: 'ZONE_CHANGED',
  ENTITY_DIED: 'ENTITY_DIED',
  DAMAGE: 'DAMAGE',
  HEALING: 'HEALING',
  TRIGGERED: 'TRIGGERED',
  FATIGUE: 'FATIGUE',
  CONCEDED: 'CONCEDED',
} as const;

export type SemanticEventType = (typeof SemanticEventType)[keyof typeof SemanticEventType];

/** What every event knows about the entity it concerns, as of the moment of the event. */
export interface EntityFacts {
  readonly entity: number;
  readonly cardId?: string;
  /** Raw `CardType` value, when the entity has been revealed. */
  readonly cardType?: number;
  /** Entity id of the controlling player, when known. */
  readonly playerEntityId?: number;
}

export interface BaseSemanticEvent {
  /** Sequential position in the event list. */
  readonly index: number;
  readonly type: SemanticEventType;
  /** Index of the packet that produced the event. */
  readonly packetIndex: number;
  /** Index of the innermost enclosing BLOCK packet, when inside one. */
  readonly blockIndex?: number;
  /** Game turn at the moment of the event, when known. */
  readonly turn?: number;
  /** How the event was inferred and from which packets. */
  readonly evidence: SemanticEvidence;
}

/** Whether a block-level action came from the player's own command or from an effect that ran inside another block. */
export type EventInitiator = 'player' | 'effect';

export interface GameStartedEvent extends BaseSemanticEvent {
  readonly type: typeof SemanticEventType.GAME_STARTED;
  readonly gameEntityId: number;
}

export interface PlayerResult {
  readonly playerEntityId: number;
  /** Raw `PlayState` value. */
  readonly playState: number | undefined;
}

export interface GameEndedEvent extends BaseSemanticEvent {
  readonly type: typeof SemanticEventType.GAME_ENDED;
  readonly results: readonly PlayerResult[];
  readonly winners: readonly number[];
  readonly losers: readonly number[];
}

/** The game state was rewound by a GAME_RESET block (e.g. Toki, Time-Tinker); entities are re-created and the turn goes back. */
export interface GameResetEvent extends BaseSemanticEvent, EntityFacts {
  readonly type: typeof SemanticEventType.GAME_RESET;
}

export interface TurnStartedEvent extends BaseSemanticEvent {
  readonly type: typeof SemanticEventType.TURN_STARTED;
  readonly turn: number;
  /** Player whose CURRENT_PLAYER tag is set once the turn begins. */
  readonly playerEntityId?: number;
}

export interface ChoiceOfferedEvent extends BaseSemanticEvent {
  readonly type: typeof SemanticEventType.CHOICE_OFFERED;
  readonly choiceId: number;
  /** Raw `ChoiceType`: 1 = mulligan, 2 = general (discover and the like). */
  readonly choiceType: number;
  readonly playerEntityId?: number;
  readonly source: EntityRef;
  readonly entities: readonly EntityRef[];
  readonly min: number;
  readonly max: number;
}

export interface ChoiceMadeEvent extends BaseSemanticEvent {
  readonly type: typeof SemanticEventType.CHOICE_MADE;
  readonly choiceId: number;
  /** Copied from the matching CHOICE_OFFERED, when one was seen. */
  readonly choiceType?: number;
  readonly playerEntityId?: number;
  readonly chosen: readonly EntityRef[];
}

export interface OptionChosenEvent extends BaseSemanticEvent {
  readonly type: typeof SemanticEventType.OPTION_CHOSEN;
  readonly optionsId?: number;
  /** Raw `OptionType`: 2 = end turn, 3 = power. */
  readonly optionType?: number;
  readonly entity?: EntityRef;
  readonly subOptionEntity?: EntityRef;
  readonly target?: EntityRef;
  readonly position?: number;
}

export interface CardPlayedEvent extends BaseSemanticEvent, EntityFacts {
  readonly type: typeof SemanticEventType.CARD_PLAYED;
  readonly target?: number;
  /** `player` for a top-level PLAY block, `effect` when the block is nested inside another block. */
  readonly initiator: EventInitiator;
}

export interface HeroPowerUsedEvent extends BaseSemanticEvent, EntityFacts {
  readonly type: typeof SemanticEventType.HERO_POWER_USED;
  readonly target?: number;
  readonly initiator: EventInitiator;
}

export interface AttackEvent extends BaseSemanticEvent, EntityFacts {
  readonly type: typeof SemanticEventType.ATTACK;
  readonly initiator: EventInitiator;
  /** Target named on the block, when present. */
  readonly target?: number;
  /** Entity whose DEFENDING tag was set during the block; differs from `target` when the attack was redirected. */
  readonly defender?: number;
}

export interface CardDrawnEvent extends BaseSemanticEvent, EntityFacts {
  readonly type: typeof SemanticEventType.CARD_DRAWN;
}

export interface ZoneChangedEvent extends BaseSemanticEvent, EntityFacts {
  readonly type: typeof SemanticEventType.ZONE_CHANGED;
  readonly from?: number;
  readonly to: number;
}

export interface EntityDiedEvent extends BaseSemanticEvent, EntityFacts {
  readonly type: typeof SemanticEventType.ENTITY_DIED;
}

export interface DamageEvent extends BaseSemanticEvent {
  readonly type: typeof SemanticEventType.DAMAGE;
  readonly target: EntityRef;
  readonly amount: number;
  /** Entity recorded by the log as LAST_AFFECTED_BY on the target; absent when the log did not record it. */
  readonly source?: number;
  /** Entity of the innermost enclosing block. Context, not attribution: it is the attacker or effect owner, not always the damage source. */
  readonly blockEntity?: number;
}

export interface HealingEvent extends BaseSemanticEvent {
  readonly type: typeof SemanticEventType.HEALING;
  readonly target: EntityRef;
  readonly amount: number;
  readonly source?: number;
  readonly blockEntity?: number;
}

export interface TriggeredEvent extends BaseSemanticEvent, EntityFacts {
  readonly type: typeof SemanticEventType.TRIGGERED;
  /** GameTag that fired, e.g. DEATHRATTLE (217) or TRIGGER_VISUAL (32). */
  readonly triggerKeyword: number;
}

export interface FatigueEvent extends BaseSemanticEvent, EntityFacts {
  readonly type: typeof SemanticEventType.FATIGUE;
}

export interface ConcededEvent extends BaseSemanticEvent {
  readonly type: typeof SemanticEventType.CONCEDED;
  readonly playerEntityId: number;
}

export type SemanticEvent =
  | GameStartedEvent
  | GameEndedEvent
  | GameResetEvent
  | TurnStartedEvent
  | ChoiceOfferedEvent
  | ChoiceMadeEvent
  | OptionChosenEvent
  | CardPlayedEvent
  | HeroPowerUsedEvent
  | AttackEvent
  | CardDrawnEvent
  | ZoneChangedEvent
  | EntityDiedEvent
  | DamageEvent
  | HealingEvent
  | TriggeredEvent
  | FatigueEvent
  | ConcededEvent;
