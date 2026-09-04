import { type ReplayPacket, ReplayPacketType, type TagPair } from '../parser/packets/types.js';
import { walkPackets } from '../parser/packets/walk.js';
import { GameTag } from '../tags/game-tag.js';

/** One observed value of a tag: set by the packet at `packetIndex`. */
export interface TagValueRecord {
  readonly packetIndex: number;
  readonly value: number;
}

/** entity id → tag → chronological values. */
export type TagHistory = ReadonlyMap<number, ReadonlyMap<number, readonly TagValueRecord[]>>;

export interface TagHistoryFilter {
  /** Only record these entity ids. */
  readonly entities?: ReadonlySet<number>;
  /** Only record these tags. */
  readonly tags?: ReadonlySet<number>;
}

/**
 * Collects every value each tag took over the replay, in packet order.
 * Entity definitions, reveals, changes, hides and tag changes all count,
 * mirroring exactly what the state engine applies.
 */
export function collectTagHistory(
  packets: readonly ReplayPacket[],
  filter: TagHistoryFilter = {},
): TagHistory {
  const history = new Map<number, Map<number, TagValueRecord[]>>();

  const record = (entityId: number, tag: number, value: number, packetIndex: number): void => {
    if (filter.entities && !filter.entities.has(entityId)) return;
    if (filter.tags && !filter.tags.has(tag)) return;
    let byTag = history.get(entityId);
    if (!byTag) history.set(entityId, (byTag = new Map<number, TagValueRecord[]>()));
    let values = byTag.get(tag);
    if (!values) byTag.set(tag, (values = []));
    values.push({ packetIndex, value });
  };

  const recordAll = (entityId: number, tags: readonly TagPair[], packetIndex: number): void => {
    for (const { tag, value } of tags) record(entityId, tag, value, packetIndex);
  };

  for (const { packet } of walkPackets(packets)) {
    switch (packet.type) {
      case ReplayPacketType.GAME_ENTITY:
      case ReplayPacketType.PLAYER:
      case ReplayPacketType.FULL_ENTITY:
        recordAll(packet.id, packet.tags, packet.index);
        break;
      case ReplayPacketType.SHOW_ENTITY:
      case ReplayPacketType.CHANGE_ENTITY:
        if (packet.entity.kind === 'id') recordAll(packet.entity.id, packet.tags, packet.index);
        break;
      case ReplayPacketType.HIDE_ENTITY:
        if (packet.entity.kind === 'id')
          record(packet.entity.id, GameTag.ZONE, packet.zone, packet.index);
        break;
      case ReplayPacketType.TAG_CHANGE:
        if (packet.entity.kind === 'id')
          record(packet.entity.id, packet.tag, packet.value, packet.index);
        break;
      case ReplayPacketType.BLOCK:
      case ReplayPacketType.SUB_SPELL:
      case ReplayPacketType.META_DATA:
      case ReplayPacketType.CHOICES:
      case ReplayPacketType.CHOSEN_ENTITIES:
      case ReplayPacketType.SEND_CHOICES:
      case ReplayPacketType.OPTIONS:
      case ReplayPacketType.SEND_OPTION:
      case ReplayPacketType.SHUFFLE_DECK:
      case ReplayPacketType.UNKNOWN:
        break;
    }
  }
  return history;
}
