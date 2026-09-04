import { DiagnosticCollector } from '../diagnostics.js';
import { type EntityRef } from '../parser/packets/entity-ref.js';
import {
  type BlockPacket,
  type MetaDataPacket,
  type OptionsPacket,
  type ReplayPacket,
  ReplayPacketType,
} from '../parser/packets/types.js';
import { type Entity, getCardType, getController, getZone } from '../state/entity.js';
import { applyPacket, GameState } from '../state/engine.js';
import { BlockType, GameEntityState, MetaDataType, PlayState, Step } from '../tags/enums.js';
import { CardType, GameTag, Zone } from '../tags/game-tag.js';
import {
  type EntityFacts,
  type EventInitiator,
  type PlayerResult,
  type SemanticEvent,
  SemanticEventType,
} from './events.js';
import { evidence, type SemanticRuleId } from './rules.js';

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
 * Every event names the rule that produced it (`evidence`). The rules live
 * in `rules.ts`; this file only applies them. When a rule's conditions are
 * not met nothing is emitted: a missing event is preferable to a wrong one.
 */
export function extractEvents(
  source: { readonly packets: readonly ReplayPacket[] } | readonly ReplayPacket[],
  options: ExtractEventsOptions = {},
): SemanticEvent[] {
  const packets = isPacketList(source) ? source : source.packets;
  const extractor = new EventExtractor(options);
  extractor.visitAll(packets);
  return extractor.finish();
}

function isPacketList(
  source: { readonly packets: readonly ReplayPacket[] } | readonly ReplayPacket[],
): source is readonly ReplayPacket[] {
  return Array.isArray(source);
}

type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;
/** An event before its sequential index and evidence are attached. */
type Draft = DistributiveOmit<SemanticEvent, 'index' | 'evidence'>;
type Pending = DistributiveOmit<SemanticEvent, 'index'>;

/** Card types for which leaving play for the graveyard means the entity died. */
const DYING_CARD_TYPES: ReadonlySet<number> = new Set([
  CardType.MINION,
  CardType.HERO,
  CardType.WEAPON,
  CardType.LOCATION,
]);

function isMainStep(step: number | undefined): boolean {
  return (
    step !== undefined &&
    step >= Step.MAIN_BEGIN &&
    step <= Step.MAIN_START_TRIGGERS &&
    step !== Step.FINAL_WRAPUP &&
    step !== Step.FINAL_GAMEOVER
  );
}

interface BlockContext {
  readonly packet: BlockPacket;
  /** Last entity whose DEFENDING tag went to 1 inside this block, and the packet that set it. */
  defender?: { entity: number; packetIndex: number };
}

class EventExtractor {
  private readonly state = new GameState();
  private readonly diagnostics = new DiagnosticCollector();
  private readonly slots: (Pending | undefined)[] = [];
  private readonly blocks: BlockContext[] = [];
  private readonly choices = new Map<
    number,
    { packetIndex: number; choiceType: number; playerEntityId?: number }
  >();
  private lastOptions: OptionsPacket | undefined;

  constructor(private readonly options: ExtractEventsOptions) {}

  visitAll(packets: readonly ReplayPacket[]): void {
    packets.forEach((packet, position) => {
      this.visit(packet, packets, position);
    });
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

  private emit(rule: SemanticRuleId, packetIndices: readonly number[], draft: Draft): void {
    this.slots.push(this.withEvidence(rule, packetIndices, draft));
  }

  private withEvidence(
    rule: SemanticRuleId,
    packetIndices: readonly number[],
    draft: Draft,
  ): Pending {
    return { ...draft, evidence: evidence(rule, packetIndices) };
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

  private innermostBlock(): BlockContext | undefined {
    return this.blocks[this.blocks.length - 1];
  }

  private visit(packet: ReplayPacket, siblings: readonly ReplayPacket[], position: number): void {
    switch (packet.type) {
      case ReplayPacketType.BLOCK:
        this.visitBlock(packet);
        return;
      case ReplayPacketType.SUB_SPELL:
        this.visitAll(packet.children);
        return;
      case ReplayPacketType.GAME_ENTITY:
        applyPacket(this.state, packet, this.diagnostics);
        this.emit('GAME_STARTED', [packet.index], {
          type: SemanticEventType.GAME_STARTED,
          ...this.base(packet.index),
          gameEntityId: packet.id,
        });
        return;
      case ReplayPacketType.TAG_CHANGE: {
        const entityId = this.resolve(packet.entity);
        const zoneBefore = this.zoneOf(entityId);
        applyPacket(this.state, packet, this.diagnostics);
        if (entityId === undefined) return;
        this.afterTagChange(packet.index, entityId, packet.tag, packet.value, zoneBefore);
        return;
      }
      case ReplayPacketType.SHOW_ENTITY:
      case ReplayPacketType.CHANGE_ENTITY:
      case ReplayPacketType.HIDE_ENTITY: {
        const entityId = this.resolve(packet.entity);
        const zoneBefore = this.zoneOf(entityId);
        applyPacket(this.state, packet, this.diagnostics);
        if (entityId === undefined) return;
        const zoneAfter = this.zoneOf(entityId);
        if (zoneAfter !== undefined && zoneAfter !== zoneBefore) {
          this.zoneChanged(packet.index, entityId, zoneBefore, zoneAfter);
        }
        return;
      }
      case ReplayPacketType.CHOICES:
        this.visitChoices(packet);
        return;
      case ReplayPacketType.CHOSEN_ENTITIES: {
        const offered = this.choices.get(packet.id);
        const playerEntityId = this.resolve(packet.entity) ?? offered?.playerEntityId;
        this.emit('CHOICE_MADE', offered ? [packet.index, offered.packetIndex] : [packet.index], {
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
      case ReplayPacketType.SEND_OPTION:
        this.visitSendOption(packet);
        return;
      case ReplayPacketType.META_DATA:
        this.visitMetaData(packet, siblings, position);
        return;
      case ReplayPacketType.PLAYER:
      case ReplayPacketType.FULL_ENTITY:
      case ReplayPacketType.SEND_CHOICES:
      case ReplayPacketType.SHUFFLE_DECK:
      case ReplayPacketType.UNKNOWN:
        applyPacket(this.state, packet, this.diagnostics);
        return;
    }
  }

  private zoneOf(entityId: number | undefined): number | undefined {
    if (entityId === undefined) return undefined;
    const entity = this.state.entities.get(entityId);
    return entity ? getZone(entity) : undefined;
  }

  private visitChoices(packet: Extract<ReplayPacket, { type: 'CHOICES' }>): void {
    applyPacket(this.state, packet, this.diagnostics);
    const playerEntityId = this.resolve(packet.entity);
    const record: { packetIndex: number; choiceType: number; playerEntityId?: number } = {
      packetIndex: packet.index,
      choiceType: packet.choiceType,
    };
    if (playerEntityId !== undefined) record.playerEntityId = playerEntityId;
    this.choices.set(packet.id, record);
    this.emit('CHOICE_OFFERED', [packet.index], {
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
  }

  private visitSendOption(packet: Extract<ReplayPacket, { type: 'SEND_OPTION' }>): void {
    const options = this.lastOptions;
    const option = options?.options.find((entry) => entry.index === packet.option);
    const subOption =
      packet.subOption === undefined || packet.subOption < 0
        ? undefined
        : option?.subOptions.find((entry) => entry.index === packet.subOption);
    const target =
      packet.target && this.target(packet.target) !== undefined ? packet.target : undefined;
    this.emit('OPTION_CHOSEN', options ? [packet.index, options.index] : [packet.index], {
      type: SemanticEventType.OPTION_CHOSEN,
      ...this.base(packet.index),
      ...(options ? { optionsId: options.id } : {}),
      ...(option ? { optionType: option.optionType } : {}),
      ...(option?.entity ? { entity: option.entity } : {}),
      ...(subOption ? { subOptionEntity: subOption.entity } : {}),
      ...(target ? { target } : {}),
      ...(packet.position === undefined ? {} : { position: packet.position }),
    });
  }

  private visitMetaData(
    packet: MetaDataPacket,
    siblings: readonly ReplayPacket[],
    position: number,
  ): void {
    const kind =
      packet.meta === MetaDataType.DAMAGE
        ? { type: SemanticEventType.DAMAGE, plain: 'DAMAGE', attributed: 'DAMAGE_SOURCE' }
        : packet.meta === MetaDataType.HEALING
          ? { type: SemanticEventType.HEALING, plain: 'HEALING', attributed: 'HEALING_SOURCE' }
          : undefined;
    if (!kind) return;
    const blockEntity = this.resolve(this.innermostBlock()?.packet.entity);
    for (const info of packet.info) {
      const affected = findLastAffectedBy(siblings, position, info.entity);
      this.emit(
        affected ? (kind.attributed as SemanticRuleId) : (kind.plain as SemanticRuleId),
        affected ? [packet.index, affected.packetIndex] : [packet.index],
        {
          type: kind.type,
          ...this.base(packet.index),
          target: info.entity,
          amount: packet.data,
          ...(affected ? { source: affected.source } : {}),
          ...(blockEntity === undefined ? {} : { blockEntity }),
        },
      );
    }
  }

  private visitBlock(block: BlockPacket): void {
    const context: BlockContext = { packet: block };
    const entityId = this.resolve(block.entity);
    const initiator: EventInitiator = this.blocks.length === 0 ? 'player' : 'effect';

    if (
      block.blockType === BlockType.TRIGGER &&
      block.triggerKeyword !== undefined &&
      entityId !== undefined
    ) {
      this.emit('TRIGGERED', [block.index], {
        type: SemanticEventType.TRIGGERED,
        ...this.base(block.index),
        ...this.facts(entityId),
        triggerKeyword: block.triggerKeyword,
      });
    }
    if (block.blockType === BlockType.GAME_RESET && entityId !== undefined) {
      this.emit('GAME_RESET', [block.index], {
        type: SemanticEventType.GAME_RESET,
        ...this.base(block.index),
        ...this.facts(entityId),
      });
    }
    if (block.blockType === BlockType.FATIGUE && entityId !== undefined) {
      this.emit('FATIGUE', [block.index], {
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
      const defender = context.defender;
      this.slots[slot] = this.withEvidence(
        'ATTACK',
        defender ? [block.index, defender.packetIndex] : [block.index],
        {
          type: SemanticEventType.ATTACK,
          ...base,
          ...this.facts(entityId),
          initiator,
          ...(target === undefined ? {} : { target }),
          ...(defender ? { defender: defender.entity } : {}),
        },
      );
      return;
    }
    const facts = this.facts(entityId);
    const isHeroPower = facts.cardType === CardType.HERO_POWER;
    this.slots[slot] = this.withEvidence(
      isHeroPower ? 'HERO_POWER_USED' : 'CARD_PLAYED',
      [block.index],
      {
        type: isHeroPower ? SemanticEventType.HERO_POWER_USED : SemanticEventType.CARD_PLAYED,
        ...base,
        ...facts,
        initiator,
        ...(target === undefined ? {} : { target }),
      },
    );
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
          if (attack) attack.defender = { entity: entityId, packetIndex };
        }
        return;
      case GameTag.TURN:
        if (entityId === this.state.gameEntityId) {
          const player = this.state.currentPlayer?.id;
          this.emit('TURN_STARTED', [packetIndex], {
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
          this.emit('CONCEDED', [packetIndex], {
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
    this.emit('ZONE_CHANGED', [packetIndex], {
      type: SemanticEventType.ZONE_CHANGED,
      ...this.base(packetIndex),
      ...facts,
      ...(from === undefined ? {} : { from }),
      to,
    });
    if (from === Zone.DECK && to === Zone.HAND && isMainStep(this.state.step)) {
      this.emit('CARD_DRAWN', [packetIndex], {
        type: SemanticEventType.CARD_DRAWN,
        ...this.base(packetIndex),
        ...facts,
      });
    }
    if (
      from === Zone.PLAY &&
      to === Zone.GRAVEYARD &&
      facts.cardType !== undefined &&
      DYING_CARD_TYPES.has(facts.cardType)
    ) {
      this.emit('ENTITY_DIED', [packetIndex], {
        type: SemanticEventType.ENTITY_DIED,
        ...this.base(packetIndex),
        ...facts,
      });
    }
  }

  private gameEnded(packetIndex: number): void {
    const results: PlayerResult[] = this.state.players.map((player) => ({
      playerEntityId: player.id,
      playState: player.tags.get(GameTag.PLAYSTATE),
    }));
    this.emit('GAME_ENDED', [packetIndex], {
      type: SemanticEventType.GAME_ENDED,
      ...this.base(packetIndex),
      results,
      winners: results.filter((r) => r.playState === PlayState.WON).map((r) => r.playerEntityId),
      losers: results.filter((r) => r.playState === PlayState.LOST).map((r) => r.playerEntityId),
    });
  }
}

/**
 * The log writes LAST_AFFECTED_BY on a damaged or healed entity after the
 * META_DATA packet, in the same container. The search stops at the target's
 * next META_DATA or DAMAGE tag change: past that point a LAST_AFFECTED_BY
 * would belong to a later hit. Absorbed hits (Divine Shield, Immune) write
 * neither, and stay unattributed.
 */
function findLastAffectedBy(
  siblings: readonly ReplayPacket[],
  position: number,
  target: EntityRef,
): { source: number; packetIndex: number } | undefined {
  if (target.kind !== 'id') return undefined;
  for (let i = position + 1; i < siblings.length; i++) {
    const packet = siblings[i];
    if (!packet) return undefined;
    if (packet.type === ReplayPacketType.META_DATA) {
      if (packet.info.some((info) => info.entity.kind === 'id' && info.entity.id === target.id))
        return undefined;
      continue;
    }
    if (
      packet.type !== ReplayPacketType.TAG_CHANGE ||
      packet.entity.kind !== 'id' ||
      packet.entity.id !== target.id
    ) {
      continue;
    }
    if (packet.tag === GameTag.LAST_AFFECTED_BY)
      return { source: packet.value, packetIndex: packet.index };
    if (packet.tag === GameTag.DAMAGE) return undefined;
  }
  return undefined;
}
