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
