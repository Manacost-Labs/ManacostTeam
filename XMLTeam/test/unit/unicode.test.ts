import { describe, expect, it } from 'vitest';

import {
  parseReplay,
  parseReplayStream,
  type PlayerPacket,
  type TagChangePacket,
} from '../../src/index.js';
import { wrapGame } from '../helpers.js';

const NAMES = [
  ['russian', 'Игрок Нгуен#2048'],
  ['polish', 'Zażółć gęślą jaźń#1'],
  ['chinese', '玩家小明#7'],
  ['korean', '플레이어#9'],
  ['japanese', 'プレイヤー太郎#3'],
  ['emoji', 'Dragon \u{1F409}\u{1F0CF}#1'],
  ['combining', 'e\u0301a\u0308 Zoe\u0308#5'],
  ['xml-special', 'Tom & "Jerry" <3 \'q\''],
] as const;

function escape(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

describe('Unicode round trips', () => {
  it.each(NAMES)(
    '%s player name survives parsing and byte-wise streaming',
    async (_label, name) => {
      const xml =
        wrapGame(`<Player id="2" playerID="1" name="${escape(name)}"><Tag tag="50" value="1"/></Player>
      <TagChange entity="1" tag="1" value="1" EntityCardName="${escape(name)}" note="${escape(name)}"/>`);
      const replay = parseReplay(xml);
      const player = replay.packets[0] as PlayerPacket;
      expect(player.name).toBe(name);
      expect(replay.metadata.players[0]?.name).toBe(name);
      expect(replay.entities.get(2)?.player?.name).toBe(name);
      const change = replay.packets[1] as TagChangePacket;
      expect(change.unknownAttributes).toEqual({ EntityCardName: name, note: name });

      const bytes = new TextEncoder().encode(xml);
      const chunks = Array.from(bytes, (byte) => Uint8Array.of(byte));
      const streamed = await parseReplayStream(chunks);
      expect((streamed.games[0]?.packets[0] as PlayerPacket).name).toBe(name);
      expect((streamed.games[0]?.packets[1] as TagChangePacket).unknownAttributes).toEqual({
        EntityCardName: name,
        note: name,
      });
    },
  );

  it('resolves name-based entity references containing non-ASCII text', () => {
    const replay = parseReplay(
      wrapGame(`<Player id="2" playerID="1" name="Игрок#1"><Tag tag="50" value="1"/></Player>
        <TagChange entity="Игрок#1" tag="17" value="4"/>`),
    );
    expect(replay.entities.get(2)?.tags.get(17)).toBe(4);
    expect(replay.diagnostics).toEqual([]);
  });
});
