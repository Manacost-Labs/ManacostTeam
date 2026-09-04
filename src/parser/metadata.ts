import { type DiagnosticCollector, DiagnosticCode } from '../diagnostics.js';
import { type GameMetadata, type ReplayPlayer } from '../replay.js';
import { AttributeReader, MalformedElementError } from './packets/attributes.js';
import { type ReplayPacket, ReplayPacketType } from './packets/types.js';
import { type XmlElement } from './xml/nodes.js';

export interface DocumentHeader {
  readonly version?: string;
  readonly build?: number;
}

export function readRootMetadata(
  root: XmlElement,
  diagnostics: DiagnosticCollector,
): DocumentHeader {
  const reader = new AttributeReader(root, diagnostics, undefined);
  const result: { version?: string; build?: number } = {};
  const version = reader.optionalString('version');
  if (version !== undefined) result.version = version;
  const build = tryInt(reader, 'build', diagnostics);
  if (build !== undefined) result.build = build;
  reader.unknown();
  return result;
}

export function readGameMetadata(game: XmlElement, diagnostics: DiagnosticCollector): GameMetadata {
  const reader = new AttributeReader(game, diagnostics, undefined);
  const result: { -readonly [K in keyof GameMetadata]: GameMetadata[K] } = {};
  const id = tryInt(reader, 'id', diagnostics);
  if (id !== undefined) result.id = id;
  const ts = reader.optionalString('ts');
  if (ts !== undefined) result.ts = ts;
  const gameType = tryInt(reader, 'type', diagnostics);
  if (gameType !== undefined) result.gameType = gameType;
  const format = tryInt(reader, 'format', diagnostics);
  if (format !== undefined) result.format = format;
  const scenarioId = tryInt(reader, 'scenarioID', diagnostics);
  if (scenarioId !== undefined) result.scenarioId = scenarioId;
  reader.unknown();
  return result;
}

// Metadata attributes are optional by nature; a bad value must not fail the parse.
function tryInt(
  reader: AttributeReader,
  name: string,
  diagnostics: DiagnosticCollector,
): number | undefined {
  try {
    return reader.optionalInt(name);
  } catch (error) {
    if (!(error instanceof MalformedElementError)) throw error;
    diagnostics.error(DiagnosticCode.MALFORMED_PACKET, error.message, reader.context());
    return undefined;
  }
}

export function collectPlayers(packets: readonly ReplayPacket[]): ReplayPlayer[] {
  const players: ReplayPlayer[] = [];
  for (const packet of packets) {
    if (packet.type !== ReplayPacketType.PLAYER) continue;
    const player: { -readonly [K in keyof ReplayPlayer]: ReplayPlayer[K] } = {
      entityId: packet.id,
      playerId: packet.playerId,
    };
    if (packet.name !== undefined) player.name = packet.name;
    if (packet.accountHi !== undefined) player.accountHi = packet.accountHi;
    if (packet.accountLo !== undefined) player.accountLo = packet.accountLo;
    if (packet.deck !== undefined) player.deck = packet.deck;
    players.push(player);
  }
  return players;
}
