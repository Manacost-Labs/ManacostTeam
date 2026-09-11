import { describe, expect, it } from 'vitest';

import {
  type BlockPacket,
  DiagnosticCode,
  type OptionsPacket,
  parseReplay,
} from '../../src/index.js';
import { wrapGame } from '../helpers.js';

describe('real-world format deviations', () => {
  it('accepts <Target> entries without an entity (hsreplay-test-data bounce replay)', () => {
    const replay = parseReplay(
      wrapGame(`<Options id="3">
        <Option index="1" entity="56" type="3">
          <Target index="0" entity="64"/>
          <Target error="33" index="5"/>
        </Option>
      </Options>`),
    );
    expect(replay.diagnostics.filter((d) => d.code === DiagnosticCode.MALFORMED_PACKET)).toEqual(
      [],
    );
    const options = replay.packets[0] as OptionsPacket;
    expect(options.type).toBe('OPTIONS');
    expect(options.options[0]?.targets).toEqual([
      { index: 0, entity: { kind: 'id', id: 64 } },
      { index: 5, error: '33' },
    ]);
  });

  it('parses legacy HSReplay 1.0 <Action> elements as BLOCK packets', () => {
    const replay = parseReplay(
      wrapGame(`<Action entity="2" target="0" ts="2016-02-19T16:59:08.248440" type="5">
        <TagChange entity="1" tag="20" value="1"/>
      </Action>`),
    );
    const block = replay.packets[0] as BlockPacket;
    expect(block.type).toBe('BLOCK');
    expect(block.blockType).toBe(5);
    expect(block.entity).toEqual({ kind: 'id', id: 2 });
    expect(block.children.map((child) => child.type)).toEqual(['TAG_CHANGE']);
    expect(replay.diagnostics.map((d) => d.code)).toEqual([
      DiagnosticCode.LEGACY_ELEMENT,
      DiagnosticCode.UNKNOWN_ENTITY,
    ]);
  });

  it('reports each unknown attribute once per element kind, keeping every value', () => {
    const replay = parseReplay(
      wrapGame(`<TagChange entity="1" tag="1" value="1" GameTagName="A"/>
        <TagChange entity="1" tag="2" value="1" GameTagName="B"/>
        <FullEntity id="9" EntityName="X"/>`),
    );
    const unknown = replay.diagnostics.filter((d) => d.code === DiagnosticCode.UNKNOWN_ATTRIBUTE);
    expect(unknown.map((d) => [d.packetIndex, d.message])).toEqual([
      [0, 'unknown attribute(s) on <TagChange>: GameTagName'],
      [2, 'unknown attribute(s) on <FullEntity>: EntityName'],
    ]);
    expect(replay.packets.map((p) => p.unknownAttributes)).toEqual([
      { GameTagName: 'A' },
      { GameTagName: 'B' },
      { EntityName: 'X' },
    ]);
  });
});

describe('elements written by python-hsreplay (Power.log conversions)', () => {
  it('parses CachedTagForDormantChange, ResetGame and VOSpell as typed packets', () => {
    const replay = parseReplay(
      wrapGame(`<CachedTagForDormantChange entity="22" tag="47" value="2"/>
        <ResetGame ts="2026-09-04T10:00:00"/>
        <VOSpell brass_ring_guid="BR_1" vo_spell_prefab_guid="VO_1:abcd" blocking="True" additional_delay_ms="250"/>`),
    );
    expect(replay.packets.map((packet) => packet.type)).toEqual([
      'CACHED_TAG_FOR_DORMANT_CHANGE',
      'RESET_GAME',
      'VO_SPELL',
    ]);
    expect(replay.packets[0]).toEqual({
      index: 0,
      type: 'CACHED_TAG_FOR_DORMANT_CHANGE',
      entity: { kind: 'id', id: 22 },
      tag: 47,
      value: 2,
    });
    expect(replay.packets[1]).toEqual({ index: 1, type: 'RESET_GAME', ts: '2026-09-04T10:00:00' });
    expect(replay.packets[2]).toEqual({
      index: 2,
      type: 'VO_SPELL',
      brassRingGuid: 'BR_1',
      voSpellPrefabGuid: 'VO_1:abcd',
      blocking: true,
      additionalDelayMs: 250,
    });
    expect(replay.diagnostics.filter((d) => d.code === DiagnosticCode.UNKNOWN_NODE)).toEqual([]);
  });

  it('does not let a cached dormant tag touch the entity state', () => {
    const replay = parseReplay(
      wrapGame(`<FullEntity id="22"><Tag tag="47" value="1"/></FullEntity>
        <CachedTagForDormantChange entity="22" tag="47" value="2"/>`),
    );
    expect(replay.entities.get(22)?.tags.get(47)).toBe(1);
  });
});
