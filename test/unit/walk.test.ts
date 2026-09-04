import { describe, expect, it } from 'vitest';

import { flattenPackets, parseReplay, walkPackets } from '../../src/index.js';
import { wrapGame } from '../helpers.js';

describe('walkPackets', () => {
  it('visits packets depth-first in index order with depth and parent', () => {
    const replay = parseReplay(
      wrapGame(`
      <TagChange entity="1" tag="1" value="1"/>
      <Block entity="1" type="5">
        <TagChange entity="1" tag="1" value="2"/>
        <SubSpell source="1"><TagChange entity="1" tag="1" value="3"/></SubSpell>
      </Block>
      <TagChange entity="1" tag="1" value="4"/>`),
    );
    const visits = [...walkPackets(replay.packets)].map((visit) => [
      visit.packet.index,
      visit.depth,
      visit.parent?.index,
    ]);
    expect(visits).toEqual([
      [0, 0, undefined],
      [1, 0, undefined],
      [2, 1, 1],
      [3, 1, 1],
      [4, 2, 3],
      [5, 0, undefined],
    ]);
    expect(flattenPackets(replay.packets).map((packet) => packet.index)).toEqual([
      0, 1, 2, 3, 4, 5,
    ]);
    expect(replay.packetCount).toBe(6);
  });
});
