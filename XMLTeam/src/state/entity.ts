import { type DeckList, type TagPair } from '../parser/packets/types.js';
import { GameTag } from '../tags/game-tag.js';

/** Player-specific data that lives outside the tag map. */
export interface PlayerInfo {
  readonly playerId: number;
  readonly name?: string;
  readonly accountHi?: string;
  readonly accountLo?: string;
  readonly deck?: DeckList;
}

/**
 * Observed state of one game entity. The tag map is the source of truth;
 * everything else is either identity (`id`), a value the log carries outside
 * of tags (`cardId`, `player`) or derived through the accessor functions.
 */
export interface Entity {
  readonly id: number;
  cardId?: string;
  readonly tags: Map<number, number>;
  player?: PlayerInfo;
}

export function createEntity(id: number, cardId?: string, tags: Iterable<TagPair> = []): Entity {
  const entity: Entity = { id, tags: new Map() };
  if (cardId !== undefined) entity.cardId = cardId;
  for (const { tag, value } of tags) entity.tags.set(tag, value);
  return entity;
}

export function getTag(entity: Entity, tag: number): number | undefined {
  return entity.tags.get(tag);
}

export function getZone(entity: Entity): number | undefined {
  return entity.tags.get(GameTag.ZONE);
}

export function getController(entity: Entity): number | undefined {
  return entity.tags.get(GameTag.CONTROLLER);
}

export function getZonePosition(entity: Entity): number | undefined {
  return entity.tags.get(GameTag.ZONE_POSITION);
}

export function getCardType(entity: Entity): number | undefined {
  return entity.tags.get(GameTag.CARDTYPE);
}
