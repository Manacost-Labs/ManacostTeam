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
      Mystery: {
        count: 1,
        files: ['a.xml'],
        fileCount: 1,
        firstFile: 'a.xml',
        firstPacketIndex: 3,
        sampleFile: 'a.xml',
        samplePacketIndex: 3,
        firstBuild: null,
        lastBuild: null,
      },
    });
    expect(report.attributes['TagChange.GameTagName']).toMatchObject({
      count: 2,
      files: ['a.xml', 'b.xml'],
      fileCount: 2,
      firstFile: 'a.xml',
      firstPacketIndex: 0,
    });
    expect(report.attributes['Mystery.a']?.count).toBe(1);
    expect(report.children['FullEntity>Odd']).toMatchObject({
      count: 1,
      files: ['a.xml'],
      firstPacketIndex: 4,
    });
    expect(report.tags['424242']).toMatchObject({
      count: 2,
      files: ['a.xml', 'b.xml'],
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

describe('analyzeUnknowns across a corpus', () => {
  it('reports file counts, build range and a sample packet for each unknown', () => {
    const a = parseReplay(
      wrapGame(
        '<TagChange entity="1" tag="424242" value="1"/><TagChange entity="1" tag="424242" value="2"/>',
      ),
    );
    const b = parseReplay(
      wrapGame('<Block entity="1" type="5"><TagChange entity="1" tag="424242" value="3"/></Block>'),
    );
    const c = parseReplay(wrapGame('<TagChange entity="1" tag="1" value="1"/>'));
    const report = analyzeUnknowns([
      { label: 'old.xml', build: 20000, packets: a.packets },
      { label: 'new.xml', build: 250339, packets: b.packets },
      { label: 'unknown-build.xml', packets: c.packets },
    ]);
    expect(report.tags['424242']).toEqual({
      count: 3,
      files: ['old.xml', 'new.xml'],
      fileCount: 2,
      firstFile: 'old.xml',
      firstPacketIndex: 0,
      sampleFile: 'new.xml',
      samplePacketIndex: 1,
      firstBuild: 20000,
      lastBuild: 250339,
    });
    expect(report.replayCount).toBe(3);
  });

  it('keeps builds null when no replay states one', () => {
    const replay = parseReplay(wrapGame('<Mystery/>'));
    const report = analyzeUnknowns([{ label: 'x', packets: replay.packets }]);
    expect(report.nodes.Mystery).toMatchObject({ fileCount: 1, firstBuild: null, lastBuild: null });
  });
});

describe('analyzeUnknowns sample selection', () => {
  it('points the sample at the first occurrence in the newest build', () => {
    const old = parseReplay(wrapGame('<TagChange entity="1" tag="424242" value="1"/>'));
    const fresh = parseReplay(
      wrapGame('<Block entity="1" type="5"><TagChange entity="1" tag="424242" value="3"/></Block>'),
    );
    const report = analyzeUnknowns([
      { label: 'old.xml', build: 20000, packets: old.packets },
      { label: 'new.xml', build: 250339, packets: fresh.packets },
    ]);
    expect(report.tags['424242']).toMatchObject({
      firstFile: 'old.xml',
      firstPacketIndex: 0,
      sampleFile: 'new.xml',
      samplePacketIndex: 1,
    });
  });
});
