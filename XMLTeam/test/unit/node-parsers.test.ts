import { describe, expect, it } from 'vitest';

import {
  type BlockPacket,
  type ChangeEntityPacket,
  type ChoicesPacket,
  type ChosenEntitiesPacket,
  DiagnosticCode,
  type FullEntityPacket,
  type GameEntityPacket,
  type HideEntityPacket,
  type MetaDataPacket,
  type OptionsPacket,
  parseReplay,
  type PlayerPacket,
  type ReplayPacket,
  ReplayValidationError,
  type SendChoicesPacket,
  type SendOptionPacket,
  type ShowEntityPacket,
  type ShuffleDeckPacket,
  type SubSpellPacket,
  type TagChangePacket,
  type UnknownPacket,
} from '../../src/index.js';
import { PRELUDE, wrapGame } from '../helpers.js';

function packetsOf(body: string, strict = false) {
  const replay = parseReplay(wrapGame(body), { strict });
  return { replay, packets: replay.packets };
}

function single<T extends ReplayPacket>(body: string): T {
  const { packets } = packetsOf(body);
  expect(packets).toHaveLength(1);
  return packets[0] as T;
}

describe('node parsers', () => {
  it('GameEntity', () => {
    const packet = single<GameEntityPacket>(
      '<GameEntity id="1"><Tag tag="202" value="1"/><Tag tag="49" value="1"/></GameEntity>',
    );
    expect(packet).toEqual({
      index: 0,
      type: 'GAME_ENTITY',
      id: 1,
      tags: [
        { tag: 202, value: 1 },
        { tag: 49, value: 1 },
      ],
    });
  });

  it('Player with deck and big account ids kept as strings', () => {
    const { packets } = packetsOf(PRELUDE);
    const [, alice, bob] = packets as [GameEntityPacket, PlayerPacket, PlayerPacket];
    expect(alice.type).toBe('PLAYER');
    expect(alice.id).toBe(2);
    expect(alice.playerId).toBe(1);
    expect(alice.name).toBe('Alice#1234');
    expect(alice.accountHi).toBe('144115193835963207');
    expect(alice.accountLo).toBe('124857041');
    expect(alice.deck).toBeUndefined();
    expect(alice.tags).toEqual([
      { tag: 50, value: 1 },
      { tag: 202, value: 2 },
    ]);
    expect(bob.deck).toEqual({
      cards: [
        { id: 'CS2_029', count: 1, premium: 0 },
        { id: 'CS2_029', count: 2, premium: 1 },
      ],
    });
    expect(bob.tags).toHaveLength(2);
  });

  it('FullEntity with and without cardID', () => {
    const { packets } = packetsOf(
      '<FullEntity id="4"><Tag tag="49" value="2"/></FullEntity><FullEntity id="5" cardID="CS2_029"/>',
    );
    const [hidden, known] = packets as [FullEntityPacket, FullEntityPacket];
    expect(hidden).toEqual({ index: 0, type: 'FULL_ENTITY', id: 4, tags: [{ tag: 49, value: 2 }] });
    expect(known).toEqual({ index: 1, type: 'FULL_ENTITY', id: 5, cardId: 'CS2_029', tags: [] });
  });

  it('ShowEntity, ChangeEntity, HideEntity', () => {
    const { packets } = packetsOf(`
      <ShowEntity entity="68" cardID="FIR_959"><Tag tag="50" value="2"/></ShowEntity>
      <ChangeEntity entity="68" cardID="CS2_029"><Tag tag="202" value="4"/></ChangeEntity>
      <HideEntity entity="68" zone="2" ts="2026-09-04T02:42:33.962567-04:00"/>`);
    const [show, change, hide] = packets as [
      ShowEntityPacket,
      ChangeEntityPacket,
      HideEntityPacket,
    ];
    expect(show).toEqual({
      index: 0,
      type: 'SHOW_ENTITY',
      entity: { kind: 'id', id: 68 },
      cardId: 'FIR_959',
      tags: [{ tag: 50, value: 2 }],
    });
    expect(change).toEqual({
      index: 1,
      type: 'CHANGE_ENTITY',
      entity: { kind: 'id', id: 68 },
      cardId: 'CS2_029',
      tags: [{ tag: 202, value: 4 }],
    });
    expect(hide).toEqual({
      index: 2,
      type: 'HIDE_ENTITY',
      entity: { kind: 'id', id: 68 },
      zone: 2,
      ts: '2026-09-04T02:42:33.962567-04:00',
    });
  });

  it('TagChange with hasChangeDef', () => {
    const { packets } = packetsOf(
      '<TagChange entity="3" tag="17" value="8"/><TagChange entity="209" tag="515" value="111355" hasChangeDef="true"/>',
    );
    const [plain, withDef] = packets as [TagChangePacket, TagChangePacket];
    expect(plain).toEqual({
      index: 0,
      type: 'TAG_CHANGE',
      entity: { kind: 'id', id: 3 },
      tag: 17,
      value: 8,
    });
    expect(withDef.hasChangeDef).toBe(true);
    expect(withDef.value).toBe(111355);
  });

  it('Block keeps every attribute and nests packets', () => {
    const packet = single<BlockPacket>(`
      <Block entity="70" type="5" effectCardId="System.Collections.Generic.List\`1[System.String]" effectIndex="0" triggerKeyword="32" target="12" subOption="0" index="3" ts="2026-09-04T02:43:02.811198-04:00">
        <TagChange entity="70" tag="1" value="1"/>
        <Block entity="71" type="3">
          <FullEntity id="99"/>
        </Block>
        <TagChange entity="70" tag="1" value="0"/>
      </Block>`);
    expect(packet.type).toBe('BLOCK');
    expect(packet.index).toBe(0);
    expect(packet.entity).toEqual({ kind: 'id', id: 70 });
    expect(packet.blockType).toBe(5);
    expect(packet.effectCardId).toBe('System.Collections.Generic.List`1[System.String]');
    expect(packet.effectIndex).toBe(0);
    expect(packet.triggerKeyword).toBe(32);
    expect(packet.target).toEqual({ kind: 'id', id: 12 });
    expect(packet.subOption).toBe(0);
    expect(packet.actionIndex).toBe(3);
    expect(packet.ts).toBe('2026-09-04T02:43:02.811198-04:00');
    expect(packet.children.map((child) => [child.index, child.type])).toEqual([
      [1, 'TAG_CHANGE'],
      [2, 'BLOCK'],
      [4, 'TAG_CHANGE'],
    ]);
    const inner = packet.children[1] as BlockPacket;
    expect(inner.children).toEqual([{ index: 3, type: 'FULL_ENTITY', id: 99, tags: [] }]);
    expect(inner.effectCardId).toBeUndefined();
  });

  it('empty self-closing Block', () => {
    const packet = single<BlockPacket>('<Block entity="1" type="5"/>');
    expect(packet.children).toEqual([]);
  });

  it('SubSpell separates targets from nested packets', () => {
    const packet = single<SubSpellPacket>(`
      <SubSpell spellPrefabGuid="ReuseFX_Holy:841d04a6" source="72" targetCount="1" ts="2026-09-04T02:42:54.613119-04:00">
        <SubSpellTarget index="0" entity="52"/>
        <MetaData meta="0" data="0" infoCount="1"><Info index="0" entity="52"/></MetaData>
        <TagChange entity="52" tag="425" value="2"/>
        <Block entity="219" type="5"><TagChange entity="219" tag="1" value="1"/></Block>
      </SubSpell>`);
    expect(packet.type).toBe('SUB_SPELL');
    expect(packet.spellPrefabGuid).toBe('ReuseFX_Holy:841d04a6');
    expect(packet.source).toEqual({ kind: 'id', id: 72 });
    expect(packet.targetCount).toBe(1);
    expect(packet.targets).toEqual([{ index: 0, entity: { kind: 'id', id: 52 } }]);
    expect(packet.children.map((child) => [child.index, child.type])).toEqual([
      [1, 'META_DATA'],
      [2, 'TAG_CHANGE'],
      [3, 'BLOCK'],
    ]);
  });

  it('MetaData with Info, accepting both infoCount and info', () => {
    const { packets } = packetsOf(`
      <MetaData meta="20" data="3000" infoCount="1"><Info index="0" entity="31"/></MetaData>
      <MetaData meta="1" info="2"><Info entity="1"/><Info entity="2"/></MetaData>`);
    const [first, second] = packets as [MetaDataPacket, MetaDataPacket];
    expect(first).toEqual({
      index: 0,
      type: 'META_DATA',
      meta: 20,
      data: 3000,
      infoCount: 1,
      info: [{ index: 0, entity: { kind: 'id', id: 31 } }],
    });
    expect(second.data).toBe(0);
    expect(second.infoCount).toBe(2);
    expect(second.info).toEqual([
      { entity: { kind: 'id', id: 1 } },
      { entity: { kind: 'id', id: 2 } },
    ]);
  });

  it('Choices, ChosenEntities, SendChoices', () => {
    const { packets } = packetsOf(`
      <Choices entity="2" id="1" taskList="5" type="1" min="0" max="3" source="1" ts="t1">
        <Choice index="0" entity="31"/><Choice index="1" entity="7"/>
      </Choices>
      <ChosenEntities entity="2" id="1" ts="t2"><Choice index="0" entity="31"/></ChosenEntities>
      <SendChoices id="2" type="1" ts="t3"/>`);
    const [choices, chosen, sent] = packets as [
      ChoicesPacket,
      ChosenEntitiesPacket,
      SendChoicesPacket,
    ];
    expect(choices).toEqual({
      index: 0,
      type: 'CHOICES',
      id: 1,
      entity: { kind: 'id', id: 2 },
      taskList: 5,
      choiceType: 1,
      min: 0,
      max: 3,
      source: { kind: 'id', id: 1 },
      choices: [
        { index: 0, entity: { kind: 'id', id: 31 } },
        { index: 1, entity: { kind: 'id', id: 7 } },
      ],
      ts: 't1',
    });
    expect(chosen).toEqual({
      index: 1,
      type: 'CHOSEN_ENTITIES',
      id: 1,
      entity: { kind: 'id', id: 2 },
      choices: [{ index: 0, entity: { kind: 'id', id: 31 } }],
      ts: 't2',
    });
    expect(sent).toEqual({
      index: 2,
      type: 'SEND_CHOICES',
      id: 2,
      choiceType: 1,
      choices: [],
      ts: 't3',
    });
  });

  it('Options with SubOption and Target', () => {
    const packet = single<OptionsPacket>(`
      <Options id="3" ts="t">
        <Option index="0" error="INVALID" type="2"/>
        <Option index="1" entity="56" type="3">
          <Target index="0" entity="64"/>
          <Target index="1" entity="72" error="REQ_ENEMY_TARGET" errorParam="5"/>
        </Option>
        <Option index="2" entity="57" type="3" error="REQ_ENOUGH_MANA">
          <SubOption index="0" entity="58"><Target index="0" entity="64"/></SubOption>
          <SubOption index="1" entity="59"/>
        </Option>
      </Options>`);
    expect(packet.type).toBe('OPTIONS');
    expect(packet.id).toBe(3);
    expect(packet.options).toEqual([
      { index: 0, optionType: 2, error: 'INVALID', subOptions: [], targets: [] },
      {
        index: 1,
        optionType: 3,
        entity: { kind: 'id', id: 56 },
        subOptions: [],
        targets: [
          { index: 0, entity: { kind: 'id', id: 64 } },
          { index: 1, entity: { kind: 'id', id: 72 }, error: 'REQ_ENEMY_TARGET', errorParam: 5 },
        ],
      },
      {
        index: 2,
        optionType: 3,
        entity: { kind: 'id', id: 57 },
        error: 'REQ_ENOUGH_MANA',
        subOptions: [
          {
            index: 0,
            entity: { kind: 'id', id: 58 },
            targets: [{ index: 0, entity: { kind: 'id', id: 64 } }],
          },
          { index: 1, entity: { kind: 'id', id: 59 }, targets: [] },
        ],
        targets: [],
      },
    ]);
  });

  it('SendOption and ShuffleDeck', () => {
    const { packets } = packetsOf(`
      <SendOption option="3" subOption="-1" target="72" position="0" ts="t"/>
      <SendOption option="1"/>
      <ShuffleDeck player_id="2"/>`);
    const [full, minimal, shuffle] = packets as [
      SendOptionPacket,
      SendOptionPacket,
      ShuffleDeckPacket,
    ];
    expect(full).toEqual({
      index: 0,
      type: 'SEND_OPTION',
      option: 3,
      subOption: -1,
      target: { kind: 'id', id: 72 },
      position: 0,
      ts: 't',
    });
    expect(minimal).toEqual({ index: 1, type: 'SEND_OPTION', option: 1 });
    expect(shuffle).toEqual({ index: 2, type: 'SHUFFLE_DECK', playerId: 2 });
  });

  it('keeps name entity references', () => {
    const packet = single<TagChangePacket>(
      '<TagChange entity="UNKNOWN HUMAN PLAYER" tag="17" value="1"/>',
    );
    expect(packet.entity).toEqual({ kind: 'name', name: 'UNKNOWN HUMAN PLAYER' });
  });

  it('preserves unknown attributes and reports them', () => {
    const { replay, packets } = packetsOf(
      '<TagChange entity="1" tag="17" value="1" mystery="42"/>',
    );
    const packet = packets[0] as TagChangePacket;
    expect(packet.unknownAttributes).toEqual({ mystery: '42' });
    expect(replay.diagnostics).toContainEqual(
      expect.objectContaining({
        level: 'info',
        code: DiagnosticCode.UNKNOWN_ATTRIBUTE,
        packetIndex: 0,
      }),
    );
  });

  it('preserves unexpected children of payload elements', () => {
    const { replay, packets } = packetsOf(
      '<FullEntity id="4"><Tag tag="49" value="2"/><Weird a="b"/></FullEntity>',
    );
    const packet = packets[0] as FullEntityPacket;
    expect(packet.tags).toEqual([{ tag: 49, value: 2 }]);
    expect(packet.unknownChildren?.map((child) => child.name)).toEqual(['Weird']);
    expect(replay.diagnostics).toContainEqual(
      expect.objectContaining({
        level: 'warning',
        code: DiagnosticCode.UNEXPECTED_CHILD,
        packetIndex: 0,
      }),
    );
    expect(() => packetsOf('<FullEntity id="4"><Weird/></FullEntity>', true)).toThrow(
      ReplayValidationError,
    );
  });

  it('turns unknown elements into UnknownPacket and fails in strict mode', () => {
    const { replay, packets } = packetsOf(
      '<TagChange entity="1" tag="1" value="1"/><Mystery a="1" ts="t"><Inner/></Mystery><TagChange entity="1" tag="1" value="0"/>',
    );
    expect(packets.map((packet) => packet.type)).toEqual(['TAG_CHANGE', 'UNKNOWN', 'TAG_CHANGE']);
    const unknown = packets[1] as UnknownPacket;
    expect(unknown).toMatchObject({
      index: 1,
      name: 'Mystery',
      attributes: { a: '1', ts: 't' },
      ts: 't',
    });
    expect(unknown.children.map((child) => child.name)).toEqual(['Inner']);
    expect(replay.diagnostics).toContainEqual(
      expect.objectContaining({
        level: 'warning',
        code: DiagnosticCode.UNKNOWN_NODE,
        packetIndex: 1,
      }),
    );
    expect(() => packetsOf('<Mystery/>', true)).toThrow(ReplayValidationError);
  });

  it('turns malformed known elements into UnknownPacket with an error diagnostic', () => {
    const { replay, packets } = packetsOf(
      '<TagChange entity="1" tag="abc" value="1"/><TagChange entity="1" value="1"/>',
    );
    expect(packets.map((packet) => packet.type)).toEqual(['UNKNOWN', 'UNKNOWN']);
    expect(
      replay.diagnostics.filter((d) => d.code === DiagnosticCode.MALFORMED_PACKET),
    ).toHaveLength(2);
    expect(replay.diagnostics[0]!.level).toBe('error');
    expect(() => packetsOf('<TagChange entity="1" value="1"/>', true)).toThrow(
      ReplayValidationError,
    );
  });

  it('skips a malformed payload item without dropping the packet', () => {
    const { replay, packets } = packetsOf(
      '<FullEntity id="4"><Tag tag="49" value="2"/><Tag tag="x" value="1"/></FullEntity>',
    );
    const packet = packets[0] as FullEntityPacket;
    expect(packet.type).toBe('FULL_ENTITY');
    expect(packet.tags).toEqual([{ tag: 49, value: 2 }]);
    expect(packet.unknownChildren).toHaveLength(1);
    expect(replay.diagnostics).toContainEqual(
      expect.objectContaining({ code: DiagnosticCode.MALFORMED_PACKET }),
    );
  });

  it('warns about unsafe integers but keeps parsing', () => {
    const { replay } = packetsOf('<TagChange entity="1" tag="1" value="99999999999999999999"/>');
    expect(replay.packets[0]!.type).toBe('TAG_CHANGE');
    expect(replay.diagnostics).toContainEqual(
      expect.objectContaining({ code: DiagnosticCode.UNSAFE_INTEGER }),
    );
  });

  it('accepts a bare Game root with a diagnostic', () => {
    const replay = parseReplay('<Game id="5"><TagChange entity="1" tag="1" value="1"/></Game>');
    expect(replay.packets).toHaveLength(1);
    expect(replay.metadata.version).toBeUndefined();
    expect(replay.metadata.game.id).toBe(5);
    expect(replay.diagnostics).toContainEqual(
      expect.objectContaining({ code: DiagnosticCode.UNEXPECTED_ROOT }),
    );
  });

  it('rejects a foreign root and a replay without games', () => {
    expect(() => parseReplay('<Nope/>')).toThrow(ReplayValidationError);
    expect(() => parseReplay('<HSReplay version="1.7"/>')).toThrow(/NO_GAME/);
  });

  it('parses only the first of several games and says so', () => {
    const xml =
      '<HSReplay version="1.7"><Game id="1"><TagChange entity="1" tag="1" value="1"/></Game><Game id="2"/></HSReplay>';
    const replay = parseReplay(xml);
    expect(replay.metadata.game.id).toBe(1);
    expect(replay.diagnostics).toContainEqual(
      expect.objectContaining({ code: DiagnosticCode.MULTIPLE_GAMES }),
    );
    expect(() => parseReplay(xml, { strict: true })).toThrow(ReplayValidationError);
  });
});
