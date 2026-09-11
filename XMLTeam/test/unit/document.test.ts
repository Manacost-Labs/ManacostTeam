import { describe, expect, it } from 'vitest';

import {
  DiagnosticCode,
  GameTag,
  parseReplay,
  parseReplayDocument,
  ReplayValidationError,
} from '../../src/index.js';
import { PRELUDE, wrapGame } from '../helpers.js';

const TWO_GAMES = `<HSReplay build="1" version="1.7">
  <Game id="1"><TagChange entity="1" tag="20" value="1"/></Game>
  <Game id="2"><TagChange entity="1" tag="20" value="5"/><Mystery/></Game>
</HSReplay>`;

describe('parseReplayDocument', () => {
  it('parses every game with its own packets, state and diagnostics', () => {
    const document = parseReplayDocument(TWO_GAMES);
    expect(document.version).toBe('1.7');
    expect(document.build).toBe(1);
    expect(document.diagnostics).toEqual([]);
    expect(document.games.map((game) => game.metadata.game.id)).toEqual([1, 2]);
    expect(document.games[0]?.entities.get(1)?.tags.get(GameTag.TURN)).toBe(1);
    expect(document.games[1]?.entities.get(1)?.tags.get(GameTag.TURN)).toBe(5);
    expect(document.games[0]?.diagnostics.map((d) => d.code)).toEqual([
      DiagnosticCode.UNKNOWN_ENTITY,
    ]);
    // Packetizing reports before the state engine runs, so UNKNOWN_NODE comes first.
    expect(document.games[1]?.diagnostics.map((d) => d.code)).toEqual([
      DiagnosticCode.UNKNOWN_NODE,
      DiagnosticCode.UNKNOWN_ENTITY,
    ]);
    expect(() => parseReplayDocument(TWO_GAMES, { strict: true })).toThrow(ReplayValidationError);
  });

  it('returns an empty game list for a replay without games', () => {
    expect(parseReplayDocument('<HSReplay version="1.7"/>').games).toEqual([]);
    expect(() => parseReplay('<HSReplay version="1.7"/>')).toThrow(/NO_GAME/);
  });

  it('parseReplay merges document diagnostics and flags extra games', () => {
    const replay = parseReplay(TWO_GAMES);
    expect(replay.metadata.game.id).toBe(1);
    expect(replay.diagnostics.map((d) => d.code)).toEqual([
      DiagnosticCode.MULTIPLE_GAMES,
      DiagnosticCode.UNKNOWN_ENTITY,
    ]);
  });
});

describe('name-based entity references', () => {
  it('resolve to the player with that name', () => {
    const replay = parseReplay(
      wrapGame(`${PRELUDE}<TagChange entity="Bob#5678" tag="17" value="4"/>`),
    );
    expect(replay.entities.get(3)?.tags.get(GameTag.PLAYSTATE)).toBe(4);
    expect(replay.diagnostics).toEqual([]);
  });

  it('are reported when no player matches', () => {
    const replay = parseReplay(
      wrapGame(`${PRELUDE}<TagChange entity="UNKNOWN HUMAN PLAYER" tag="17" value="4"/>`),
    );
    expect(replay.diagnostics.map((d) => d.code)).toEqual([DiagnosticCode.UNRESOLVED_ENTITY_REF]);
  });
});
