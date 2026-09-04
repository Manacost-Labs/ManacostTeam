import { describe, expect, it } from 'vitest';

import { collectTagHistory, GameTag, parseReplay } from '../../src/index.js';
import { wrapGame } from '../helpers.js';

describe('collectTagHistory', () => {
  const replay = parseReplay(
    wrapGame(`
    <FullEntity id="4" cardID="A"><Tag tag="49" value="2"/><Tag tag="50" value="1"/></FullEntity>
    <Block entity="4" type="7">
      <TagChange entity="4" tag="49" value="3"/>
      <ShowEntity entity="4" cardID="B"><Tag tag="49" value="1"/></ShowEntity>
    </Block>
    <HideEntity entity="4" zone="2"/>
    <TagChange entity="UNKNOWN HUMAN PLAYER" tag="49" value="9"/>
    <TagChange entity="5" tag="49" value="4"/>`),
  );

  it('records every value in packet order, including definitions and hides', () => {
    const history = collectTagHistory(replay.packets);
    expect(history.get(4)?.get(GameTag.ZONE)).toEqual([
      { packetIndex: 0, value: 2 },
      { packetIndex: 2, value: 3 },
      { packetIndex: 3, value: 1 },
      { packetIndex: 4, value: 2 },
    ]);
    expect(history.get(4)?.get(GameTag.CONTROLLER)).toEqual([{ packetIndex: 0, value: 1 }]);
    expect(history.get(5)?.get(GameTag.ZONE)).toEqual([{ packetIndex: 6, value: 4 }]);
    expect(history.size).toBe(2);
  });

  it('honours entity and tag filters', () => {
    const history = collectTagHistory(replay.packets, {
      entities: new Set([4]),
      tags: new Set([GameTag.CONTROLLER]),
    });
    expect([...history.keys()]).toEqual([4]);
    expect([...history.get(4)!.keys()]).toEqual([GameTag.CONTROLLER]);
  });
});
