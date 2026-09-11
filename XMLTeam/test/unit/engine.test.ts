import { describe, expect, it } from 'vitest';

import {
  DiagnosticCode,
  GameTag,
  parseReplay,
  ReplayValidationError,
  Zone,
} from '../../src/index.js';
import { PRELUDE, wrapGame } from '../helpers.js';

describe('state engine', () => {
  it('creates game and player entities with metadata', () => {
    const replay = parseReplay(wrapGame(PRELUDE));
    expect(replay.entities.size).toBe(3);
    expect(replay.state.game?.id).toBe(1);
    expect(replay.state.players.map((player) => player.id)).toEqual([2, 3]);
    expect(replay.entities.get(2)?.player).toEqual({
      playerId: 1,
      name: 'Alice#1234',
      accountHi: '144115193835963207',
      accountLo: '124857041',
    });
    expect(replay.entities.get(3)?.player?.deck?.cards).toHaveLength(2);
    expect(replay.entities.get(3)?.tags.get(GameTag.CONTROLLER)).toBe(2);
    expect(replay.metadata.players).toEqual([
      {
        entityId: 2,
        playerId: 1,
        name: 'Alice#1234',
        accountHi: '144115193835963207',
        accountLo: '124857041',
      },
      expect.objectContaining({ entityId: 3, playerId: 2, name: 'Bob#5678' }),
    ]);
  });

  it('applies FullEntity, TagChange, ShowEntity, HideEntity and ChangeEntity in order', () => {
    const replay = parseReplay(
      wrapGame(`${PRELUDE}
      <FullEntity id="4"><Tag tag="49" value="2"/><Tag tag="50" value="1"/></FullEntity>
      <Block entity="2" type="7">
        <TagChange entity="4" tag="49" value="3"/>
        <ShowEntity entity="4" cardID="CS2_029"><Tag tag="202" value="4"/><Tag tag="49" value="1"/></ShowEntity>
        <Block entity="4" type="5">
          <TagChange entity="4" tag="263" value="2"/>
        </Block>
      </Block>
      <HideEntity entity="4" zone="2"/>
      <ChangeEntity entity="4" cardID="CS2_030"><Tag tag="47" value="5"/></ChangeEntity>`),
    );
    const entity = replay.entities.get(4)!;
    expect(entity.cardId).toBe('CS2_030');
    expect(entity.tags.get(GameTag.ZONE)).toBe(Zone.DECK);
    expect(entity.tags.get(GameTag.CARDTYPE)).toBe(4);
    expect(entity.tags.get(GameTag.ZONE_POSITION)).toBe(2);
    expect(entity.tags.get(GameTag.ATK)).toBe(5);
    expect(entity.tags.get(GameTag.CONTROLLER)).toBe(1);
    expect(replay.diagnostics).toEqual([]);
  });

  it('replaces tags when an entity is defined twice and reports it', () => {
    const replay = parseReplay(
      wrapGame(`
      <FullEntity id="4" cardID="A"><Tag tag="49" value="2"/><Tag tag="50" value="1"/></FullEntity>
      <FullEntity id="4"><Tag tag="49" value="3"/></FullEntity>`),
    );
    const entity = replay.entities.get(4)!;
    expect(entity.cardId).toBeUndefined();
    expect([...entity.tags]).toEqual([[49, 3]]);
    expect(replay.diagnostics).toContainEqual(
      expect.objectContaining({ code: DiagnosticCode.ENTITY_RECREATED, packetIndex: 1 }),
    );
  });

  it('creates a placeholder for unknown entities and fails in strict mode', () => {
    const body = '<TagChange entity="77" tag="49" value="1"/>';
    const replay = parseReplay(wrapGame(body));
    expect(replay.entities.get(77)?.tags.get(49)).toBe(1);
    expect(replay.diagnostics).toContainEqual(
      expect.objectContaining({
        level: 'warning',
        code: DiagnosticCode.UNKNOWN_ENTITY,
        packetIndex: 0,
      }),
    );
    expect(() => parseReplay(wrapGame(body), { strict: true })).toThrow(ReplayValidationError);
  });

  it('ignores name references with a diagnostic', () => {
    const replay = parseReplay(
      wrapGame('<TagChange entity="UNKNOWN HUMAN PLAYER" tag="49" value="1"/>'),
    );
    expect(replay.entities.size).toBe(0);
    expect(replay.diagnostics).toContainEqual(
      expect.objectContaining({ code: DiagnosticCode.UNRESOLVED_ENTITY_REF }),
    );
  });

  it('reports duplicate tags inside one definition, last value wins', () => {
    const replay = parseReplay(
      wrapGame(
        '<FullEntity id="4"><Tag tag="49" value="2"/><Tag tag="49" value="3"/></FullEntity>',
      ),
    );
    expect(replay.entities.get(4)?.tags.get(49)).toBe(3);
    expect(replay.diagnostics).toContainEqual(
      expect.objectContaining({ level: 'info', code: DiagnosticCode.DUPLICATE_TAG }),
    );
  });
});
