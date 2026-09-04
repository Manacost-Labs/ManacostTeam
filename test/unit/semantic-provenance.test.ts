import { describe, expect, it } from 'vitest';

import {
  CardType,
  extractEvents,
  parseReplay,
  type SemanticEvent,
  SemanticEventType,
  SemanticRuleId,
  Step,
} from '../../src/index.js';
import { PRELUDE, wrapGame } from '../helpers.js';

function events(body: string): SemanticEvent[] {
  return extractEvents(parseReplay(wrapGame(`${PRELUDE}${body}`)));
}

const HERO = `
  <FullEntity id="72" cardID="HERO_01"><Tag tag="49" value="1"/><Tag tag="50" value="1"/><Tag tag="202" value="3"/></FullEntity>
  <FullEntity id="74" cardID="HERO_02"><Tag tag="49" value="1"/><Tag tag="50" value="2"/><Tag tag="202" value="3"/></FullEntity>`;

const MAIN_ACTION = `<TagChange entity="1" tag="19" value="${String(Step.MAIN_ACTION)}"/>`;

describe('semantic evidence', () => {
  it('is attached to every event with the packets it came from', () => {
    const list = events(`${HERO}${MAIN_ACTION}
      <FullEntity id="10"><Tag tag="49" value="2"/><Tag tag="50" value="1"/></FullEntity>
      <Block entity="1" type="5"><TagChange entity="10" tag="49" value="3"/></Block>`);
    expect(list.length).toBeGreaterThan(0);
    for (const event of list) {
      expect(['observed', 'derived', 'heuristic']).toContain(event.evidence.level);
      expect(typeof event.evidence.rule).toBe('string');
      expect(event.evidence.packetIndices.length).toBeGreaterThan(0);
      expect(event.evidence.packetIndices).toContain(event.packetIndex);
    }
    const drawn = list.find((event) => event.type === SemanticEventType.CARD_DRAWN);
    expect(drawn?.evidence).toEqual({
      level: 'derived',
      rule: SemanticRuleId.CARD_DRAWN,
      packetIndices: [drawn!.packetIndex],
    });
    const zone = list.find(
      (event) => event.type === SemanticEventType.ZONE_CHANGED && event.entity === 10,
    );
    expect(zone?.evidence.level).toBe('observed');
  });
});

describe('CARD_DRAWN', () => {
  it('is not emitted for the opening hand or mulligan replacements', () => {
    const list = events(`${HERO}
      <FullEntity id="10"><Tag tag="49" value="2"/><Tag tag="50" value="1"/></FullEntity>
      <FullEntity id="11"><Tag tag="49" value="2"/><Tag tag="50" value="1"/></FullEntity>
      <TagChange entity="10" tag="49" value="3"/>
      <TagChange entity="1" tag="19" value="${String(Step.BEGIN_MULLIGAN)}"/>
      <TagChange entity="11" tag="49" value="3"/>
      ${MAIN_ACTION}
      <TagChange entity="11" tag="49" value="2"/>
      <TagChange entity="11" tag="49" value="3"/>`);
    const drawn = list.filter((event) => event.type === SemanticEventType.CARD_DRAWN);
    expect(drawn.map((event) => [event.entity, event.packetIndex])).toEqual([[11, 12]]);
    expect(
      list.filter((event) => event.type === SemanticEventType.ZONE_CHANGED && event.to === 3),
    ).toHaveLength(3);
  });
});

describe('ENTITY_DIED', () => {
  it('is not emitted for spells and enchantments leaving play', () => {
    const list = events(`${HERO}${MAIN_ACTION}
      <FullEntity id="20" cardID="SPELL"><Tag tag="49" value="1"/><Tag tag="50" value="1"/><Tag tag="202" value="5"/></FullEntity>
      <FullEntity id="21" cardID="ENCH"><Tag tag="49" value="1"/><Tag tag="50" value="1"/><Tag tag="202" value="6"/></FullEntity>
      <FullEntity id="22" cardID="MINION"><Tag tag="49" value="1"/><Tag tag="50" value="1"/><Tag tag="202" value="4"/></FullEntity>
      <FullEntity id="23" cardID="WEAPON"><Tag tag="49" value="1"/><Tag tag="50" value="1"/><Tag tag="202" value="7"/></FullEntity>
      <FullEntity id="24"><Tag tag="49" value="1"/><Tag tag="50" value="1"/></FullEntity>
      <TagChange entity="20" tag="49" value="4"/>
      <TagChange entity="21" tag="49" value="4"/>
      <Block entity="1" type="6">
        <TagChange entity="22" tag="49" value="4"/>
        <TagChange entity="23" tag="49" value="4"/>
        <TagChange entity="24" tag="49" value="4"/>
      </Block>`);
    const died = list.filter((event) => event.type === SemanticEventType.ENTITY_DIED);
    expect(died.map((event) => [event.entity, event.cardType])).toEqual([
      [22, CardType.MINION],
      [23, CardType.WEAPON],
    ]);
    expect(died[0]?.evidence).toMatchObject({ level: 'derived', rule: SemanticRuleId.ENTITY_DIED });
  });
});

describe('DAMAGE', () => {
  it('attributes the source to LAST_AFFECTED_BY when the log records it, else only the block entity', () => {
    const list = events(`${HERO}${MAIN_ACTION}
      <FullEntity id="30" cardID="DEATHRATTLER"><Tag tag="49" value="1"/><Tag tag="50" value="1"/><Tag tag="202" value="4"/></FullEntity>
      <Block entity="72" type="1" target="74">
        <MetaData meta="1" data="2"><Info entity="74"/></MetaData>
        <TagChange entity="74" tag="18" value="30"/>
        <TagChange entity="74" tag="44" value="2"/>
        <MetaData meta="1" data="1"><Info entity="72"/></MetaData>
        <TagChange entity="72" tag="44" value="1"/>
      </Block>`);
    const damage = list.filter((event) => event.type === SemanticEventType.DAMAGE);
    expect(damage[0]).toMatchObject({
      target: { kind: 'id', id: 74 },
      amount: 2,
      source: 30,
      blockEntity: 72,
      evidence: { level: 'derived', rule: SemanticRuleId.DAMAGE_SOURCE },
    });
    expect(damage[0]!.evidence.packetIndices).toHaveLength(2);
    expect(damage[1]).toMatchObject({ target: { kind: 'id', id: 72 }, amount: 1, blockEntity: 72 });
    expect(damage[1]!.source).toBeUndefined();
    expect(damage[1]!.evidence).toMatchObject({ level: 'observed', rule: SemanticRuleId.DAMAGE });
  });
});

describe('CARD_PLAYED', () => {
  it('distinguishes a player action from a PLAY block nested in an effect', () => {
    const list = events(`${HERO}${MAIN_ACTION}
      <FullEntity id="40" cardID="A"><Tag tag="49" value="3"/><Tag tag="50" value="1"/><Tag tag="202" value="5"/></FullEntity>
      <FullEntity id="41" cardID="B"><Tag tag="49" value="2"/><Tag tag="50" value="1"/><Tag tag="202" value="5"/></FullEntity>
      <Block entity="40" type="7">
        <TagChange entity="40" tag="49" value="1"/>
        <Block entity="40" type="3">
          <Block entity="41" type="7"><TagChange entity="41" tag="49" value="1"/></Block>
        </Block>
      </Block>`);
    const played = list.filter((event) => event.type === SemanticEventType.CARD_PLAYED);
    expect(played.map((event) => [event.entity, event.initiator])).toEqual([
      [40, 'player'],
      [41, 'effect'],
    ]);
    expect(played[0]?.evidence.rule).toBe(SemanticRuleId.CARD_PLAYED);
  });
});

describe('GAME_RESET', () => {
  it('is reported as an observed event so turn numbers going backwards can be explained', () => {
    const list = events(`${HERO}${MAIN_ACTION}
      <Block entity="1" type="5"><TagChange entity="1" tag="20" value="5"/></Block>
      <Block entity="1" type="11"><TagChange entity="1" tag="20" value="2"/></Block>`);
    const reset = list.find((event) => event.type === SemanticEventType.GAME_RESET);
    expect(reset).toMatchObject({
      entity: 1,
      evidence: { level: 'observed', rule: SemanticRuleId.GAME_RESET },
    });
    const turns = list
      .filter((event) => event.type === SemanticEventType.TURN_STARTED)
      .map((event) => event.turn);
    expect(turns).toEqual([5, 2]);
    expect(reset!.index).toBeLessThan(
      list.findIndex((event) => event.type === SemanticEventType.TURN_STARTED && event.turn === 2),
    );
  });
});

describe('DAMAGE attribution with several targets', () => {
  it("finds LAST_AFFECTED_BY written after the other targets' MetaData packets", () => {
    const list = events(`${HERO}${MAIN_ACTION}
      <FullEntity id="93"><Tag tag="49" value="1"/><Tag tag="50" value="2"/><Tag tag="202" value="4"/></FullEntity>
      <FullEntity id="94"><Tag tag="49" value="1"/><Tag tag="50" value="2"/><Tag tag="202" value="4"/></FullEntity>
      <Block entity="45" type="3">
        <MetaData meta="1" data="2"><Info entity="93"/></MetaData>
        <MetaData meta="1" data="2"><Info entity="94"/></MetaData>
        <TagChange entity="93" tag="18" value="45"/>
        <TagChange entity="93" tag="44" value="2"/>
        <TagChange entity="94" tag="18" value="45"/>
        <TagChange entity="94" tag="44" value="2"/>
        <MetaData meta="1" data="1"><Info entity="93"/></MetaData>
        <TagChange entity="93" tag="44" value="3"/>
      </Block>`);
    const damage = list.filter((event) => event.type === SemanticEventType.DAMAGE);
    expect(
      damage.map((event) => [
        event.target.kind === 'id' ? event.target.id : -1,
        event.amount,
        event.source,
      ]),
    ).toEqual([
      [93, 2, 45],
      [94, 2, 45],
      [93, 1, undefined],
    ]);
    expect(damage[0]?.evidence.packetIndices).toEqual([
      damage[0]!.packetIndex,
      damage[0]!.packetIndex + 2,
    ]);
  });
});

describe('CARD_PLAYED on non-card entities', () => {
  it('is not emitted for game-mode buttons, but is for never-revealed and location entities', () => {
    const list = events(`${HERO}${MAIN_ACTION}
      <FullEntity id="60" cardID="TB_BaconShop_Button"><Tag tag="49" value="1"/><Tag tag="50" value="1"/><Tag tag="202" value="12"/></FullEntity>
      <FullEntity id="61"><Tag tag="49" value="3"/><Tag tag="50" value="1"/></FullEntity>
      <FullEntity id="62" cardID="LOC_1"><Tag tag="49" value="3"/><Tag tag="50" value="1"/><Tag tag="202" value="39"/></FullEntity>
      <Block entity="60" type="7"><TagChange entity="60" tag="43" value="1"/></Block>
      <Block entity="61" type="7"><TagChange entity="61" tag="49" value="1"/></Block>
      <Block entity="62" type="7"><TagChange entity="62" tag="49" value="1"/></Block>`);
    const played = list.filter((event) => event.type === SemanticEventType.CARD_PLAYED);
    expect(played.map((event) => [event.entity, event.cardType])).toEqual([
      [61, undefined],
      [62, CardType.LOCATION],
    ]);
  });
});

describe('HEALING', () => {
  it('never claims a source, because the log does not record one for healing', () => {
    const list = events(`${HERO}${MAIN_ACTION}
      <Block entity="72" type="3">
        <MetaData meta="2" data="4"><Info entity="74"/></MetaData>
        <TagChange entity="74" tag="18" value="72"/>
        <TagChange entity="74" tag="44" value="0"/>
      </Block>`);
    const healing = list.find((event) => event.type === SemanticEventType.HEALING);
    expect(healing).toMatchObject({
      amount: 4,
      blockEntity: 72,
      evidence: { level: 'observed', rule: SemanticRuleId.HEALING },
    });
    expect(healing && 'source' in healing).toBe(false);
    expect('HEALING_SOURCE' in SemanticRuleId).toBe(false);
  });
});

describe('ENTITY_DIED', () => {
  it('records whether the entity left play inside a DEATHS block', () => {
    const list = events(`${HERO}${MAIN_ACTION}
      <FullEntity id="22" cardID="MINION"><Tag tag="49" value="1"/><Tag tag="50" value="1"/><Tag tag="202" value="4"/></FullEntity>
      <FullEntity id="23" cardID="WEAPON"><Tag tag="49" value="1"/><Tag tag="50" value="1"/><Tag tag="202" value="7"/></FullEntity>
      <Block entity="1" type="6"><TagChange entity="22" tag="49" value="4"/></Block>
      <Block entity="72" type="7"><TagChange entity="23" tag="49" value="4"/></Block>`);
    const died = list.filter((event) => event.type === SemanticEventType.ENTITY_DIED);
    expect(died.map((event) => [event.entity, event.viaDeathsBlock])).toEqual([
      [22, true],
      [23, false],
    ]);
  });
});

describe('CARD_PLAYED for hidden and location entities', () => {
  it('reports an opponent secret played from hand even though the card is never revealed', () => {
    const list = events(`${HERO}${MAIN_ACTION}
      <FullEntity id="80"><Tag tag="49" value="3"/><Tag tag="50" value="2"/></FullEntity>
      <Block entity="80" type="7"><TagChange entity="80" tag="49" value="7"/></Block>`);
    const played = list.filter((event) => event.type === SemanticEventType.CARD_PLAYED);
    expect(played).toHaveLength(1);
    expect(played[0]).toMatchObject({ entity: 80, playerEntityId: 3, initiator: 'player' });
    expect(played[0]?.cardType).toBeUndefined();
  });

  it('reports a location activation as CARD_PLAYED of a LOCATION (card type 39)', () => {
    const list = events(`${HERO}${MAIN_ACTION}
      <FullEntity id="81" cardID="REV_290"><Tag tag="49" value="1"/><Tag tag="50" value="1"/><Tag tag="202" value="39"/></FullEntity>
      <Block entity="81" type="7"><TagChange entity="81" tag="43" value="1"/></Block>`);
    const played = list.filter((event) => event.type === SemanticEventType.CARD_PLAYED);
    expect(played.map((event) => [event.entity, event.cardType])).toEqual([
      [81, CardType.LOCATION],
    ]);
  });

  it('counts a draw during the newer MAIN_PRE_ACTION / MAIN_POST_ACTION steps', () => {
    const list = events(`${HERO}
      <FullEntity id="82"><Tag tag="49" value="2"/><Tag tag="50" value="1"/></FullEntity>
      <TagChange entity="1" tag="19" value="${String(Step.MAIN_POST_ACTION)}"/>
      <TagChange entity="82" tag="49" value="3"/>`);
    expect(
      list.filter((event) => event.type === SemanticEventType.CARD_DRAWN).map((e) => e.entity),
    ).toEqual([82]);
  });
});
