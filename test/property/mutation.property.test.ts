import fc from 'fast-check';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import './setup.js';
import {
  DiagnosticCode,
  flattenPackets,
  isStrictViolation,
  parseReplayDocument,
  type ReplayDocument,
  ReplayError,
  ReplayParseError,
  ReplayValidationError,
} from '../../src/index.js';
import { DOCTYPE, gameXml, type ModelGame, modelGame } from './arbitraries.js';

/** A mutation of a valid document and what the parser must do with it. */
interface Mutation {
  readonly name: string;
  readonly apply: (game: ModelGame) => string;
  /** Lenient mode must succeed and report every one of these codes. */
  readonly reports?: readonly DiagnosticCode[];
  /** Both modes must throw this error class (the input is not a document at all). */
  readonly throws?: typeof ReplayParseError | typeof ReplayValidationError;
  /** Extra top-level packets the mutation adds. */
  readonly extraPackets?: number;
}

const mutations: Mutation[] = [
  {
    name: 'unknown node in packet position',
    apply: (game) => gameXml(game, '<FutureNode a="1"><Inner/></FutureNode>'),
    reports: [DiagnosticCode.UNKNOWN_NODE],
    extraPackets: 1,
  },
  {
    name: 'unknown attribute on a known element',
    apply: (game) => gameXml(game, '<TagChange entity="1" tag="1" value="1" future="x"/>'),
    reports: [DiagnosticCode.UNKNOWN_ATTRIBUTE],
    extraPackets: 1,
  },
  {
    name: 'missing optional attributes',
    apply: (game) =>
      gameXml(game, '<Block entity="1" type="5"/><SendOption option="0"/><MetaData meta="1"/>'),
    extraPackets: 3,
  },
  {
    name: 'missing required attribute',
    apply: (game) => gameXml(game, '<TagChange entity="1" value="1"/>'),
    reports: [DiagnosticCode.MALFORMED_PACKET],
    extraPackets: 1,
  },
  {
    name: 'very large integer',
    apply: (game) =>
      gameXml(game, '<TagChange entity="1" tag="1" value="99999999999999999999999"/>'),
    reports: [DiagnosticCode.UNSAFE_INTEGER],
    extraPackets: 1,
  },
  {
    name: 'negative integers',
    apply: (game) =>
      gameXml(game, '<TagChange entity="1" tag="1" value="-5"/><HideEntity entity="1" zone="-1"/>'),
    extraPackets: 2,
  },
  {
    name: 'non-numeric entity reference',
    apply: (game) => gameXml(game, '<TagChange entity="UNKNOWN HUMAN PLAYER" tag="1" value="1"/>'),
    reports: [DiagnosticCode.UNRESOLVED_ENTITY_REF],
    extraPackets: 1,
  },
  {
    name: 'unknown GameTag and BlockType',
    apply: (game) =>
      gameXml(game, '<TagChange entity="1" tag="999999" value="1"/><Block entity="1" type="999"/>'),
    extraPackets: 2,
  },
  {
    name: 'empty block',
    apply: (game) => gameXml(game, '<Block entity="1" type="5"></Block>'),
    extraPackets: 1,
  },
  {
    name: 'unexpected child of a payload element',
    apply: (game) =>
      gameXml(game, '<FullEntity id="9"><Tag tag="1" value="1"/><Weird/></FullEntity>'),
    reports: [DiagnosticCode.UNEXPECTED_CHILD],
    extraPackets: 1,
  },
  {
    name: 'deep nesting within the limit',
    apply: (game) =>
      gameXml(game, `${'<Block entity="1" type="5">'.repeat(200)}${'</Block>'.repeat(200)}`),
    extraPackets: 1,
  },
  {
    name: 'nesting beyond the limit',
    apply: (game) =>
      gameXml(game, `${'<Block entity="1" type="5">'.repeat(300)}${'</Block>'.repeat(300)}`),
    throws: ReplayParseError,
  },
  {
    name: 'multiple Game elements',
    apply: (game) => gameXml(game).replace('</HSReplay>', '<Game id="2"/></HSReplay>'),
  },
  {
    name: 'bare Game root',
    apply: (game) =>
      gameXml(game)
        .replace(/<HSReplay[^>]*>/, '')
        .replace('</HSReplay>', ''),
    reports: [DiagnosticCode.UNEXPECTED_ROOT],
  },
  {
    name: 'malformed closing tag',
    apply: (game) => gameXml(game).replace('</Game>', '</Gaem>'),
    throws: ReplayParseError,
  },
  {
    name: 'truncated document',
    apply: (game) => gameXml(game).slice(0, -12),
    throws: ReplayParseError,
  },
  {
    name: 'custom entities declared in the internal subset but unused',
    apply: (game) =>
      gameXml(game).replace(
        DOCTYPE,
        '<!DOCTYPE hsreplay [<!ENTITY lol "lollollol"><!ENTITY lol2 "&lol;&lol;">]>',
      ),
  },
  {
    name: 'reference to a declared entity (expansion attempt)',
    apply: (game) =>
      gameXml(game)
        .replace(DOCTYPE, '<!DOCTYPE hsreplay [<!ENTITY lol "lollollol">]>')
        .replace('<Game ', '<Game x="&lol;" '),
    throws: ReplayParseError,
  },
  {
    name: 'external entity attempt',
    apply: (game) =>
      gameXml(game)
        .replace(DOCTYPE, '<!DOCTYPE hsreplay [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>')
        .replace('<Game ', '<Game x="&xxe;" '),
    throws: ReplayParseError,
  },
  {
    name: 'text content between packets',
    apply: (game) => gameXml(game, 'stray text'),
    reports: [DiagnosticCode.UNEXPECTED_TEXT],
  },
  {
    name: 'UTF-8 byte order mark and CRLF line endings',
    apply: (game) => `\uFEFF${gameXml(game).replace(/\n/g, '\r\n')}`,
  },
];

const originalFetch = globalThis.fetch;

describe('mutation properties', () => {
  beforeAll(() => {
    globalThis.fetch = () => {
      throw new Error('the parser must never perform network requests');
    };
  });
  afterAll(() => {
    globalThis.fetch = originalFetch;
  });

  it.each(mutations.map((mutation) => [mutation.name, mutation] as const))(
    '%s: no crash, no silent loss, strict mode agrees with the diagnostics',
    (_name, mutation) => {
      fc.assert(
        fc.property(modelGame, (game) => {
          const xml = mutation.apply(game);
          const baseline = parseReplayDocument(gameXml(game)).games[0]!;

          if (mutation.throws) {
            expect(() => parseReplayDocument(xml)).toThrow(mutation.throws);
            expect(() => parseReplayDocument(xml, { strict: true })).toThrow(mutation.throws);
            return;
          }

          let lenient: ReplayDocument;
          try {
            lenient = parseReplayDocument(xml);
          } catch (error) {
            expect(error).toBeInstanceOf(ReplayError);
            throw error;
          }
          const game0 = lenient.games[0]!;
          const codes = new Set([...lenient.diagnostics, ...game0.diagnostics].map((d) => d.code));
          for (const code of mutation.reports ?? []) expect(codes.has(code)).toBe(true);

          // The untouched part of the document is parsed exactly as before.
          expect(game0.packets.slice(0, baseline.packets.length)).toEqual(baseline.packets);
          expect(game0.packets).toHaveLength(
            baseline.packets.length + (mutation.extraPackets ?? 0),
          );
          const flat = flattenPackets(game0.packets);
          expect(flat.map((packet) => packet.index)).toEqual(flat.map((_, position) => position));

          // Strict mode throws exactly when lenient mode recorded a strict violation.
          const violated = [
            ...lenient.diagnostics,
            ...lenient.games.flatMap((g) => g.diagnostics),
          ].some(isStrictViolation);
          if (violated) {
            expect(() => parseReplayDocument(xml, { strict: true })).toThrow(ReplayValidationError);
          } else {
            expect(parseReplayDocument(xml, { strict: true }).games[0]!.packets).toEqual(
              game0.packets,
            );
          }
        }),
        { numRuns: 25 },
      );
    },
  );
});
