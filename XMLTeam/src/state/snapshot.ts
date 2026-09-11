import { type Entity, type PlayerInfo } from './entity.js';
import { GameState } from './engine.js';

/** Immutable copy of one entity at a point in time. */
export interface EntitySnapshot {
  readonly id: number;
  readonly cardId?: string;
  readonly tags: ReadonlyMap<number, number>;
  readonly player?: PlayerInfo;
}

/** Immutable copy of the whole state after the packet with `packetIndex` was applied (-1 = nothing applied). */
export interface GameStateSnapshot {
  readonly packetIndex: number;
  readonly gameEntityId: number | undefined;
  readonly playerEntityIds: ReadonlyMap<number, number>;
  readonly entities: ReadonlyMap<number, EntitySnapshot>;
}

export function snapshotState(state: GameState, packetIndex: number): GameStateSnapshot {
  const entities = new Map<number, EntitySnapshot>();
  for (const entity of state.entities) entities.set(entity.id, snapshotEntity(entity));
  return {
    packetIndex,
    gameEntityId: state.gameEntityId,
    playerEntityIds: new Map(state.playerEntityIds),
    entities,
  };
}

/** Builds a fresh mutable state from a snapshot. The snapshot is left untouched. */
export function restoreState(snapshot: GameStateSnapshot): GameState {
  const state = new GameState();
  state.gameEntityId = snapshot.gameEntityId;
  for (const [playerId, entityId] of snapshot.playerEntityIds)
    state.playerEntityIds.set(playerId, entityId);
  for (const entity of snapshot.entities.values()) {
    const copy: Entity = { id: entity.id, tags: new Map(entity.tags) };
    if (entity.cardId !== undefined) copy.cardId = entity.cardId;
    if (entity.player !== undefined) copy.player = entity.player;
    state.entities.create(copy);
  }
  return state;
}

function snapshotEntity(entity: Entity): EntitySnapshot {
  const copy: { id: number; cardId?: string; tags: Map<number, number>; player?: PlayerInfo } = {
    id: entity.id,
    tags: new Map(entity.tags),
  };
  if (entity.cardId !== undefined) copy.cardId = entity.cardId;
  if (entity.player !== undefined) copy.player = entity.player;
  return copy;
}
