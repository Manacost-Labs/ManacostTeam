import { describe, expect, it } from 'vitest';

import {
  applyPackets,
  createGameState,
  createTimeline,
  GameTag,
  parseReplay,
  ReplayValidationError,
  restoreState,
  snapshotState,
} from '../../src/index.js';
import { DiagnosticCollector } from '../../src/diagnostics.js';
import { PRELUDE, wrapGame } from '../helpers.js';

const XML = wrapGame(`${PRELUDE}
  <FullEntity id="4" cardID="A"><Tag tag="49" value="2"/></FullEntity>
  <Block entity="2" type="7">
    <TagChange entity="4" tag="49" value="3"/>
    <TagChange entity="1" tag="20" value="1"/>
    <Block entity="4" type="5">
      <TagChange entity="4" tag="49" value="1"/>
    </Block>
  </Block>
  <TagChange entity="1" tag="20" value="2"/>
  <TagChange entity="2" tag="23" value="1"/>
  <HideEntity entity="4" zone="2"/>`);

describe('snapshots', () => {
  it('copy state and restore an independent mutable state', () => {
    const replay = parseReplay(XML);
    const snapshot = snapshotState(replay.state, replay.packetCount - 1);
    expect(snapshot.entities.size).toBe(4);
    expect(snapshot.entities.get(4)?.tags.get(GameTag.ZONE)).toBe(2);

    const restored = restoreState(snapshot);
    restored.entities.get(4)!.tags.set(GameTag.ZONE, 7);
    expect(snapshot.entities.get(4)?.tags.get(GameTag.ZONE)).toBe(2);
    expect(replay.state.entities.get(4)?.tags.get(GameTag.ZONE)).toBe(2);
    expect(restored.players.map((player) => player.player?.name)).toEqual([
      'Alice#1234',
      'Bob#5678',
    ]);
    expect(restored.game?.id).toBe(1);
  });
});

describe('ReplayTimeline', () => {
  const replay = parseReplay(XML);

  it('reconstructs the state after any packet', () => {
    const timeline = createTimeline(replay, { checkpointInterval: 3 });
    expect(timeline.packetCount).toBe(replay.packetCount);
    expect(timeline.checkpoints.map((checkpoint) => checkpoint.packetIndex)).toEqual([2, 5, 8, 11]);

    expect(timeline.stateAt(-1).entities.size).toBe(0);
    expect(timeline.stateAt(2).entities.size).toBe(3);
    expect(timeline.stateAt(3).entities.get(4)?.tags.get(GameTag.ZONE)).toBe(2);
    expect(timeline.stateAt(5).entities.get(4)?.tags.get(GameTag.ZONE)).toBe(3);
    expect(timeline.stateAt(6).turn).toBe(1);
    expect(timeline.stateAt(8).entities.get(4)?.tags.get(GameTag.ZONE)).toBe(1);
    expect(timeline.stateAt(9).turn).toBe(2);
    expect(timeline.stateAt(10).currentPlayer?.id).toBe(2);
    expect(timeline.stateAt(11).entities.get(4)?.tags.get(GameTag.ZONE)).toBe(2);
  });

  it('matches the full hierarchical apply for every index regardless of interval', () => {
    for (const interval of [1, 2, 7, 1000]) {
      const timeline = createTimeline(replay.packets, { checkpointInterval: interval });
      for (let index = 0; index < replay.packetCount; index++) {
        const expected = createGameState();
        const prefix = timeline.packets.slice(0, index + 1);
        applyPackets(
          expected,
          prefix.filter((packet) => packet.type !== 'BLOCK' && packet.type !== 'SUB_SPELL'),
          new DiagnosticCollector(),
        );
        const actual = timeline.stateAt(index);
        expect(dump(actual)).toEqual(dump(expected));
      }
    }
  });

  it('rejects bad indexes and options', () => {
    const timeline = createTimeline(replay);
    expect(() => timeline.stateAt(-2)).toThrow(ReplayValidationError);
    expect(() => timeline.stateAt(replay.packetCount)).toThrow(ReplayValidationError);
    expect(() => createTimeline(replay, { checkpointInterval: 0 })).toThrow(ReplayValidationError);
  });
});

function dump(state: ReturnType<typeof createGameState>): unknown {
  return [...state.entities].map((entity) => [entity.id, entity.cardId, [...entity.tags]]);
}
