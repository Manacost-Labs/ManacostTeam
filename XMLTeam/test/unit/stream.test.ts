import { describe, expect, it } from 'vitest';

import {
  DiagnosticCode,
  parseReplayDocument,
  parseReplayStream,
  type ReplayDocument,
  ReplayParseError,
  ReplayValidationError,
  streamReplay,
} from '../../src/index.js';
import { PRELUDE, wrapGame } from '../helpers.js';

const XML = wrapGame(`${PRELUDE}
  <Block entity="2" type="7">
    <TagChange entity="4" tag="49" value="3"/>
    <Mystery/>
  </Block>
  <TagChange entity="1" tag="20" value="2"/>`);

function* chunksOf(text: string, size: number): Generator<string> {
  for (let offset = 0; offset < text.length; offset += size)
    yield text.slice(offset, offset + size);
}

function comparable(document: ReplayDocument): unknown {
  return {
    version: document.version,
    build: document.build,
    diagnostics: document.diagnostics,
    games: document.games.map((game) => ({
      metadata: game.metadata,
      packets: game.packets,
      packetCount: game.packetCount,
      diagnostics: game.diagnostics,
      entities: [...game.entities].map((entity) => [
        entity.id,
        entity.cardId,
        [...entity.tags],
        entity.player,
      ]),
    })),
  };
}

describe('streamReplay', () => {
  it('emits document, game and packet events in order', async () => {
    const kinds: string[] = [];
    let packets = 0;
    for await (const event of streamReplay(chunksOf(XML, 7))) {
      kinds.push(event.kind);
      if (event.kind === 'packet') {
        expect(event.packet.index).toBe(packets);
        packets += event.packet.type === 'BLOCK' ? 1 + event.packet.children.length : 1;
      }
      if (event.kind === 'game-end') {
        expect(event.packetCount).toBe(packets);
        expect(event.diagnostics.map((d) => d.code)).toEqual([DiagnosticCode.UNKNOWN_NODE]);
      }
    }
    expect(kinds[0]).toBe('document');
    expect(kinds[1]).toBe('game-start');
    expect(kinds.filter((kind) => kind === 'packet')).toHaveLength(5);
    expect(kinds.slice(-2)).toEqual(['game-end', 'end']);
  });

  it('produces the same document as the in-memory parser, from strings or bytes', async () => {
    const expected = comparable(parseReplayDocument(XML));
    expect(comparable(await parseReplayStream([XML]))).toEqual(expected);
    expect(comparable(await parseReplayStream(chunksOf(XML, 1)))).toEqual(expected);
    const bytes = new TextEncoder().encode(XML);
    const byteChunks = [bytes.subarray(0, 100), bytes.subarray(100, 101), bytes.subarray(101)];
    expect(comparable(await parseReplayStream(byteChunks))).toEqual(expected);
  });

  it('decodes multi-byte characters split across byte chunks', async () => {
    const xml = wrapGame('<Player id="2" playerID="1" name="Игрок#1"/>');
    const bytes = new TextEncoder().encode(xml);
    const split = bytes.indexOf(0xd0) + 1; // inside the first Cyrillic character
    const document = await parseReplayStream([bytes.subarray(0, split), bytes.subarray(split)]);
    expect(document.games[0]?.metadata.players[0]?.name).toBe('Игрок#1');
  });

  it('handles several games, a bare Game root and foreign root children', async () => {
    const two = await parseReplayStream([
      '<HSReplay version="1.7"><Game id="1"><TagChange entity="1" tag="20" value="1"/></Game><Extra/><Game id="2"/></HSReplay>',
    ]);
    expect(two.games.map((game) => game.metadata.game.id)).toEqual([1, 2]);
    expect(two.games[0]?.packetCount).toBe(1);
    expect(two.diagnostics.map((d) => d.code)).toEqual([DiagnosticCode.UNKNOWN_NODE]);

    const bare = await parseReplayStream([
      '<Game id="7"><TagChange entity="1" tag="20" value="1"/></Game>',
    ]);
    expect(bare.games[0]?.metadata.game.id).toBe(7);
    expect(bare.diagnostics.map((d) => d.code)).toEqual([DiagnosticCode.UNEXPECTED_ROOT]);
  });

  it('propagates parse and strict-mode errors', async () => {
    await expect(parseReplayStream(['<HSReplay><Game>'])).rejects.toBeInstanceOf(ReplayParseError);
    await expect(parseReplayStream(['<Nope/>'])).rejects.toBeInstanceOf(ReplayValidationError);
    await expect(parseReplayStream([XML], { strict: true })).rejects.toBeInstanceOf(
      ReplayValidationError,
    );
  });
});
