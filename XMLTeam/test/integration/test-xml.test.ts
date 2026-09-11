import { describe, expect, it } from 'vitest';

import {
  CardType,
  flattenPackets,
  GameTag,
  getCardType,
  getZone,
  parseReplay,
  ReplayPacketType,
  type ReplayDiagnostic,
  type TagChangePacket,
  walkPackets,
  Zone,
} from '../../src/index.js';
import { parseReplayFile } from '../../src/node.js';
import { FIXTURE_PATH, FIXTURE_URL } from '../helpers.js';
import { readFile } from 'node:fs/promises';

const replay = await parseReplayFile(FIXTURE_PATH);
const flat = flattenPackets(replay.packets);

describe('test.xml (real HSReplay fixture)', () => {
  it('parses metadata', () => {
    expect(replay.metadata.version).toBe('1.7');
    expect(replay.metadata.build).toBe(250339);
    expect(replay.metadata.game).toEqual({
      id: 13991,
      ts: '2026-09-04T02:42:09.655151-04:00',
      gameType: 7,
      format: 2,
      scenarioId: 2,
    });
    expect(
      replay.metadata.players.map((player) => [player.entityId, player.playerId, player.name]),
    ).toEqual([
      [2, 1, 'MrLean#11738'],
      [3, 2, 'sunq#11510'],
    ]);
    expect(replay.metadata.players[1]?.deck?.cards).toHaveLength(30);
  });

  it('produces packets with strictly increasing, gap-free indexes', () => {
    expect(replay.packets.length).toBeGreaterThan(500);
    expect(flat).toHaveLength(replay.packetCount);
    flat.forEach((packet, position) => {
      expect(packet.index).toBe(position);
    });
  });

  it('contains no unknown packets and only known diagnostics', () => {
    expect(flat.filter((packet) => packet.type === ReplayPacketType.UNKNOWN)).toHaveLength(0);
    expect(flat.some((packet) => packet.unknownAttributes !== undefined)).toBe(false);
    expect(flat.some((packet) => packet.unknownChildren !== undefined)).toBe(false);
    const levels = new Set(
      replay.diagnostics.map((diagnostic: ReplayDiagnostic) => diagnostic.level),
    );
    expect(levels.has('error')).toBe(false);
    expect(replay.diagnostics).toEqual([]);
  });

  it('parses cleanly in strict mode too', async () => {
    const strict = await parseReplayFile(FIXTURE_URL, { strict: true });
    expect(strict.packetCount).toBe(replay.packetCount);
  });

  it('preserves the block hierarchy', () => {
    const depths = [...walkPackets(replay.packets)].map((visit) => visit.depth);
    expect(Math.max(...depths)).toBeGreaterThanOrEqual(3);
    const blocks = flat.filter((packet) => packet.type === ReplayPacketType.BLOCK);
    expect(blocks).toHaveLength(520);
    const subSpells = flat.filter((packet) => packet.type === ReplayPacketType.SUB_SPELL);
    expect(subSpells).toHaveLength(74);
    const nested = blocks.filter((block) =>
      block.children.some((child) => child.type === ReplayPacketType.BLOCK),
    );
    expect(nested.length).toBeGreaterThan(0);
    for (const block of blocks) {
      block.children.forEach((child, position) => {
        expect(child.index).toBeGreaterThan(block.index);
        if (position > 0) expect(child.index).toBeGreaterThan(block.children[position - 1]!.index);
      });
    }
  });

  it('counts every element kind exactly as found in the XML', () => {
    const counts = new Map<string, number>();
    for (const packet of flat) counts.set(packet.type, (counts.get(packet.type) ?? 0) + 1);
    expect(Object.fromEntries(counts)).toEqual({
      GAME_ENTITY: 1,
      PLAYER: 2,
      FULL_ENTITY: 259,
      SHOW_ENTITY: 118,
      HIDE_ENTITY: 42,
      TAG_CHANGE: 6921,
      BLOCK: 520,
      SUB_SPELL: 74,
      META_DATA: 439,
      CHOICES: 12,
      CHOSEN_ENTITIES: 12,
      SEND_CHOICES: 8,
      OPTIONS: 63,
      SEND_OPTION: 62,
      SHUFFLE_DECK: 2,
    });
    const tagChangesWithDef = flat.filter(
      (packet): packet is TagChangePacket =>
        packet.type === ReplayPacketType.TAG_CHANGE && packet.hasChangeDef === true,
    );
    expect(tagChangesWithDef).toHaveLength(17);
  });

  it('reconstructs the entity store', () => {
    expect(replay.entities.size).toBe(262);
    const game = replay.state.game!;
    expect(game.id).toBe(1);
    expect(getCardType(game)).toBe(CardType.GAME);
    expect(game.tags.get(GameTag.STATE)).toBe(3);
    expect(game.tags.get(GameTag.TURN)).toBeGreaterThan(1);

    const [alice, bob] = replay.state.players;
    expect(alice?.player?.name).toBe('MrLean#11738');
    expect(alice?.tags.get(GameTag.PLAYSTATE)).toBe(4);
    expect(bob?.tags.get(GameTag.PLAYSTATE)).toBe(5);
    expect(bob?.player?.deck?.cards.map((card) => card.id)).toContain('TIME_702');

    const hero = replay.entities.get(alice!.tags.get(GameTag.HERO_ENTITY)!)!;
    expect(getCardType(hero)).toBe(CardType.HERO);
    expect(getZone(hero)).toBe(Zone.PLAY);
    expect(hero.cardId).toBeDefined();

    for (const entity of replay.entities) {
      expect(entity.tags.get(GameTag.ENTITY_ID)).toBe(entity.id);
    }
  });

  it('applies TagChange packets to entity state', () => {
    const last = flat[flat.length - 1] as TagChangePacket;
    expect(last.type).toBe(ReplayPacketType.TAG_CHANGE);
    expect(last).toMatchObject({ entity: { kind: 'id', id: 1 }, tag: GameTag.STATE, value: 3 });
    expect(replay.entities.get(1)?.tags.get(GameTag.STATE)).toBe(3);

    const revealed = flat.find((packet) => packet.type === ReplayPacketType.SHOW_ENTITY);
    expect(revealed).toBeDefined();
    if (revealed?.type === ReplayPacketType.SHOW_ENTITY && revealed.entity.kind === 'id') {
      expect(replay.entities.get(revealed.entity.id)?.cardId).toBe(revealed.cardId);
    }
  });

  it('is deterministic across parses', async () => {
    const xml = await readFile(FIXTURE_PATH, 'utf8');
    const first = parseReplay(xml);
    const second = parseReplay(xml);
    expect(second.packets).toEqual(first.packets);
    expect(second.metadata).toEqual(first.metadata);
    expect(second.diagnostics).toEqual(first.diagnostics);
    expect(
      [...second.entities].map((entity) => [entity.id, entity.cardId, [...entity.tags]]),
    ).toEqual([...first.entities].map((entity) => [entity.id, entity.cardId, [...entity.tags]]));
  });
});

describe('test.xml timeline and history', () => {
  it('reconstructs intermediate states that agree with the final state and history', async () => {
    const { createTimeline, collectTagHistory, GameEntityState, Step } =
      await import('../../src/index.js');
    const timeline = createTimeline(replay, { checkpointInterval: 500 });
    expect(timeline.checkpoints.length).toBe(Math.floor(replay.packetCount / 500));

    const final = timeline.stateAt(replay.packetCount - 1);
    expect(final.entities.size).toBe(replay.entities.size);
    for (const entity of replay.entities) {
      expect([...final.entities.get(entity.id)!.tags]).toEqual([...entity.tags]);
    }
    expect(final.turn).toBe(replay.state.turn);
    expect(final.step).toBe(Step.FINAL_GAMEOVER);
    expect(final.game?.tags.get(GameTag.STATE)).toBe(GameEntityState.COMPLETE);

    const history = collectTagHistory(replay.packets, {
      entities: new Set([1]),
      tags: new Set([GameTag.TURN]),
    });
    const turns = history.get(1)!.get(GameTag.TURN)!;
    expect(turns.map((record) => record.value)).toEqual(
      Array.from({ length: turns.length }, (_, i) => i + 1),
    );
    const midTurn = turns[Math.floor(turns.length / 2)]!;
    expect(timeline.stateAt(midTurn.packetIndex).turn).toBe(midTurn.value);
    expect(timeline.stateAt(midTurn.packetIndex - 1).turn).toBe(midTurn.value! - 1);
    expect(timeline.stateAt(-1).entities.size).toBe(0);
  });
});

describe('test.xml semantic events', () => {
  it('derives a consistent event stream from the real game', async () => {
    const {
      extractEvents,
      SemanticEventType,
      collectTagHistory,
      GameTag,
      Zone,
      CardType,
      PlayState,
    } = await import('../../src/index.js');
    const events = extractEvents(replay);
    const count = (type: string) => events.filter((event) => event.type === type).length;

    events.forEach((event, position) => {
      expect(event.index).toBe(position);
      if (position > 0)
        expect(event.packetIndex).toBeGreaterThanOrEqual(events[position - 1]!.packetIndex);
      if (event.blockIndex !== undefined)
        expect(event.blockIndex).toBeLessThan(event.packetIndex + 1);
    });

    expect(events[0]?.type).toBe(SemanticEventType.GAME_STARTED);
    expect(events[events.length - 1]).toMatchObject({
      type: SemanticEventType.GAME_ENDED,
      winners: [2],
      losers: [3],
    });
    expect(count(SemanticEventType.CONCEDED)).toBe(1);

    const turns = events.filter((event) => event.type === SemanticEventType.TURN_STARTED);
    expect(turns.map((event) => event.turn)).toEqual(Array.from({ length: 24 }, (_, i) => i + 1));
    const firstPlayer = replay.state.players.find(
      (player) => player.tags.get(GameTag.FIRST_PLAYER) === 1,
    )!;
    expect(turns[0]).toMatchObject({ playerEntityId: firstPlayer.id });
    expect(new Set(turns.map((event) => event.playerEntityId)).size).toBe(2);
    for (let i = 1; i < turns.length; i++)
      expect(turns[i]!.playerEntityId).not.toBe(turns[i - 1]!.playerEntityId);

    expect(count(SemanticEventType.ATTACK)).toBe(30);
    const attacks = events.filter((event) => event.type === SemanticEventType.ATTACK);
    expect(attacks.filter((event) => event.target !== undefined)).toHaveLength(26);
    expect(
      attacks.every(
        (event) => event.cardType === CardType.MINION || event.cardType === CardType.HERO,
      ),
    ).toBe(true);
    // Every attack resolves a defender through the DEFENDING tag, including the
    // four effect-forced attacks that carry no target attribute; none is redirected.
    expect(attacks.every((event) => event.defender !== undefined)).toBe(true);
    expect(
      attacks.filter((event) => event.target !== undefined && event.target !== event.defender),
    ).toHaveLength(0);

    expect(count(SemanticEventType.CARD_PLAYED) + count(SemanticEventType.HERO_POWER_USED)).toBe(
      55,
    );
    expect(count(SemanticEventType.HERO_POWER_USED)).toBe(2);
    const played = events.filter((event) => event.type === SemanticEventType.CARD_PLAYED);
    expect(
      played.every((event) => event.cardId !== undefined && event.playerEntityId !== undefined),
    ).toBe(true);

    expect(count(SemanticEventType.CHOICE_OFFERED)).toBe(12);
    expect(count(SemanticEventType.CHOICE_MADE)).toBe(12);
    expect(count(SemanticEventType.OPTION_CHOSEN)).toBe(62);
    expect(
      events
        .filter((event) => event.type === SemanticEventType.OPTION_CHOSEN)
        .every((e) => e.optionsId !== undefined),
    ).toBe(true);

    const infoCount = flat.reduce(
      (sum, p) => sum + (p.type === ReplayPacketType.META_DATA && p.meta === 1 ? p.info.length : 0),
      0,
    );
    expect(count(SemanticEventType.DAMAGE)).toBe(infoCount);

    // Cross-check against the tag history (an independent reading of the packets):
    // every draw is a DECK → HAND transition after the game reached its main phase,
    // every death is a PLAY → GRAVEYARD transition of a minion, hero or weapon.
    const zones = collectTagHistory(replay.packets, { tags: new Set([GameTag.ZONE]) });
    const transitions = new Map<string, number>();
    for (const [entityId, byTag] of zones) {
      const values = byTag.get(GameTag.ZONE)!;
      for (let i = 1; i < values.length; i++) {
        const from = values[i - 1]!.value;
        const to = values[i]!.value;
        if (from !== undefined && to !== undefined) {
          transitions.set(`${String(entityId)}@${String(values[i]!.packetIndex)}`, from * 100 + to);
        }
      }
    }
    const firstTurn = turns[0]!.packetIndex;
    const drawn = events.filter((event) => event.type === SemanticEventType.CARD_DRAWN);
    expect(drawn.length).toBeGreaterThan(20);
    for (const event of drawn) {
      expect(transitions.get(`${String(event.entity)}@${String(event.packetIndex)}`)).toBe(
        Zone.DECK * 100 + Zone.HAND,
      );
      expect(event.packetIndex).toBeGreaterThan(firstTurn);
      expect(event.evidence).toEqual({
        level: 'derived',
        rule: 'CARD_DRAWN',
        packetIndices: [event.packetIndex],
      });
    }
    const died = events.filter((event) => event.type === SemanticEventType.ENTITY_DIED);
    expect(died.length).toBeGreaterThan(10);
    const dying = new Set<number>([
      CardType.MINION,
      CardType.HERO,
      CardType.WEAPON,
      CardType.LOCATION,
    ]);
    for (const event of died) {
      expect(transitions.get(`${String(event.entity)}@${String(event.packetIndex)}`)).toBe(
        Zone.PLAY * 100 + Zone.GRAVEYARD,
      );
      expect(dying.has(replay.entities.get(event.entity)!.tags.get(GameTag.CARDTYPE)!)).toBe(true);
    }
    const spellsLeavingPlay = [...transitions.entries()].filter(
      ([key, transition]) =>
        transition === Zone.PLAY * 100 + Zone.GRAVEYARD &&
        replay.entities.get(Number(key.split('@')[0]))!.tags.get(GameTag.CARDTYPE) ===
          CardType.SPELL,
    );
    expect(spellsLeavingPlay.length).toBeGreaterThan(0);

    const ended = events[events.length - 1];
    expect(
      ended?.type === SemanticEventType.GAME_ENDED && ended.results.map((r) => r.playState),
    ).toEqual([PlayState.WON, PlayState.LOST]);
  });
});

describe('test.xml streaming', () => {
  it('yields the same result as the in-memory parser', async () => {
    const { parseReplayFileStream } = await import('../../src/node.js');
    const streamed = await parseReplayFileStream(FIXTURE_PATH);
    expect(streamed.packets).toEqual(replay.packets);
    expect(streamed.packetCount).toBe(replay.packetCount);
    expect(streamed.metadata).toEqual(replay.metadata);
    expect(streamed.diagnostics).toEqual(replay.diagnostics);
    expect([...streamed.entities].map((e) => [e.id, e.cardId, [...e.tags]])).toEqual(
      [...replay.entities].map((e) => [e.id, e.cardId, [...e.tags]]),
    );
  });
});
