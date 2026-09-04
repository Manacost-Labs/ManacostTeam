import { describe, expect, it } from 'vitest';

import { ReplayValidationError } from '../../src/errors.js';
import { createEntity, getController, getZone, getZonePosition } from '../../src/state/entity.js';
import { EntityStore } from '../../src/state/entity-store.js';

describe('EntityStore', () => {
  it('creates, looks up and iterates entities', () => {
    const store = new EntityStore();
    expect(store.has(1)).toBe(false);
    const entity = store.create(createEntity(1, 'CS2_029', [{ tag: 49, value: 1 }]));
    expect(store.get(1)).toBe(entity);
    expect(store.has(1)).toBe(true);
    expect(store.size).toBe(1);
    expect([...store.values()]).toEqual([entity]);
    expect([...store]).toEqual([entity]);
  });

  it('rejects duplicate creation and updates of missing entities', () => {
    const store = new EntityStore();
    store.create(createEntity(1));
    expect(() => store.create(createEntity(1))).toThrow(ReplayValidationError);
    expect(() => store.update(2, { cardId: 'x' })).toThrow(ReplayValidationError);
  });

  it('updates card id and player info in place', () => {
    const store = new EntityStore();
    store.create(createEntity(2));
    const updated = store.update(2, { cardId: 'HERO_01', player: { playerId: 1, name: 'Alice' } });
    expect(updated.cardId).toBe('HERO_01');
    expect(updated.player?.name).toBe('Alice');
    expect(store.get(2)).toBe(updated);
  });

  it('derives zone, controller and position from tags', () => {
    const entity = createEntity(5, undefined, [
      { tag: 49, value: 3 },
      { tag: 50, value: 2 },
      { tag: 263, value: 4 },
    ]);
    expect(getZone(entity)).toBe(3);
    expect(getController(entity)).toBe(2);
    expect(getZonePosition(entity)).toBe(4);
    expect(getZone(createEntity(6))).toBeUndefined();
  });
});
