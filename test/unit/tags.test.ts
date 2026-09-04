import { describe, expect, it } from 'vitest';

import { createTagRegistry, defaultTagRegistry, GameTag } from '../../src/index.js';

describe('tag registry', () => {
  it('maps ids to names and back', () => {
    expect(defaultTagRegistry.name(GameTag.ZONE)).toBe('ZONE');
    expect(defaultTagRegistry.id('CONTROLLER')).toBe(50);
    expect(defaultTagRegistry.describe(49)).toBe('ZONE');
    expect(defaultTagRegistry.describe(99999)).toBe('TAG_99999');
    expect(defaultTagRegistry.name(99999)).toBeUndefined();
  });

  it('can be extended without touching the defaults', () => {
    const registry = createTagRegistry({ MY_TAG: 4242 });
    expect(registry.name(4242)).toBe('MY_TAG');
    expect(registry.name(GameTag.ZONE)).toBe('ZONE');
    expect(defaultTagRegistry.name(4242)).toBeUndefined();
  });
});
