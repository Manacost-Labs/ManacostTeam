import { type ReplayDiagnostic, DiagnosticCollector } from '../diagnostics.js';
import {
  assembleReplay,
  assertRootName,
  GAME_ELEMENT,
  reportBareGameRoot,
  reportForeignRootChild,
} from '../parse-replay.js';
import {
  type GameMetadata,
  type ParseReplayOptions,
  type Replay,
  type ReplayDocument,
} from '../replay.js';
import { applyPacket, createGameState, type GameState } from '../state/engine.js';
import { type DocumentHeader, readGameMetadata, readRootMetadata } from './metadata.js';
import { GamePacketizer } from './packets/packetizer.js';
import { type ReplayPacket } from './packets/types.js';
import { type XmlElement } from './xml/nodes.js';
import { XmlTreeBuilder } from './xml/parser.js';

export type ReplayStreamChunk = string | Uint8Array;
export type ReplayStreamSource = AsyncIterable<ReplayStreamChunk> | Iterable<ReplayStreamChunk>;

/** Events produced while streaming a document, in document order. */
export type ReplayStreamEvent =
  | { readonly kind: 'document'; readonly header: DocumentHeader }
  | { readonly kind: 'game-start'; readonly gameIndex: number; readonly game: GameMetadata }
  | { readonly kind: 'packet'; readonly gameIndex: number; readonly packet: ReplayPacket }
  | {
      readonly kind: 'game-end';
      readonly gameIndex: number;
      readonly packetCount: number;
      readonly diagnostics: readonly ReplayDiagnostic[];
    }
  | { readonly kind: 'end'; readonly diagnostics: readonly ReplayDiagnostic[] };

interface OpenGame {
  readonly index: number;
  readonly element: XmlElement;
  readonly diagnostics: DiagnosticCollector;
  readonly packetizer: GamePacketizer;
}

/**
 * Streams an HSReplay document chunk by chunk. Top-level packets are emitted
 * as soon as their element closes and are then released, so memory stays
 * proportional to the largest single top-level packet, not to the document.
 */
export async function* streamReplay(
  source: ReplayStreamSource,
  options: ParseReplayOptions = {},
): AsyncGenerator<ReplayStreamEvent, void, undefined> {
  const strict = options.strict ?? false;
  const diagnostics = new DiagnosticCollector(strict);
  const queue: ReplayStreamEvent[] = [];
  let gameDepth = 1;
  let current: OpenGame | undefined;
  let gameCount = 0;

  const builder = new XmlTreeBuilder(diagnostics, options, {
    onOpen(element, depth) {
      if (depth === 0) {
        if (element.name === GAME_ELEMENT) {
          reportBareGameRoot(element, diagnostics);
          gameDepth = 0;
          queue.push({ kind: 'document', header: {} });
        } else {
          assertRootName(element);
          queue.push({ kind: 'document', header: readRootMetadata(element, diagnostics) });
        }
      }
      if (depth === gameDepth && element.name === GAME_ELEMENT) {
        const gameDiagnostics = new DiagnosticCollector(strict);
        current = {
          index: gameCount++,
          element,
          diagnostics: gameDiagnostics,
          packetizer: new GamePacketizer(gameDiagnostics),
        };
        queue.push({
          kind: 'game-start',
          gameIndex: current.index,
          game: readGameMetadata(element, gameDiagnostics),
        });
      }
    },
    onClose(element, depth, parent) {
      if (current && depth === gameDepth + 1 && parent === current.element) {
        queue.push({
          kind: 'packet',
          gameIndex: current.index,
          packet: current.packetizer.packetizeElement(element),
        });
        return false;
      }
      if (current?.element === element) {
        queue.push({
          kind: 'game-end',
          gameIndex: current.index,
          packetCount: current.packetizer.count,
          diagnostics: current.diagnostics.items,
        });
        current = undefined;
        return false;
      }
      if (depth === 1 && gameDepth === 1) {
        reportForeignRootChild(element, diagnostics);
        return false;
      }
      return true;
    },
  });

  const decoder = new TextDecoder('utf-8');
  for await (const chunk of source) {
    builder.write(typeof chunk === 'string' ? chunk : decoder.decode(chunk, { stream: true }));
    yield* drain(queue);
  }
  const tail = decoder.decode();
  if (tail.length > 0) builder.write(tail);
  builder.end();
  yield* drain(queue);
  yield { kind: 'end', diagnostics: diagnostics.items };
}

function* drain(queue: ReplayStreamEvent[]): Generator<ReplayStreamEvent, void, undefined> {
  while (queue.length > 0) {
    const event = queue.shift();
    if (event) yield event;
  }
}

/**
 * Builds a full `ReplayDocument` from a chunked source. Same result as
 * `parseReplayDocument`, without ever holding the whole XML or its element
 * tree in memory.
 */
export async function parseReplayStream(
  source: ReplayStreamSource,
  options: ParseReplayOptions = {},
): Promise<ReplayDocument> {
  let header: DocumentHeader = {};
  const games: Replay[] = [];
  let open:
    | {
        game: GameMetadata;
        packets: ReplayPacket[];
        state: GameState;
        diagnostics: DiagnosticCollector;
      }
    | undefined;
  let documentDiagnostics: readonly ReplayDiagnostic[] = [];

  for await (const event of streamReplay(source, options)) {
    switch (event.kind) {
      case 'document':
        header = event.header;
        break;
      case 'game-start':
        open = {
          game: event.game,
          packets: [],
          state: createGameState(),
          diagnostics: new DiagnosticCollector(options.strict ?? false),
        };
        break;
      case 'packet':
        if (open) {
          open.packets.push(event.packet);
          applyPacket(open.state, event.packet, open.diagnostics);
        }
        break;
      case 'game-end':
        if (open) {
          // Packet-level diagnostics come first, then the state diagnostics
          // collected while applying, matching the non-streaming order.
          const merged = new DiagnosticCollector(options.strict ?? false);
          merged.items.push(...event.diagnostics, ...open.diagnostics.items);
          games.push(
            assembleReplay(header, open.game, open.packets, event.packetCount, open.state, merged),
          );
          open = undefined;
        }
        break;
      case 'end':
        documentDiagnostics = event.diagnostics;
        break;
    }
  }
  return { ...header, games, diagnostics: documentDiagnostics };
}
