import { describe, expect, it } from 'vitest';

import { DiagnosticCollector } from '../../src/diagnostics.js';
import { ReplayParseError } from '../../src/errors.js';
import { parseXml } from '../../src/parser/xml/parser.js';

function parse(xml: string, options?: Parameters<typeof parseXml>[2]) {
  const diagnostics = new DiagnosticCollector();
  const document = parseXml(xml, diagnostics, options);
  return { document, diagnostics };
}

describe('parseXml', () => {
  it('preserves sibling order and nesting', () => {
    const { document } = parse('<a><b x="1"/><c/><b x="2"><d/></b><c/></a>');
    expect(document.root.name).toBe('a');
    expect(document.root.children.map((child) => child.name)).toEqual(['b', 'c', 'b', 'c']);
    expect(document.root.children[2]!.attributes).toEqual({ x: '2' });
    expect(document.root.children[2]!.children[0]!.name).toBe('d');
  });

  it('tolerates prolog, doctype, comments and processing instructions', () => {
    const { document } = parse(
      `<?xml version="1.0"?><!DOCTYPE hsreplay SYSTEM "https://example.invalid/x.dtd"><!-- c --><a/><!-- trailing -->`,
    );
    expect(document.root.name).toBe('a');
    expect(document.hadDoctype).toBe(true);
  });

  it('records line and column positions', () => {
    const { document } = parse('<a>\n  <b/>\n</a>');
    expect(document.root.children[0]!.line).toBe(2);
  });

  it('expands only the predefined entities', () => {
    const { document } = parse('<a t="&lt;x&gt; &amp; &quot;y&quot; &apos;z&apos;"/>');
    expect(document.root.attributes.t).toBe(`<x> & "y" 'z'`);
  });

  it('does not honour entity declarations from the internal subset', () => {
    const xml = `<!DOCTYPE a [<!ENTITY lol "lollollol">]><a t="&lol;"/>`;
    expect(() => parse(xml)).toThrow(ReplayParseError);
  });

  it('throws ReplayParseError with position on malformed XML', () => {
    let error: unknown;
    try {
      parse('<a>\n  <b>\n</a>');
    } catch (caught) {
      error = caught;
    }
    expect(error).toBeInstanceOf(ReplayParseError);
    const parseError = error as ReplayParseError;
    expect(parseError.code).toBe('XML_SYNTAX');
    expect(parseError.context.line).toBeGreaterThan(0);
    expect(parseError.message).toMatch(/line \d+/);
  });

  it('rejects empty input and multiple roots', () => {
    expect(() => parse('')).toThrow(ReplayParseError);
    expect(() => parse('   ')).toThrow(ReplayParseError);
    expect(() => parse('<a/><b/>')).toThrow(ReplayParseError);
  });

  it('enforces the nesting depth limit', () => {
    const deep = `${'<a>'.repeat(10)}${'</a>'.repeat(10)}`;
    expect(() => parse(deep, { maxDepth: 5 })).toThrow(/XML_TOO_DEEP/);
    expect(() => parse(deep, { maxDepth: 10 })).not.toThrow();
  });

  it('enforces the element count limit', () => {
    expect(() => parse('<a><b/><b/><b/></a>', { maxElements: 3 })).toThrow(/XML_TOO_LARGE/);
  });

  it('reports non-whitespace text instead of failing', () => {
    const { document, diagnostics } = parse('<a>hello<b/></a>');
    expect(document.root.children).toHaveLength(1);
    expect(diagnostics.items).toEqual([
      expect.objectContaining({ level: 'info', code: 'UNEXPECTED_TEXT' }),
    ]);
  });
});
