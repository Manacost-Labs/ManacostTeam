import { describe, expect, it } from 'vitest';

import {
  BlockType,
  describeTagValue,
  enumName,
  GameTag,
  PlayState,
  Step,
} from '../../src/index.js';

describe('enum tables', () => {
  it('names known values and leaves unknown ones numeric', () => {
    expect(enumName(Step, 15)).toBe('FINAL_GAMEOVER');
    expect(enumName(BlockType, 7)).toBe('PLAY');
    expect(enumName(BlockType, 13)).toBe('DECK_ACTION');
    expect(enumName(BlockType, 99)).toBeUndefined();
    expect(PlayState.CONCEDED).toBe(8);
  });

  it('describes tag values through the tag → enum map', () => {
    expect(describeTagValue(GameTag.PLAYSTATE, 4)).toBe('WON');
    expect(describeTagValue(GameTag.NEXT_STEP, 10)).toBe('MAIN_ACTION');
    expect(describeTagValue(GameTag.MULLIGAN_STATE, 4)).toBe('DONE');
    expect(describeTagValue(GameTag.PLAYSTATE, 99)).toBe('99');
    expect(describeTagValue(GameTag.ATK, 5)).toBe('5');
  });
});

describe('enum values match the HearthSim tables', () => {
  it('CardType uses the real game values, including the Battlegrounds and Location types', async () => {
    const { CardType, Zone, BlockType, MetaDataType } = await import('../../src/index.js');
    expect(CardType.LOCATION).toBe(39);
    expect(CardType.MOVE_MINION_HOVER_TARGET).toBe(22);
    expect(CardType.LETTUCE_ABILITY).toBe(23);
    expect(CardType.BATTLEGROUND_HERO_BUDDY).toBe(24);
    expect(CardType.BATTLEGROUND_QUEST_REWARD).toBe(40);
    expect(CardType.BATTLEGROUND_SPELL).toBe(42);
    expect(CardType.BATTLEGROUND_ANOMALY).toBe(43);
    expect(CardType.BATTLEGROUND_TRINKET).toBe(44);
    expect(Object.values(CardType)).not.toContain(16);
    expect(Zone.LETTUCE_ABILITY).toBe(8);
    expect(BlockType.DECK_ACTION).toBe(13);
    expect(MetaDataType.HOLD_DRAWN_CARD).toBe(17);
    expect(MetaDataType.CONTROLLER_AND_ZONE_CHANGE).toBe(18);
    expect(Step.MAIN_POST_ACTION).toBe(20);
  });
});
