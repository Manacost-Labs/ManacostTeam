import { DiagnosticCollector } from '../diagnostics.js';
import { ReplayValidationError } from '../errors.js';
import { isContainerPacket, type ReplayPacket } from '../parser/packets/types.js';
import { flattenPackets } from '../parser/packets/walk.js';
import { applyPacket, GameState } from './engine.js';
import { type GameStateSnapshot, restoreState, snapshotState } from './snapshot.js';

export interface TimelineOptions {
  /** Take a checkpoint every N packets. Defaults to 1000. */
  readonly checkpointInterval?: number;
}

const DEFAULT_CHECKPOINT_INTERVAL = 1000;

/**
 * Random access to the observed state at any packet index. Checkpoints are
 * immutable snapshots taken at a fixed interval; `stateAt` restores the
 * nearest one and replays the few packets that follow it.
 *
 * Only leaf packets change state, so containers are stepped through as
 * no-ops and their children are applied individually. The end result is
 * identical to `applyPackets` over the hierarchy.
 */
export class ReplayTimeline {
  /** Every packet in index order. */
  readonly packets: readonly ReplayPacket[];
  readonly checkpoints: readonly GameStateSnapshot[];

  constructor(packets: readonly ReplayPacket[], options: TimelineOptions = {}) {
    const interval = options.checkpointInterval ?? DEFAULT_CHECKPOINT_INTERVAL;
    if (!Number.isInteger(interval) || interval < 1) {
      throw new ReplayValidationError(
        'INVALID_OPTION',
        'checkpointInterval must be a positive integer',
      );
    }
    this.packets = flattenPackets(packets);

    const checkpoints: GameStateSnapshot[] = [];
    const state = new GameState();
    const diagnostics = new DiagnosticCollector();
    this.packets.forEach((packet, position) => {
      applyLeaf(state, packet, diagnostics);
      if ((position + 1) % interval === 0) checkpoints.push(snapshotState(state, packet.index));
    });
    this.checkpoints = checkpoints;
  }

  get packetCount(): number {
    return this.packets.length;
  }

  /**
   * State after the packet with `packetIndex` has been applied. Pass -1 for
   * the state before anything happened. Returns a fresh mutable `GameState`
   * every time; mutate it freely.
   */
  stateAt(packetIndex: number): GameState {
    if (!Number.isInteger(packetIndex) || packetIndex < -1 || packetIndex >= this.packets.length) {
      throw new ReplayValidationError(
        'PACKET_INDEX_OUT_OF_RANGE',
        `packet index ${String(packetIndex)} is outside -1..${String(this.packets.length - 1)}`,
      );
    }
    const checkpoint = this.nearestCheckpoint(packetIndex);
    const state = checkpoint ? restoreState(checkpoint) : new GameState();
    const diagnostics = new DiagnosticCollector();
    const start = checkpoint ? checkpoint.packetIndex + 1 : 0;
    for (let position = start; position <= packetIndex; position++) {
      const packet = this.packets[position];
      if (packet) applyLeaf(state, packet, diagnostics);
    }
    return state;
  }

  /** Last checkpoint whose packet index is <= `packetIndex`, found by binary search. */
  private nearestCheckpoint(packetIndex: number): GameStateSnapshot | undefined {
    let low = 0;
    let high = this.checkpoints.length - 1;
    let found: GameStateSnapshot | undefined;
    while (low <= high) {
      const middle = (low + high) >>> 1;
      const candidate = this.checkpoints[middle];
      if (candidate && candidate.packetIndex <= packetIndex) {
        found = candidate;
        low = middle + 1;
      } else {
        high = middle - 1;
      }
    }
    return found;
  }
}

function applyLeaf(state: GameState, packet: ReplayPacket, diagnostics: DiagnosticCollector): void {
  if (!isContainerPacket(packet)) applyPacket(state, packet, diagnostics);
}

export function createTimeline(
  source: { readonly packets: readonly ReplayPacket[] } | readonly ReplayPacket[],
  options?: TimelineOptions,
): ReplayTimeline {
  return new ReplayTimeline(
    Array.isArray(source) ? source : (source as { packets: readonly ReplayPacket[] }).packets,
    options,
  );
}
