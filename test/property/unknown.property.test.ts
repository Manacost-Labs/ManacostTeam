import fc from 'fast-check';
import { describe, expect, it } from 'vitest';

import './setup.js';
import { analyzeUnknowns, flattenPackets, parseReplayDocument } from '../../src/index.js';
import { escapeAttribute, gameXml, modelGame } from './arbitraries.js';

const NAME = fc.stringMatching(/^[A-Za-z_][A-Za-z0-9_.-]{0,12}$/);
// XML 1.0 forbids control characters in attribute values; lone surrogates cannot be encoded as UTF-8.
// eslint-disable-next-line no-control-regex
const CONTROL_OR_SURROGATE = /[\u0000-\u001f\ud800-\udfff]/;
const VALUE = fc
  .string({ maxLength: 20, unit: 'grapheme' })
  .filter((v) => !CONTROL_OR_SURROGATE.test(v));
const KNOWN_ATTRIBUTES = new Set([
  'entity',
  'tag',
  'value',
  'id',
  'type',
  'target',
  'ts',
  'cardID',
  'zone',
  'hasChangeDef',
]);
const KNOWN_ELEMENTS =
  /^(TagChange|Block|FullEntity|ShowEntity|HideEntity|MetaData|SubSpell|Player|GameEntity|Options|SendOption|Choices|ChosenEntities|SendChoices|ShuffleDeck|ChangeEntity|Action|ResetGame|VOSpell|CachedTagForDormantChange)$/;

const unknownAttributes = fc.dictionary(
  NAME.filter((n) => !KNOWN_ATTRIBUTES.has(n)),
  VALUE,
  { minKeys: 1, maxKeys: 3 },
);
const unknownNode = fc.record({
  name: NAME.filter((n) => !KNOWN_ELEMENTS.test(n)),
  attributes: unknownAttributes,
});

function attributesXml(attributes: Record<string, string>): string {
  return Object.entries(attributes)
    .map(([key, value]) => ` ${key}="${escapeAttribute(value)}"`)
    .join('');
}

describe('unknown preservation properties', () => {
  it('keeps every unknown attribute and unknown element verbatim, with matching telemetry (roundtrip)', () => {
    fc.assert(
      fc.property(modelGame, unknownAttributes, unknownNode, (game, attributes, node) => {
        const extra = `<TagChange entity="1" tag="1" value="1"${attributesXml(attributes)}/><${node.name}${attributesXml(node.attributes)}><Inner/></${node.name}>`;
        const replay = parseReplayDocument(gameXml(game, extra)).games[0]!;
        const packets = replay.packets;
        const tagChange = packets[packets.length - 2]!;
        const unknown = packets[packets.length - 1]!;
        expect(tagChange.type).toBe('TAG_CHANGE');
        expect(tagChange.unknownAttributes).toEqual(attributes);
        expect(unknown.type).toBe('UNKNOWN');
        if (unknown.type === 'UNKNOWN') {
          expect(unknown.name).toBe(node.name);
          expect({ ...unknown.attributes }).toEqual(node.attributes);
          expect(unknown.children.map((child) => child.name)).toEqual(['Inner']);
        }
        const report = analyzeUnknowns([{ label: 'x', packets }]);
        expect(report.nodes[node.name]?.count).toBe(1);
        for (const key of Object.keys(attributes))
          expect(report.attributes[`TagChange.${key}`]?.count).toBeGreaterThanOrEqual(1);
        expect(flattenPackets(packets).map((p) => p.index)).toEqual(
          flattenPackets(packets).map((_, i) => i),
        );
      }),
      { numRuns: 60 },
    );
  });
});
