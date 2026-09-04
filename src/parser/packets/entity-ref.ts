/**
 * A reference to a game entity as written in the replay.
 *
 * In every HSReplay produced by modern exporters this is a numeric entity id.
 * The HSReplay DTD nevertheless allows the literal `UNKNOWN HUMAN PLAYER`, and
 * older exporters wrote player names in place of ids. Those forms are kept as
 * `name` references so that nothing is lost and nothing crashes.
 */
export type EntityRef = EntityIdRef | EntityNameRef;

export interface EntityIdRef {
  readonly kind: 'id';
  readonly id: number;
}

export interface EntityNameRef {
  readonly kind: 'name';
  readonly name: string;
}

const INTEGER = /^-?\d{1,15}$/;

export function parseEntityRef(raw: string): EntityRef {
  const text = raw.trim();
  if (INTEGER.test(text)) {
    return { kind: 'id', id: Number(text) };
  }
  return { kind: 'name', name: raw };
}

export function entityRefFromId(id: number): EntityIdRef {
  return { kind: 'id', id };
}

/** Returns the numeric id of a reference, or `undefined` for name references. */
export function entityId(ref: EntityRef): number | undefined {
  return ref.kind === 'id' ? ref.id : undefined;
}

export function formatEntityRef(ref: EntityRef): string {
  return ref.kind === 'id' ? String(ref.id) : JSON.stringify(ref.name);
}
