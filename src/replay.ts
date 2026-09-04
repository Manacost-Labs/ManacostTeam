import { type ReplayDiagnostic } from './diagnostics.js';
import { type DeckList, type ReplayPacket } from './parser/packets/types.js';
import { type XmlParseOptions } from './parser/xml/parser.js';
import { type GameState } from './state/engine.js';
import { type EntityStore } from './state/entity-store.js';

export interface GameMetadata {
  readonly id?: number;
  /** Raw RFC 3339 timestamp of the game start. */
  readonly ts?: string;
  /** Raw `GameType` enum value. */
  readonly gameType?: number;
  /** Raw `FormatType` enum value. */
  readonly format?: number;
  readonly scenarioId?: number;
}

export interface ReplayPlayer {
  readonly entityId: number;
  readonly playerId: number;
  readonly name?: string;
  readonly accountHi?: string;
  readonly accountLo?: string;
  readonly deck?: DeckList;
}

export interface ReplayMetadata {
  /** HSReplay spec version, e.g. `"1.7"`. */
  readonly version?: string;
  /** Hearthstone client build that produced the log. */
  readonly build?: number;
  readonly game: GameMetadata;
  readonly players: readonly ReplayPlayer[];
}

export interface Replay {
  readonly metadata: ReplayMetadata;
  /** Top-level packets in document order. Containers (`BLOCK`, `SUB_SPELL`) hold their children. */
  readonly packets: readonly ReplayPacket[];
  /** Total number of packets including nested ones. */
  readonly packetCount: number;
  /** Final observed entity state after every packet was applied. Same object as `state.entities`. */
  readonly entities: EntityStore;
  readonly state: GameState;
  readonly diagnostics: readonly ReplayDiagnostic[];
}

/** A whole HSReplay document, which may hold several games. */
export interface ReplayDocument {
  readonly version?: string;
  readonly build?: number;
  readonly games: readonly Replay[];
  /** Document-level diagnostics (XML, root element). Game-level ones live on each `Replay`. */
  readonly diagnostics: readonly ReplayDiagnostic[];
}

export interface ParseReplayOptions extends XmlParseOptions {
  /**
   * When true, anything the lenient parser would merely report (unknown
   * elements, malformed packets, unknown entities, …) throws a
   * `ReplayValidationError` instead. Defaults to false.
   */
  readonly strict?: boolean;
}
