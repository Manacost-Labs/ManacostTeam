import { type ContainerPacket, isContainerPacket, type ReplayPacket } from './types.js';

export interface PacketVisit {
  readonly packet: ReplayPacket;
  /** 0 for top-level packets. */
  readonly depth: number;
  readonly parent: ContainerPacket | undefined;
}

/** Depth-first, document-order traversal of a packet hierarchy. */
export function* walkPackets(
  packets: readonly ReplayPacket[],
  depth = 0,
  parent?: ContainerPacket,
): Generator<PacketVisit, void, undefined> {
  for (const packet of packets) {
    yield { packet, depth, parent };
    if (isContainerPacket(packet)) {
      yield* walkPackets(packet.children, depth + 1, packet);
    }
  }
}

/** Flat list of every packet in index order. The hierarchy inside containers is untouched. */
export function flattenPackets(packets: readonly ReplayPacket[]): ReplayPacket[] {
  const result: ReplayPacket[] = [];
  for (const { packet } of walkPackets(packets)) result.push(packet);
  return result;
}
