import { type DiagnosticCollector, DiagnosticCode } from '../diagnostics.js';
import { type EntityRef, formatEntityRef } from '../parser/packets/entity-ref.js';
import {
  type ChangeEntityPacket,
  type FullEntityPacket,
  type GameEntityPacket,
  type HideEntityPacket,
  type PlayerPacket,
  type ReplayPacket,
  ReplayPacketType,
  type ShowEntityPacket,
  type TagChangePacket,
  type TagPair,
} from '../parser/packets/types.js';
import { GameTag } from '../tags/game-tag.js';
import { createEntity, type Entity, type PlayerInfo } from './entity.js';
import { EntityStore } from './entity-store.js';

/**
 * Observed game state reconstructed from packets. This is not a simulator:
 * it only records what the log says happened.
 */
export class GameState {
  readonly entities = new EntityStore();
  /** Entity id of the `GameEntity`, once seen. */
  gameEntityId: number | undefined;
  /** `playerId` (1-based player number) → entity id. */
  readonly playerEntityIds = new Map<number, number>();

  get game(): Entity | undefined {
    return this.gameEntityId === undefined ? undefined : this.entities.get(this.gameEntityId);
  }

  get players(): Entity[] {
    const result: Entity[] = [];
    for (const id of this.playerEntityIds.values()) {
      const entity = this.entities.get(id);
      if (entity) result.push(entity);
    }
    return result;
  }

  /** Value of the game entity's TURN tag, once known. */
  get turn(): number | undefined {
    return this.game?.tags.get(GameTag.TURN);
  }

  /** Value of the game entity's STEP tag, once known. */
  get step(): number | undefined {
    return this.game?.tags.get(GameTag.STEP);
  }

  /** The player entity whose CURRENT_PLAYER tag is set. */
  get currentPlayer(): Entity | undefined {
    return this.players.find((player) => player.tags.get(GameTag.CURRENT_PLAYER) === 1);
  }

  /** Player entity whose name matches, for name-based entity references. */
  findPlayerByName(name: string): Entity | undefined {
    return this.players.find((player) => player.player?.name === name);
  }
}

export function createGameState(): GameState {
  return new GameState();
}

/** Applies one packet (and, for containers, its children in order) to the state. */
export function applyPacket(
  state: GameState,
  packet: ReplayPacket,
  diagnostics: DiagnosticCollector,
): void {
  switch (packet.type) {
    case ReplayPacketType.GAME_ENTITY:
      applyGameEntity(state, packet, diagnostics);
      break;
    case ReplayPacketType.PLAYER:
      applyPlayer(state, packet, diagnostics);
      break;
    case ReplayPacketType.FULL_ENTITY:
      applyFullEntity(state, packet, diagnostics);
      break;
    case ReplayPacketType.SHOW_ENTITY:
      applyShowEntity(state, packet, diagnostics);
      break;
    case ReplayPacketType.CHANGE_ENTITY:
      applyChangeEntity(state, packet, diagnostics);
      break;
    case ReplayPacketType.HIDE_ENTITY:
      applyHideEntity(state, packet, diagnostics);
      break;
    case ReplayPacketType.TAG_CHANGE:
      applyTagChange(state, packet, diagnostics);
      break;
    case ReplayPacketType.BLOCK:
    case ReplayPacketType.SUB_SPELL:
      for (const child of packet.children) applyPacket(state, child, diagnostics);
      break;
    case ReplayPacketType.META_DATA:
    case ReplayPacketType.CHOICES:
    case ReplayPacketType.CHOSEN_ENTITIES:
    case ReplayPacketType.SEND_CHOICES:
    case ReplayPacketType.OPTIONS:
    case ReplayPacketType.SEND_OPTION:
    case ReplayPacketType.SHUFFLE_DECK:
    case ReplayPacketType.CACHED_TAG_FOR_DORMANT_CHANGE:
    case ReplayPacketType.RESET_GAME:
    case ReplayPacketType.VO_SPELL:
    case ReplayPacketType.UNKNOWN:
      // Informational packets: they describe choices and options, not entity state.
      break;
  }
}

export function applyPackets(
  state: GameState,
  packets: readonly ReplayPacket[],
  diagnostics: DiagnosticCollector,
): void {
  for (const packet of packets) applyPacket(state, packet, diagnostics);
}

function defineEntity(
  state: GameState,
  id: number,
  cardId: string | undefined,
  tags: readonly TagPair[],
  packet: ReplayPacket,
  diagnostics: DiagnosticCollector,
): Entity {
  const existing = state.entities.get(id);
  if (existing) {
    diagnostics.warning(
      DiagnosticCode.ENTITY_RECREATED,
      `entity ${String(id)} was defined again; its tags were replaced`,
      { packetIndex: packet.index },
    );
    existing.tags.clear();
    delete existing.cardId;
    if (cardId !== undefined) existing.cardId = cardId;
    setTags(existing, tags, packet, diagnostics);
    return existing;
  }
  const entity = createEntity(id, cardId);
  setTags(entity, tags, packet, diagnostics);
  return state.entities.create(entity);
}

function setTags(
  entity: Entity,
  tags: readonly TagPair[],
  packet: ReplayPacket,
  diagnostics: DiagnosticCollector,
): void {
  const seen = new Set<number>();
  for (const { tag, value } of tags) {
    if (seen.has(tag)) {
      diagnostics.info(
        DiagnosticCode.DUPLICATE_TAG,
        `tag ${String(tag)} appears more than once on entity ${String(entity.id)}`,
        { packetIndex: packet.index },
      );
    }
    seen.add(tag);
    entity.tags.set(tag, value);
  }
}

function applyGameEntity(
  state: GameState,
  packet: GameEntityPacket,
  diagnostics: DiagnosticCollector,
): void {
  defineEntity(state, packet.id, undefined, packet.tags, packet, diagnostics);
  state.gameEntityId = packet.id;
}

function applyPlayer(
  state: GameState,
  packet: PlayerPacket,
  diagnostics: DiagnosticCollector,
): void {
  const entity = defineEntity(state, packet.id, undefined, packet.tags, packet, diagnostics);
  const player: { -readonly [K in keyof PlayerInfo]: PlayerInfo[K] } = {
    playerId: packet.playerId,
  };
  if (packet.name !== undefined) player.name = packet.name;
  if (packet.accountHi !== undefined) player.accountHi = packet.accountHi;
  if (packet.accountLo !== undefined) player.accountLo = packet.accountLo;
  if (packet.deck !== undefined) player.deck = packet.deck;
  entity.player = player;
  state.playerEntityIds.set(packet.playerId, packet.id);
}

function applyFullEntity(
  state: GameState,
  packet: FullEntityPacket,
  diagnostics: DiagnosticCollector,
): void {
  defineEntity(state, packet.id, packet.cardId, packet.tags, packet, diagnostics);
}

/**
 * Resolves a reference to an existing entity. Unknown ids get a placeholder
 * entity so later tag changes are not lost; name references resolve to the
 * player with that name and are reported when no player matches.
 */
function resolve(
  state: GameState,
  ref: EntityRef,
  packet: ReplayPacket,
  diagnostics: DiagnosticCollector,
): Entity | undefined {
  if (ref.kind === 'name') {
    const player = state.findPlayerByName(ref.name);
    if (player) return player;
    diagnostics.violation(
      DiagnosticCode.UNRESOLVED_ENTITY_REF,
      `entity reference ${formatEntityRef(ref)} does not match a player name and was ignored`,
      { packetIndex: packet.index },
    );
    return undefined;
  }
  const entity = state.entities.get(ref.id);
  if (entity) return entity;
  diagnostics.violation(
    DiagnosticCode.UNKNOWN_ENTITY,
    `packet refers to entity ${String(ref.id)} which was never created; a placeholder was added`,
    { packetIndex: packet.index },
  );
  return state.entities.create(createEntity(ref.id));
}

function applyShowEntity(
  state: GameState,
  packet: ShowEntityPacket,
  diagnostics: DiagnosticCollector,
): void {
  const entity = resolve(state, packet.entity, packet, diagnostics);
  if (!entity) return;
  if (packet.cardId !== undefined) entity.cardId = packet.cardId;
  setTags(entity, packet.tags, packet, diagnostics);
}

// The DTD says previous tags are reset on ChangeEntity; the reference
// implementation (python-hearthstone) merges instead. Merging is followed
// because it never loses observed information.
function applyChangeEntity(
  state: GameState,
  packet: ChangeEntityPacket,
  diagnostics: DiagnosticCollector,
): void {
  const entity = resolve(state, packet.entity, packet, diagnostics);
  if (!entity) return;
  if (packet.cardId !== undefined) entity.cardId = packet.cardId;
  setTags(entity, packet.tags, packet, diagnostics);
}

function applyHideEntity(
  state: GameState,
  packet: HideEntityPacket,
  diagnostics: DiagnosticCollector,
): void {
  const entity = resolve(state, packet.entity, packet, diagnostics);
  if (!entity) return;
  entity.tags.set(GameTag.ZONE, packet.zone);
}

function applyTagChange(
  state: GameState,
  packet: TagChangePacket,
  diagnostics: DiagnosticCollector,
): void {
  const entity = resolve(state, packet.entity, packet, diagnostics);
  if (!entity) return;
  entity.tags.set(packet.tag, packet.value);
}
