import { describe, expect, it } from 'vitest';

import {
  BlockType,
  CardType,
  extractEvents,
  OptionType,
  parseReplay,
  type SemanticEvent,
  SemanticEventType,
  Zone,
} from '../../src/index.js';
import { PRELUDE, wrapGame } from '../helpers.js';

function events(body: string, types?: SemanticEvent['type'][]): SemanticEvent[] {
  const replay = parseReplay(wrapGame(`${PRELUDE}${body}`));
  return extractEvents(replay, types ? { types: new Set(types) } : {});
}

const BOARD = `
  <FullEntity id="72" cardID="HERO_01"><Tag tag="49" value="1"/><Tag tag="50" value="1"/><Tag tag="202" value="3"/></FullEntity>
  <FullEntity id="74" cardID="HERO_02"><Tag tag="49" value="1"/><Tag tag="50" value="2"/><Tag tag="202" value="3"/></FullEntity>
  <FullEntity id="75" cardID="HERO_01bp"><Tag tag="49" value="1"/><Tag tag="50" value="1"/><Tag tag="202" value="10"/></FullEntity>
  <FullEntity id="10"><Tag tag="49" value="3"/><Tag tag="50" value="1"/></FullEntity>
  <FullEntity id="11"><Tag tag="49" value="2"/><Tag tag="50" value="1"/></FullEntity>
  <FullEntity id="20" cardID="TAUNT_1"><Tag tag="49" value="1"/><Tag tag="50" value="2"/><Tag tag="202" value="4"/></FullEntity>
  <Block entity="1" type="5">
    <TagChange entity="2" tag="23" value="1"/>
    <TagChange entity="1" tag="20" value="1"/>
    <TagChange entity="1" tag="19" value="10"/>
  </Block>`;

describe('extractEvents', () => {
  it('reports game start, turns and the current player', () => {
    const list = events(BOARD);
    expect(list[0]).toMatchObject({
      index: 0,
      type: SemanticEventType.GAME_STARTED,
      gameEntityId: 1,
      packetIndex: 0,
    });
    const turn = list.find((event) => event.type === SemanticEventType.TURN_STARTED);
    expect(turn).toMatchObject({ turn: 1, playerEntityId: 2, blockIndex: 9 });
    list.forEach((event, position) => {
      expect(event.index).toBe(position);
      if (position > 0)
        expect(event.packetIndex).toBeGreaterThanOrEqual(list[position - 1]!.packetIndex);
    });
  });

  it('derives card played with the type revealed inside the block, and hero power use', () => {
    const list = events(`${BOARD}
      <Block entity="10" type="7" target="74">
        <ShowEntity entity="10" cardID="SPELL_1"><Tag tag="202" value="5"/></ShowEntity>
        <TagChange entity="10" tag="49" value="4"/>
        <Block entity="10" type="3">
          <MetaData meta="1" data="3"><Info entity="74"/></MetaData>
          <TagChange entity="74" tag="44" value="3"/>
        </Block>
      </Block>
      <Block entity="75" type="7">
        <Block entity="75" type="3">
          <MetaData meta="2" data="2"><Info entity="72"/></MetaData>
        </Block>
      </Block>`);
    const played = list.find((event) => event.type === SemanticEventType.CARD_PLAYED);
    expect(played).toMatchObject({
      entity: 10,
      cardId: 'SPELL_1',
      cardType: CardType.SPELL,
      playerEntityId: 2,
      target: 74,
      turn: 1,
    });
    const damage = list.find((event) => event.type === SemanticEventType.DAMAGE);
    expect(damage).toMatchObject({ target: { kind: 'id', id: 74 }, amount: 3, blockEntity: 10 });
    expect(damage && 'source' in damage).toBe(false);
    expect(list.indexOf(played!)).toBeLessThan(list.indexOf(damage!));
    const heroPower = list.find((event) => event.type === SemanticEventType.HERO_POWER_USED);
    expect(heroPower).toMatchObject({ entity: 75, cardId: 'HERO_01bp', playerEntityId: 2 });
    expect(heroPower && 'target' in heroPower).toBe(false);
    const healing = list.find((event) => event.type === SemanticEventType.HEALING);
    expect(healing).toMatchObject({ target: { kind: 'id', id: 72 }, amount: 2, blockEntity: 75 });
    const zone = list.find(
      (event) => event.type === SemanticEventType.ZONE_CHANGED && event.entity === 10,
    );
    expect(zone).toMatchObject({ from: Zone.HAND, to: Zone.GRAVEYARD, cardId: 'SPELL_1' });
  });

  it('reports attacks with the intended target and the actual defender', () => {
    const list = events(`${BOARD}
      <Block entity="72" type="1" target="74">
        <TagChange entity="1" tag="39" value="72"/>
        <TagChange entity="1" tag="37" value="74"/>
        <TagChange entity="72" tag="38" value="1"/>
        <TagChange entity="20" tag="36" value="1"/>
        <MetaData meta="1" data="4"><Info entity="20"/></MetaData>
        <TagChange entity="20" tag="49" value="4"/>
      </Block>
      <Block entity="72" type="1"/>`);
    const attacks = list.filter((event) => event.type === SemanticEventType.ATTACK);
    expect(attacks).toHaveLength(2);
    expect(attacks[0]).toMatchObject({
      entity: 72,
      cardId: 'HERO_01',
      playerEntityId: 2,
      target: 74,
      defender: 20,
    });
    expect(attacks[1]).toMatchObject({ entity: 72 });
    expect('target' in attacks[1]!).toBe(false);
    expect('defender' in attacks[1]!).toBe(false);
    const died = list.find((event) => event.type === SemanticEventType.ENTITY_DIED);
    expect(died).toMatchObject({
      entity: 20,
      cardId: 'TAUNT_1',
      cardType: CardType.MINION,
      playerEntityId: 3,
    });
    expect(attacks[0]!.index).toBeLessThan(died!.index);
  });

  it('reports draws from tag changes and from reveals, fatigue and triggers', () => {
    const list = events(`${BOARD}
      <Block entity="1" type="${String(BlockType.TRIGGER)}" triggerKeyword="32">
        <TagChange entity="11" tag="49" value="3"/>
        <FullEntity id="12"><Tag tag="49" value="2"/><Tag tag="50" value="2"/></FullEntity>
        <ShowEntity entity="12" cardID="DRAWN_1"><Tag tag="49" value="3"/></ShowEntity>
      </Block>
      <Block entity="72" type="${String(BlockType.FATIGUE)}"><MetaData meta="1" data="1"><Info entity="72"/></MetaData></Block>`);
    const drawn = list.filter((event) => event.type === SemanticEventType.CARD_DRAWN);
    expect(drawn.map((event) => [event.entity, event.cardId, event.playerEntityId])).toEqual([
      [11, undefined, 2],
      [12, 'DRAWN_1', 3],
    ]);
    expect(list.find((event) => event.type === SemanticEventType.TRIGGERED)).toMatchObject({
      entity: 1,
      triggerKeyword: 32,
    });
    expect(list.find((event) => event.type === SemanticEventType.FATIGUE)).toMatchObject({
      entity: 72,
      playerEntityId: 2,
    });
  });

  it('reports choices, options and the end of the game', () => {
    const list = events(`${BOARD}
      <Block entity="1" type="5">
        <Choices entity="3" id="4" type="2" min="1" max="1" source="20">
          <Choice index="0" entity="30"/><Choice index="1" entity="31"/>
        </Choices>
        <ChosenEntities entity="3" id="4"><Choice index="0" entity="31"/></ChosenEntities>
      </Block>
      <Options id="9">
        <Option index="0" type="2"/>
        <Option index="1" entity="10" type="3"><SubOption index="0" entity="13"/><SubOption index="1" entity="14"/></Option>
      </Options>
      <SendOption option="1" subOption="1" target="74" position="2"/>
      <SendOption option="0" subOption="-1" target="0" position="0"/>
      <TagChange entity="3" tag="17" value="8"/>
      <TagChange entity="2" tag="17" value="4"/>
      <TagChange entity="3" tag="17" value="5"/>
      <TagChange entity="1" tag="204" value="3"/>`);
    expect(list.find((event) => event.type === SemanticEventType.CHOICE_OFFERED)).toMatchObject({
      choiceId: 4,
      choiceType: 2,
      playerEntityId: 3,
      source: { kind: 'id', id: 20 },
      entities: [
        { kind: 'id', id: 30 },
        { kind: 'id', id: 31 },
      ],
    });
    expect(list.find((event) => event.type === SemanticEventType.CHOICE_MADE)).toMatchObject({
      choiceId: 4,
      choiceType: 2,
      playerEntityId: 3,
      chosen: [{ kind: 'id', id: 31 }],
    });
    const options = list.filter((event) => event.type === SemanticEventType.OPTION_CHOSEN);
    expect(options[0]).toMatchObject({
      optionsId: 9,
      optionType: OptionType.POWER,
      entity: { kind: 'id', id: 10 },
      subOptionEntity: { kind: 'id', id: 14 },
      target: { kind: 'id', id: 74 },
      position: 2,
    });
    expect(options[1]).toMatchObject({
      optionsId: 9,
      optionType: OptionType.END_TURN,
      position: 0,
    });
    expect('target' in options[1]!).toBe(false);
    expect(list.find((event) => event.type === SemanticEventType.CONCEDED)).toMatchObject({
      playerEntityId: 3,
    });
    const ended = list[list.length - 1];
    expect(ended).toMatchObject({
      type: SemanticEventType.GAME_ENDED,
      winners: [2],
      losers: [3],
      results: [
        { playerEntityId: 2, playState: 4 },
        { playerEntityId: 3, playState: 5 },
      ],
    });
  });

  it('filters by type and accepts a plain packet list', () => {
    const replay = parseReplay(wrapGame(`${PRELUDE}${BOARD}`));
    const only = extractEvents(replay.packets, {
      types: new Set([SemanticEventType.TURN_STARTED]),
    });
    expect(only.map((event) => event.type)).toEqual([SemanticEventType.TURN_STARTED]);
    expect(only[0]!.index).toBe(0);
  });
});
