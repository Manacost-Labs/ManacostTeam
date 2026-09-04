import { type DiagnosticCollector, DiagnosticCode } from '../../diagnostics.js';
import { type XmlElement } from '../xml/nodes.js';
import { MalformedElementError } from './attributes.js';
import { NODE_PARSERS, type NodeParseContext, parseUnknown } from './node-parsers.js';
import { type ReplayPacket } from './types.js';

export interface PacketizeResult {
  /** Top-level packets in document order; containers hold their children. */
  readonly packets: ReplayPacket[];
  /** Total number of packets including nested ones. */
  readonly packetCount: number;
}

/**
 * Turns the children of a `Game` element into packets. Indexes are assigned
 * in document order (pre-order), so a container packet is numbered before
 * its children and every index is unique across the replay.
 */
export function packetizeGame(game: XmlElement, diagnostics: DiagnosticCollector): PacketizeResult {
  const packetizer = new GamePacketizer(diagnostics);
  const packets = packetizer.packetize(game.children);
  return { packets, packetCount: packetizer.count };
}

/** Converts elements of one game into packets, one element at a time, keeping a running index. */
export class GamePacketizer {
  /** Number of packets produced so far, nested ones included. */
  count = 0;

  constructor(private readonly diagnostics: DiagnosticCollector) {}

  packetize(elements: readonly XmlElement[]): ReplayPacket[] {
    const packets: ReplayPacket[] = [];
    for (const element of elements) packets.push(this.packetizeElement(element));
    return packets;
  }

  packetizeElement(element: XmlElement): ReplayPacket {
    const index = this.count++;
    const ctx: NodeParseContext = {
      diagnostics: this.diagnostics,
      index,
      packetizeChildren: (children) => this.packetize(children),
    };
    const parser = NODE_PARSERS.get(element.name);
    if (!parser) {
      this.diagnostics.violation(DiagnosticCode.UNKNOWN_NODE, `unknown element <${element.name}>`, {
        packetIndex: index,
        line: element.line,
        column: element.column,
      });
      return parseUnknown(element, ctx);
    }
    try {
      return parser(element, ctx);
    } catch (error) {
      if (!(error instanceof MalformedElementError)) throw error;
      this.diagnostics.error(DiagnosticCode.MALFORMED_PACKET, error.message, {
        packetIndex: index,
        line: element.line,
        column: element.column,
      });
      return parseUnknown(element, ctx);
    }
  }
}
