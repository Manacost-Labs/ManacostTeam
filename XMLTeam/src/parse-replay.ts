import { DiagnosticCode, DiagnosticCollector } from './diagnostics.js';
import { ReplayParseError, ReplayValidationError } from './errors.js';
import {
  collectPlayers,
  type DocumentHeader,
  readGameMetadata,
  readRootMetadata,
} from './parser/metadata.js';
import { packetizeGame } from './parser/packets/packetizer.js';
import { type ReplayPacket } from './parser/packets/types.js';
import { type XmlElement } from './parser/xml/nodes.js';
import { parseXml } from './parser/xml/parser.js';
import {
  type GameMetadata,
  type ParseReplayOptions,
  type Replay,
  type ReplayDocument,
} from './replay.js';
import { applyPackets, createGameState, type GameState } from './state/engine.js';

export const ROOT_ELEMENT = 'HSReplay';
export const GAME_ELEMENT = 'Game';

/**
 * Parses an HSReplay XML document with every game it contains.
 *
 * Synchronous and free of Node.js dependencies, so it runs in a browser. Use
 * `parseReplayDocumentFile` from `@manacost/hearthstone-replay/node` to read
 * from disk, or `parseReplayStream` to avoid holding the XML in memory.
 */
export function parseReplayDocument(xml: string, options: ParseReplayOptions = {}): ReplayDocument {
  if (typeof xml !== 'string') {
    throw new ReplayParseError('INVALID_INPUT', 'expected the replay XML as a string');
  }
  const strict = options.strict ?? false;
  const diagnostics = new DiagnosticCollector(strict);
  const document = parseXml(xml, diagnostics, options);
  const { root, games } = locateGames(document.root, diagnostics);
  const header = root ? readRootMetadata(root, diagnostics) : {};

  return {
    ...header,
    games: games.map((game) => parseGame(game, header, strict)),
    diagnostics: diagnostics.items,
  };
}

/**
 * Parses the first game of an HSReplay document into raw packets and the
 * observed game state. Documents with several games are reported with a
 * `MULTIPLE_GAMES` diagnostic; use `parseReplayDocument` to get all of them.
 */
export function parseReplay(xml: string, options: ParseReplayOptions = {}): Replay {
  return firstGame(parseReplayDocument(xml, options), options);
}

/** Picks the first game of a document, merging document-level diagnostics into it. */
export function firstGame(document: ReplayDocument, options: ParseReplayOptions = {}): Replay {
  const first = document.games[0];
  if (!first) {
    throw new ReplayValidationError(
      'NO_GAME',
      `<${ROOT_ELEMENT}> contains no <${GAME_ELEMENT}> element`,
    );
  }
  const diagnostics = new DiagnosticCollector(options.strict ?? false);
  diagnostics.items.push(...document.diagnostics);
  if (document.games.length > 1) {
    diagnostics.violation(
      DiagnosticCode.MULTIPLE_GAMES,
      `found ${String(document.games.length)} <${GAME_ELEMENT}> elements; only the first one is returned, use parseReplayDocument for all`,
    );
  }
  diagnostics.items.push(...first.diagnostics);
  return { ...first, diagnostics: diagnostics.items };
}

function parseGame(game: XmlElement, header: DocumentHeader, strict: boolean): Replay {
  const diagnostics = new DiagnosticCollector(strict);
  // Same order as the streaming parser: game attributes first, then packets, then state.
  const metadata = readGameMetadata(game, diagnostics);
  const { packets, packetCount } = packetizeGame(game, diagnostics);
  const state = createGameState();
  applyPackets(state, packets, diagnostics);
  return assembleReplay(header, metadata, packets, packetCount, state, diagnostics);
}

export function assembleReplay(
  header: DocumentHeader,
  game: GameMetadata,
  packets: readonly ReplayPacket[],
  packetCount: number,
  state: GameState,
  diagnostics: DiagnosticCollector,
): Replay {
  return {
    metadata: { ...header, game, players: collectPlayers(packets) },
    packets,
    packetCount,
    entities: state.entities,
    state,
    diagnostics: diagnostics.items,
  };
}

/** Validates the root element and returns the game elements beneath it. */
export function locateGames(
  root: XmlElement,
  diagnostics: DiagnosticCollector,
): { root: XmlElement | undefined; games: XmlElement[] } {
  if (root.name === GAME_ELEMENT) {
    reportBareGameRoot(root, diagnostics);
    return { root: undefined, games: [root] };
  }
  assertRootName(root);
  const games: XmlElement[] = [];
  for (const child of root.children) {
    if (child.name === GAME_ELEMENT) {
      games.push(child);
    } else {
      reportForeignRootChild(child, diagnostics);
    }
  }
  return { root, games };
}

export function reportBareGameRoot(root: XmlElement, diagnostics: DiagnosticCollector): void {
  diagnostics.violation(
    DiagnosticCode.UNEXPECTED_ROOT,
    `root element is <${GAME_ELEMENT}>; expected <${ROOT_ELEMENT}>`,
    { line: root.line, column: root.column },
  );
}

export function assertRootName(root: XmlElement): void {
  if (root.name !== ROOT_ELEMENT) {
    throw new ReplayValidationError(
      DiagnosticCode.UNEXPECTED_ROOT,
      `root element is <${root.name}>; expected <${ROOT_ELEMENT}>`,
      { context: { element: root.name, line: root.line, column: root.column } },
    );
  }
}

export function reportForeignRootChild(child: XmlElement, diagnostics: DiagnosticCollector): void {
  diagnostics.violation(
    DiagnosticCode.UNKNOWN_NODE,
    `unknown element <${child.name}> under <${ROOT_ELEMENT}>`,
    {
      line: child.line,
      column: child.column,
    },
  );
}
