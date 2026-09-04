import { ReplayValidationError } from '../errors.js';
import { type Entity } from './entity.js';

/** Mutable, Map-backed collection of entities keyed by entity id. */
export class EntityStore {
  private readonly entities = new Map<number, Entity>();

  get size(): number {
    return this.entities.size;
  }

  get(id: number): Entity | undefined {
    return this.entities.get(id);
  }

  has(id: number): boolean {
    return this.entities.has(id);
  }

  create(entity: Entity): Entity {
    if (this.entities.has(entity.id)) {
      throw new ReplayValidationError(
        'DUPLICATE_ENTITY',
        `entity ${String(entity.id)} already exists`,
      );
    }
    this.entities.set(entity.id, entity);
    return entity;
  }

  /** Replaces an existing entity or inserts a new one. */
  set(entity: Entity): Entity {
    this.entities.set(entity.id, entity);
    return entity;
  }

  update(id: number, patch: Partial<Omit<Entity, 'id' | 'tags'>>): Entity {
    const entity = this.entities.get(id);
    if (!entity) {
      throw new ReplayValidationError('MISSING_ENTITY', `entity ${String(id)} does not exist`);
    }
    if (patch.cardId !== undefined) entity.cardId = patch.cardId;
    if (patch.player !== undefined) entity.player = patch.player;
    return entity;
  }

  values(): IterableIterator<Entity> {
    return this.entities.values();
  }

  [Symbol.iterator](): IterableIterator<Entity> {
    return this.entities.values();
  }
}
