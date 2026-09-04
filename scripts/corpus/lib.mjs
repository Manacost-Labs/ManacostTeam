// Shared helpers for the corpus tooling. Run after `pnpm build`.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import {
  BlockType,
  CardType,
  ChoiceType,
  extractEvents,
  flattenPackets,
  GameTag,
  parseReplayDocument,
  Zone,
} from '../../dist/index.js';

export const MANIFEST_URL = new URL('../../test/corpus/manifest.json', import.meta.url);
export const CORPUS_DIR = fileURLToPath(new URL('../../test/corpus/', import.meta.url));

export const ACCEPTED_LICENSES = new Set([
  'CC0-1.0',
  'MIT',
  'Apache-2.0',
  'BSD-2-Clause',
  'BSD-3-Clause',
  'CC-BY-4.0',
  'CC-BY-SA-4.0',
  'project fixture',
]);

export function loadManifest() {
  return JSON.parse(readFileSync(MANIFEST_URL, 'utf8'));
}

export function sha256(buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

const GAME_TYPE_MODES = {
  1: 'vs_ai',
  2: 'vs_friend',
  4: 'tutorial',
  5: 'arena',
  7: 'ranked',
  8: 'casual',
  16: 'tavern_brawl',
  23: 'battlegrounds',
  24: 'battlegrounds',
  28: 'duels',
  29: 'duels',
  30: 'mercenaries',
  31: 'mercenaries',
  32: 'mercenaries',
};
const FORMAT_MODES = { 1: 'wild', 2: 'standard', 3: 'classic', 4: 'twist' };

/** Mode label derived only from the Game element's own attributes. */
export function gameMode(gameType, formatType, hint) {
  if (hint) return hint;
  if (gameType === 7 || gameType === 8)
    return FORMAT_MODES[formatType] ?? GAME_TYPE_MODES[gameType];
  return GAME_TYPE_MODES[gameType] ?? null;
}

export function folderFor(mode, edge) {
  if (edge) return 'edge';
  if (mode === null) return 'legacy';
  if (['vs_ai', 'vs_friend', 'casual', 'tutorial'].includes(mode)) return 'friendly';
  return mode;
}

/**
 * Metadata that can be read from the replay itself, plus features confirmed
 * from packets (never from file names) and the semantic event counts.
 */
export function describeReplay(xml) {
  const document = parseReplayDocument(xml);
  const game = document.games[0];
  const eventCounts = {};
  const features = new Set();
  const anomalies = new Set();
  const diagnostics = [...document.diagnostics, ...document.games.flatMap((g) => g.diagnostics)];
  let lastTurn = 0;
  let resetSince = false;
  for (const g of document.games) {
    const events = extractEvents(g);
    for (const event of events) {
      eventCounts[event.type] = (eventCounts[event.type] ?? 0) + 1;
      if (event.type === 'GAME_RESET') {
        features.add('GAME_RESET');
        anomalies.add('GAME_RESET');
        resetSince = true;
      }
      if (event.type === 'TURN_STARTED') {
        if (event.turn < lastTurn && !resetSince) anomalies.add('TURN_NOT_MONOTONIC');
        lastTurn = event.turn;
        resetSince = false;
      }
      if (event.type === 'CHOICE_OFFERED')
        features.add(event.choiceType === ChoiceType.MULLIGAN ? 'MULLIGAN' : 'DISCOVER_OR_CHOICE');
      if (event.type === 'FATIGUE') features.add('FATIGUE');
      if (event.type === 'HERO_POWER_USED') features.add('HERO_POWER');
      if (
        event.type === 'ATTACK' &&
        event.target !== undefined &&
        event.defender !== undefined &&
        event.target !== event.defender
      )
        features.add('REDIRECTED_ATTACK');
      if (event.type === 'ATTACK' && event.initiator === 'effect') features.add('FORCED_ATTACK');
      if (event.type === 'CARD_PLAYED' && event.initiator === 'effect') features.add('EFFECT_PLAY');
    }
    for (const packet of flattenPackets(g.packets)) {
      if (packet.type === 'SUB_SPELL') features.add('SUB_SPELL');
      if (packet.type === 'SHUFFLE_DECK') features.add('SHUFFLE_DECK');
      if (packet.type === 'CHANGE_ENTITY') features.add('CHANGE_ENTITY');
      if (packet.type === 'PLAYER' && packet.deck) features.add('DECKLIST');
      if (
        packet.type === 'TAG_CHANGE' &&
        packet.tag === GameTag.ZONE &&
        packet.value === Zone.SECRET
      )
        features.add('SECRET_ZONE');
      if (packet.type === 'BLOCK' && packet.blockType === BlockType.ATTACK) features.add('ATTACK');
      if (packet.type === 'BLOCK' && packet.blockType === BlockType.DEATHS) features.add('DEATHS');
    }
    for (const entity of g.entities) {
      const cardType = entity.tags.get(GameTag.CARDTYPE);
      if (cardType === CardType.WEAPON) features.add('WEAPON');
      if (cardType === CardType.LOCATION) features.add('LOCATION');
    }
    if (!events.some((event) => event.type === 'GAME_ENDED')) anomalies.add('NO_GAME_END');
  }
  if (
    diagnostics.some(
      (d) => d.code === 'UNKNOWN_ATTRIBUTE' && d.message.includes('<Game>: reconnecting'),
    )
  )
    anomalies.add('RECONNECT');
  if (diagnostics.some((d) => d.code === 'LEGACY_ELEMENT')) features.add('LEGACY_ACTION');
  // hsreplaynet annotations show up as these attributes on Tag / TagChange elements; confirmed from packets, not from the file name.
  const annotated = document.games.some((g) =>
    flattenPackets(g.packets).some(
      (p) =>
        p.unknownAttributes !== undefined &&
        ('GameTagName' in p.unknownAttributes || 'EntityCardName' in p.unknownAttributes),
    ),
  );
  if (document.games.length > 1) anomalies.add('MULTIPLE_GAMES');
  return {
    hsreplayVersion: document.version ?? null,
    build: document.build ?? null,
    gameType: game?.metadata.game.gameType ?? null,
    formatType: game?.metadata.game.format ?? null,
    annotated,
    gameCount: document.games.length,
    playerCount: game?.metadata.players.length ?? 0,
    features: [...features].sort(),
    knownAnomalies: [...anomalies].sort(),
    eventCounts: Object.fromEntries(
      Object.entries(eventCounts).sort(([a], [b]) => a.localeCompare(b)),
    ),
    errorDiagnostics: diagnostics.filter((d) => d.level === 'error').length,
    unknownPackets: document.games.reduce(
      (n, g) => n + flattenPackets(g.packets).filter((p) => p.type === 'UNKNOWN').length,
      0,
    ),
  };
}
