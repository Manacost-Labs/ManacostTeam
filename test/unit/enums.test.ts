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
    expect(enumName(BlockType, 13)).toBeUndefined();
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
