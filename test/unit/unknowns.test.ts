import { describe, expect, it } from 'vitest';

import { analyzeUnknowns, parseReplay } from '../../src/index.js';
import { wrapGame } from '../helpers.js';

describe('analyzeUnknowns', () => {
  it('counts unknown nodes, attributes, children, tags and enum values with first occurrences', () => {
    const first = parseReplay(
      wrapGame(`<TagChange entity="1" tag="49" value="99" GameTagName="ZONE"/>
        <TagChange entity="1" tag="424242" value="1"/>
        <Block entity="1" type="77"><Mystery a="1"/></Block>
        <FullEntity id="5"><Odd/></FullEntity>
        <MetaData meta="500" data="0"/>`),
    );
    const second = parseReplay(
      wrapGame('<TagChange entity="1" tag="424242" value="2" GameTagName="X"/>'),
    );
    const report = analyzeUnknowns([
      { label: 'a.xml', packets: first.packets },
      { label: 'b.xml', packets: second.packets },
    ]);
    expect(report.replayCount).toBe(2);
    expect(report.nodes).toEqual({
      Mystery: { count: 1, files: ['a.xml'], firstFile: 'a.xml', firstPacketIndex: 3 },
    });
    expect(report.attributes['TagChange.GameTagName']).toEqual({
      count: 2,
      files: ['a.xml', 'b.xml'],
      firstFile: 'a.xml',
      firstPacketIndex: 0,
    });
    expect(report.attributes['Mystery.a']?.count).toBe(1);
    expect(report.children).toEqual({
      'FullEntity>Odd': { count: 1, files: ['a.xml'], firstFile: 'a.xml', firstPacketIndex: 4 },
    });
    expect(report.tags['424242']).toEqual({
      count: 2,
      files: ['a.xml', 'b.xml'],
      firstFile: 'a.xml',
      firstPacketIndex: 1,
    });
    expect(Object.keys(report.enumValues).sort()).toEqual([
      'BlockType.77',
      'MetaDataType.500',
      'Zone.99',
    ]);
  });

  it('reports nothing unknown for a fully known replay', () => {
    const replay = parseReplay(
      wrapGame('<TagChange entity="1" tag="49" value="1"/><Block entity="1" type="5"/>'),
    );
    const report = analyzeUnknowns([replay]);
    expect(report).toEqual({
      nodes: {},
      attributes: {},
      children: {},
      tags: {},
      enumValues: {},
      replayCount: 1,
    });
  });
});
