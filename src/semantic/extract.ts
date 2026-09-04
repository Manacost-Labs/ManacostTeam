import { DiagnosticCollector } from '../diagnostics.js';
import { type EntityRef } from '../parser/packets/entity-ref.js';
import {
  type BlockPacket,
  type OptionsPacket,
  type ReplayPacket,
  ReplayPacketType,
} from '../parser/packets/types.js';
import { type Entity, getCardType, getController, getZone } from '../state/entity.js';
import { applyPacket, GameState } from '../state/engine.js';
import { BlockType, GameEntityState, PlayState } from '../tags/enums.js';
import { CardType, GameTag, Zone } from '../tags/game-tag.js';
import {
  type EntityFacts,
  type PlayerResult,
  type SemanticEvent,
  SemanticEventType,
} from './events.js';

export interface ExtractEventsOptions {
  /** Only emit these event types. Everything is emitted by default. */
  readonly types?: ReadonlySet<SemanticEventType>;
}

/**
 * Derives semantic events from raw packets by replaying them through the
 * state engine. Events are ordered by packet index; block-level events
 * (card played, attack) carry the block's own index and are placed before
 * the events of the block's children.
 *
 * This layer interprets, and interpretation can be wrong for mechanics it
 * does not know. Every event keeps `packetIndex` so the raw packets can
 * always be consulted.
 */
export function extractEvents(
  source: { readonly packets: readonly ReplayPacket[] } | readonly ReplayPacket[],
  options: ExtractEventsOptions = {},
): SemanticEvent[] {
  const packets = Array.isArray(source)
    ? source
    : (source as { packets: readonly ReplayPacket[] }).packets;
  const extractor = new EventExtractor(options);
  extractor.visitAll(packets);
  return extractor.finish();
}

type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;
/** An event before its sequential index is known. */
type Pending = DistributiveOmit<SemanticEvent, 'index'>;

interface BlockContext {
  readonly packet: BlockPacket;
  /** Last entity whose DEFENDING tag went to 1 inside this block. */
  defender?: number;
}

class EventExtractor {
  private readonly state = new GameState();
  private readonly diagnostics = new DiagnosticCollector();
  private readonly slots: (Pending | undefined)[] = [];
  private readonly blocks: BlockContext[] = [];
  private readonly choiceTypes = new Map<number, { choiceType: number; playerEntityId?: number }>();
  private lastOptions: OptionsPacket | undefined;

  constructor(private readonly options: ExtractEventsOptions) {}

  visitAll(packets: readonly ReplayPacket[]): void {
    for (const packet of packets) this.visit(packet);
  }

  finish(): SemanticEvent[] {
    const events: SemanticEvent[] = [];
    for (const pending of this.slots) {
      if (pending && this.wanted(pending.type)) {
        events.push({ ...pending, index: events.length });
      }
    }
    return events;
  }

  private wanted(type: SemanticEventType): boolean {
    return this.options.types?.has(type) ?? true;
  }

  private emit(event: Pending): void {
    this.slots.push(event);
  }

  /** Reserves a position for an event whose data is only known after the children ran. */
  private reserve(): number {
    this.slots.push(undefined);
    return this.slots.length - 1;
  }

  private base(packetIndex: number): { packetIndex: number; blockIndex?: number; turn?: number } {
    const block = this.blocks[this.blocks.length - 1];
    const turn = this.state.turn;
    const result: { packetIndex: number; blockIndex?: number; turn?: number } = { packetIndex };
    if (block) result.blockIndex = block.packet.index;
    if (turn !== undefined) result.turn = turn;
    return result;
  }

  private facts(entityId: number): EntityFacts {
    const entity = this.state.entities.get(entityId);
    const result: { -readonly [K in keyof EntityFacts]: EntityFacts[K] } = { entity: entityId };
    if (!entity) return result;
    if (entity.cardId !== undefined) result.cardId = entity.cardId;
    const cardType = getCardType(entity);
    if (cardType !== undefined) result.cardType = cardType;
    const player = this.playerOf(entity);
    if (player !== undefined) result.playerEntityId = player;
    return result;
  }

  private playerOf(entity: Entity): number | undefined {
    const controller = getController(entity);
    return controller === undefined ? undefined : this.state.playerEntityIds.get(controller);
  }

  private resolve(ref: EntityRef | undefined): number | undefined {
    if (!ref) return undefined;
    if (ref.kind === 'id') return ref.id;
    return this.state.findPlayerByName(ref.name)?.id;
  }

  /** Block targets default to 0 when absent. */
  private target(ref: EntityRef | undefined): number | undefined {
    const id = this.resolve(ref);
    return id === undefined || id === 0 ? undefined : id;
  }

  private visit(packet: ReplayPacket): void {
    switch (packet.type) {
      case ReplayPacketType.BLOCK:
        this.visitBlock(packet);
        return;
      case ReplayPacketType.SUB_SPELL:
        this.visitAll(packet.children);
        return;
      case ReplayPacketType.GAME_ENTITY:
        applyPacket(this.state, packet, this.diagnostics);
        this.emit({
          type: SemanticEventType.GAME_STARTED,
          ...this.base(packet.index),
          gameEntityId: packet.id,
        });
        return;
      case ReplayPacketType.TAG_CHANGE: {
        const entityId = this.resolve(packet.entity);
        const before = entityId === undefined ? undefined : this.state.entities.get(entityId);
        const zoneBefore = before ? getZone(before) : undefined;
        applyPacket(this.state, packet, this.diagnostics);
        if (entityId === undefined) return;
        this.afterTagChange(packet.index, entityId, packet.tag, packet.value, zoneBefore);
        return;
      }
      case ReplayPacketType.SHOW_ENTITY:
      case ReplayPacketType.CHANGE_ENTITY:
      case ReplayPacketType.HIDE_ENTITY: {
        const entityId = this.resolve(packet.entity);
        const before = entityId === undefined ? undefined : this.state.entities.get(entityId);
        const zoneBefore = before ? getZone(before) : undefined;
        applyPacket(this.state, packet, this.diagnostics);
        if (entityId === undefined) return;
        const after = this.state.entities.get(entityId);
        const zoneAfter = after ? getZone(after) : undefined;
        if (zoneAfter !== undefined && zoneAfter !== zoneBefore)
          this.zoneChanged(packet.index, entityId, zoneBefore, zoneAfter);
        return;
      }
      case ReplayPacketType.CHOICES: {
        applyPacket(this.state, packet, this.diagnostics);
        const playerEntityId = this.resolve(packet.entity);
        const meta: { choiceType: number; playerEntityId?: number } = {
          choiceType: packet.choiceType,
        };
        if (playerEntityId !== undefined) meta.playerEntityId = playerEntityId;
        this.choiceTypes.set(packet.id, meta);
        this.emit({
          type: SemanticEventType.CHOICE_OFFERED,
          ...this.base(packet.index),
          choiceId: packet.id,
          choiceType: packet.choiceType,
          ...(playerEntityId === undefined ? {} : { playerEntityId }),
          source: packet.source,
          entities: packet.choices.map((choice) => choice.entity),
          min: packet.min,
          max: packet.max,
        });
        return;
      }
      case ReplayPacketType.CHOSEN_ENTITIES: {
        const offered = this.choiceTypes.get(packet.id);
        const playerEntityId = this.resolve(packet.entity) ?? offered?.playerEntityId;
        this.emit({
          type: SemanticEventType.CHOICE_MADE,
          ...this.base(packet.index),
          choiceId: packet.id,
          ...(offered ? { choiceType: offered.choiceType } : {}),
          ...(playerEntityId === undefined ? {} : { playerEntityId }),
          chosen: packet.choices.map((choice) => choice.entity),
        });
        return;
      }
      case ReplayPacketType.OPTIONS:
        this.lastOptions = packet;
        return;
      case ReplayPacketType.SEND_OPTION: {
        const options = this.lastOptions;
        const option = options?.options.find((entry) => entry.index === packet.option);
        const subOption =
          packet.subOption === undefined || packet.subOption < 0
            ? undefined
            : option?.subOptions.find((entry) => entry.index === packet.subOption);
        const target =
          packet.target && this.target(packet.target) !== undefined ? packet.target : undefined;
        this.emit({
          type: SemanticEventType.OPTION_CHOSEN,
          ...this.base(packet.index),
          ...(options ? { optionsId: options.id } : {}),
          ...(option ? { optionType: option.optionType } : {}),
          ...(option?.entity ? { entity: option.entity } : {}),
          ...(subOption ? { subOptionEntity: subOption.entity } : {}),
          ...(target ? { target } : {}),
          ...(packet.position === undefined ? {} : { position: packet.position }),
        });
        return;
      }
      case ReplayPacketType.META_DATA: {
        const type =
          packet.meta === 1
            ? SemanticEventType.DAMAGE
            : packet.meta === 2
              ? SemanticEventType.HEALING
              : undefined;
        if (type === undefined) return;
        const block = this.blocks[this.blocks.length - 1];
        const source = block ? this.resolve(block.packet.entity) : undefined;
        for (const info of packet.info) {
          this.emit({
            type,
            ...this.base(packet.index),
            target: info.entity,
            amount: packet.data,
            ...(source === undefined ? {} : { source }),
          });
        }
        return;
      }
      case ReplayPacketType.PLAYER:
      case ReplayPacketType.FULL_ENTITY:
      case ReplayPacketType.SEND_CHOICES:
      case ReplayPacketType.SHUFFLE_DECK:
      case ReplayPacketType.UNKNOWN:
        applyPacket(this.state, packet, this.diagnostics);
        return;
    }
  }

  private visitBlock(block: BlockPacket): void {
    const context: BlockContext = { packet: block };
    const entityId = this.resolve(block.entity);

    if (
      block.blockType === BlockType.TRIGGER &&
      block.triggerKeyword !== undefined &&
      entityId !== undefined
    ) {
      this.emit({
        type: SemanticEventType.TRIGGERED,
        ...this.base(block.index),
        ...this.facts(entityId),
        triggerKeyword: block.triggerKeyword,
      });
    }
    if (block.blockType === BlockType.FATIGUE && entityId !== undefined) {
      this.emit({
        type: SemanticEventType.FATIGUE,
        ...this.base(block.index),
        ...this.facts(entityId),
      });
    }

    const needsPost =
      entityId !== undefined &&
      (block.blockType === BlockType.PLAY || block.blockType === BlockType.ATTACK);
    const slot = needsPost ? this.reserve() : -1;
    const base = this.base(block.index);

    this.blocks.push(context);
    this.visitAll(block.children);
    this.blocks.pop();

    if (!needsPost) return;
    const target = this.target(block.target);
    if (block.blockType === BlockType.ATTACK) {
      this.slots[slot] = {
        type: SemanticEventType.ATTACK,
        ...base,
        ...this.facts(entityId),
        ...(target === undefined ? {} : { target }),
        ...(context.defender === undefined ? {} : { defender: context.defender }),
      };
      return;
    }
    const facts = this.facts(entityId);
    this.slots[slot] = {
      type:
        facts.cardType === CardType.HERO_POWER
          ? SemanticEventType.HERO_POWER_USED
          : SemanticEventType.CARD_PLAYED,
      ...base,
      ...facts,
      ...(target === undefined ? {} : { target }),
    };
  }

  private afterTagChange(
    packetIndex: number,
    entityId: number,
    tag: number,
    value: number,
    zoneBefore: number | undefined,
  ): void {
    switch (tag) {
      case GameTag.ZONE:
        if (value !== zoneBefore) this.zoneChanged(packetIndex, entityId, zoneBefore, value);
        return;
      case GameTag.DEFENDING:
        if (value === 1) {
          const attack = [...this.blocks]
            .reverse()
            .find((block) => block.packet.blockType === BlockType.ATTACK);
          if (attack) attack.defender = entityId;
        }
        return;
      case GameTag.TURN:
        if (entityId === this.state.gameEntityId) {
          const player = this.state.currentPlayer?.id;
          this.emit({
            type: SemanticEventType.TURN_STARTED,
            ...this.base(packetIndex),
            turn: value,
            ...(player === undefined ? {} : { playerEntityId: player }),
          });
        }
        return;
      case GameTag.STATE:
        if (entityId === this.state.gameEntityId && value === GameEntityState.COMPLETE)
          this.gameEnded(packetIndex);
        return;
      case GameTag.PLAYSTATE:
        if (value === PlayState.CONCEDED && this.state.playerEntityIds.size > 0) {
          this.emit({
            type: SemanticEventType.CONCEDED,
            ...this.base(packetIndex),
            playerEntityId: entityId,
          });
        }
        return;
      default:
        return;
    }
  }

  private zoneChanged(
    packetIndex: number,
    entityId: number,
    from: number | undefined,
    to: number,
  ): void {
    const facts = this.facts(entityId);
    this.emit({
      type: SemanticEventType.ZONE_CHANGED,
      ...this.base(packetIndex),
      ...facts,
      ...(from === undefined ? {} : { from }),
      to,
    });
    if (from === Zone.DECK && to === Zone.HAND) {
      this.emit({ type: SemanticEventType.CARD_DRAWN, ...this.base(packetIndex), ...facts });
    }
    if (from === Zone.PLAY && to === Zone.GRAVEYARD) {
      this.emit({ type: SemanticEventType.ENTITY_DIED, ...this.base(packetIndex), ...facts });
    }
  }

  private gameEnded(packetIndex: number): void {
    const results: PlayerResult[] = this.state.players.map((player) => ({
      playerEntityId: player.id,
      playState: player.tags.get(GameTag.PLAYSTATE),
    }));
    this.emit({
      type: SemanticEventType.GAME_ENDED,
      ...this.base(packetIndex),
      results,
      winners: results.filter((r) => r.playState === PlayState.WON).map((r) => r.playerEntityId),
      losers: results.filter((r) => r.playState === PlayState.LOST).map((r) => r.playerEntityId),
    });
  }
}
