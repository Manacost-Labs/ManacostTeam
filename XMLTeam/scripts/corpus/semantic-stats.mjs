// Reproducible numbers behind the semantic rules, computed over the corpus.
// Run after `pnpm build`:  node scripts/corpus/semantic-stats.mjs [--json]
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import {
  applyPacket,
  CardType,
  createGameState,
  enumName,
  extractEvents,
  flattenPackets,
  GameTag,
  isContainerPacket,
  parseReplayDocument,
  Step,
  Zone,
} from '../../dist/index.js';
import { DiagnosticCollector } from '../../dist/diagnostics.js';

const manifestUrl = new URL('../../test/corpus/manifest.json', import.meta.url);
const manifest = JSON.parse(readFileSync(manifestUrl, 'utf8'));
const json = process.argv.includes('--json');

const stats = {
  replays: 0,
  eventTypes: {},
  playToGraveyardByCardType: {},
  deckToHandByStep: {},
  damage: { attributed: 0, unattributed: 0, blockEntityDiffersFromSource: 0 },
  perFile: {},
};

for (const entry of manifest.entries) {
  const path = fileURLToPath(new URL(entry.file, manifestUrl));
  const document = parseReplayDocument(readFileSync(path, 'utf8'));
  for (const game of document.games) {
    stats.replays++;
    const counts = {};
    for (const event of extractEvents(game)) {
      counts[event.type] = (counts[event.type] ?? 0) + 1;
      stats.eventTypes[event.type] = (stats.eventTypes[event.type] ?? 0) + 1;
      if (event.type === 'DAMAGE') {
        if (event.source === undefined) stats.damage.unattributed++;
        else {
          stats.damage.attributed++;
          if (event.blockEntity !== undefined && event.blockEntity !== event.source)
            stats.damage.blockEntityDiffersFromSource++;
        }
      }
    }
    stats.perFile[entry.file] = counts;

    // Raw zone transitions, independent of the semantic rules.
    const state = createGameState();
    const diagnostics = new DiagnosticCollector();
    for (const packet of flattenPackets(game.packets)) {
      if (isContainerPacket(packet)) continue;
      const id = packet.entity?.kind === 'id' ? packet.entity.id : packet.id;
      const before = id === undefined ? undefined : state.entities.get(id)?.tags.get(GameTag.ZONE);
      applyPacket(state, packet, diagnostics);
      const after = id === undefined ? undefined : state.entities.get(id)?.tags.get(GameTag.ZONE);
      if (after === undefined || after === before) continue;
      if (before === Zone.PLAY && after === Zone.GRAVEYARD) {
        const cardType = state.entities.get(id)?.tags.get(GameTag.CARDTYPE);
        const key =
          cardType === undefined ? 'unknown' : (enumName(CardType, cardType) ?? String(cardType));
        stats.playToGraveyardByCardType[key] = (stats.playToGraveyardByCardType[key] ?? 0) + 1;
      }
      if (before === Zone.DECK && after === Zone.HAND) {
        const step = state.step;
        const key = step === undefined ? 'unknown' : (enumName(Step, step) ?? String(step));
        stats.deckToHandByStep[key] = (stats.deckToHandByStep[key] ?? 0) + 1;
      }
    }
  }
}

if (json) {
  console.log(JSON.stringify(stats, null, 2));
} else {
  const summary = { ...stats };
  delete summary.perFile;
  console.log(JSON.stringify(summary, null, 2));
}
