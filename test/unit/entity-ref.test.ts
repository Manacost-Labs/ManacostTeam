import { describe, expect, it } from 'vitest';

import { entityId, formatEntityRef, parseEntityRef } from '../../src/parser/packets/entity-ref.js';

describe('parseEntityRef', () => {
  it('parses integers as id references', () => {
    expect(parseEntityRef('42')).toEqual({ kind: 'id', id: 42 });
    expect(parseEntityRef('0')).toEqual({ kind: 'id', id: 0 });
    expect(parseEntityRef('-1')).toEqual({ kind: 'id', id: -1 });
  });

  it('keeps anything else as a name reference', () => {
    expect(parseEntityRef('UNKNOWN HUMAN PLAYER')).toEqual({
      kind: 'name',
      name: 'UNKNOWN HUMAN PLAYER',
    });
    expect(parseEntityRef('Alice#1234')).toEqual({ kind: 'name', name: 'Alice#1234' });
    expect(parseEntityRef('')).toEqual({ kind: 'name', name: '' });
    expect(parseEntityRef('1'.repeat(20))).toEqual({ kind: 'name', name: '1'.repeat(20) });
  });

  it('exposes helpers', () => {
    expect(entityId({ kind: 'id', id: 7 })).toBe(7);
    expect(entityId({ kind: 'name', name: 'x' })).toBeUndefined();
    expect(formatEntityRef({ kind: 'id', id: 7 })).toBe('7');
    expect(formatEntityRef({ kind: 'name', name: 'x' })).toBe('"x"');
  });
});
