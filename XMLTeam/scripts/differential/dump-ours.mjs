// Normalised dump of a replay as this library sees it. Run after `pnpm build`.
// Usage: node scripts/differential/dump-ours.mjs <replay.xml> > ours.json
import { readFileSync } from 'node:fs';

import { flattenPackets, parseReplayDocument } from '../../dist/index.js';

const [path] = process.argv.slice(2);
if (!path) {
  console.error('usage: dump-ours.mjs <replay.xml>');
  process.exit(2);
}

const document = parseReplayDocument(readFileSync(path, 'utf8'));
const games = document.games.map((game) => {
  const packets = [];
  for (const packet of flattenPackets(game.packets)) packets.push(normalisePacket(packet));
  return {
    id: game.metadata.game.id ?? null,
    players: game.metadata.players.map((player) => ({
      entityId: player.entityId,
      playerId: player.playerId,
      name: player.name ?? null,
    })),
    entities: [...game.entities]
      .map((entity) => ({
        id: entity.id,
        cardId: entity.cardId ?? null,
        tags: Object.fromEntries([...entity.tags].map(([tag, value]) => [String(tag), value])),
      }))
      .sort((a, b) => a.id - b.id),
    packets,
    result: Object.fromEntries(
      game.state.players.map((player) => [String(player.id), player.tags.get(17) ?? null]),
    ),
  };
});
process.stdout.write(JSON.stringify({ games }, null, 1));

function ref(value) {
  return value === undefined ? null : value.kind === 'id' ? value.id : value.name;
}

// One record per packet, in document order, with the fields both sides can produce.
function normalisePacket(packet) {
  switch (packet.type) {
    case 'GAME_ENTITY':
      return { type: 'CreateGame', entity: packet.id };
    case 'PLAYER':
      return { type: 'Player', entity: packet.id, playerId: packet.playerId };
    case 'FULL_ENTITY':
      return {
        type: 'FullEntity',
        entity: packet.id,
        cardId: packet.cardId ?? null,
        tags: packet.tags.length,
      };
    case 'SHOW_ENTITY':
      return {
        type: 'ShowEntity',
        entity: ref(packet.entity),
        cardId: packet.cardId ?? null,
        tags: packet.tags.length,
      };
    case 'CHANGE_ENTITY':
      return {
        type: 'ChangeEntity',
        entity: ref(packet.entity),
        cardId: packet.cardId ?? null,
        tags: packet.tags.length,
      };
    case 'HIDE_ENTITY':
      return { type: 'HideEntity', entity: ref(packet.entity), zone: packet.zone };
    case 'TAG_CHANGE':
      return {
        type: 'TagChange',
        entity: ref(packet.entity),
        tag: packet.tag,
        value: packet.value,
      };
    case 'BLOCK':
      return {
        type: 'Block',
        entity: ref(packet.entity),
        blockType: packet.blockType,
        target: packet.target ? ref(packet.target) : 0,
        children: packet.children.length,
      };
    case 'SUB_SPELL':
      return { type: 'SubSpell', entity: ref(packet.source), children: packet.children.length };
    case 'META_DATA':
      return { type: 'MetaData', meta: packet.meta, data: packet.data, info: packet.info.length };
    case 'CHOICES':
      return {
        type: 'Choices',
        id: packet.id,
        entity: ref(packet.entity),
        choiceType: packet.choiceType,
        choices: packet.choices.length,
      };
    case 'CHOSEN_ENTITIES':
      return {
        type: 'ChosenEntities',
        id: packet.id,
        entity: ref(packet.entity),
        choices: packet.choices.length,
      };
    case 'SEND_CHOICES':
      return {
        type: 'SendChoices',
        id: packet.id,
        choiceType: packet.choiceType,
        choices: packet.choices.length,
      };
    case 'OPTIONS':
      return { type: 'Options', id: packet.id, options: packet.options.length };
    case 'SEND_OPTION':
      return {
        type: 'SendOption',
        option: packet.option,
        target: packet.target ? ref(packet.target) : 0,
      };
    case 'SHUFFLE_DECK':
      return { type: 'ShuffleDeck', playerId: packet.playerId };
    default:
      return { type: packet.type };
  }
}
