import { SaxesParser, type SaxesTagPlain } from 'saxes';

import { type DiagnosticCollector, DiagnosticCode } from '../../diagnostics.js';
import { ReplayError, ReplayParseError } from '../../errors.js';
import { type XmlDocument, type XmlElement } from './nodes.js';

export interface XmlParseOptions {
  /** Maximum element nesting depth before the input is rejected. Defaults to 256. */
  readonly maxDepth?: number;
  /** Maximum number of elements before the input is rejected. Defaults to 50 million. */
  readonly maxElements?: number;
}

/**
 * Hooks that let a consumer observe elements as they are built and detach
 * finished subtrees so that a document never has to be held in memory whole.
 */
export interface XmlTreeHooks {
  /** Called when a start tag has been read; `depth` is 0 for the root. Children are not parsed yet. */
  onOpen?(element: XmlElement, depth: number): void;
  /**
   * Called when an element is complete. Return `false` to drop it from its
   * parent's children (the consumer has taken ownership), `true` to keep it.
   */
  onClose?(element: XmlElement, depth: number, parent: XmlElement | undefined): boolean;
}

const DEFAULT_MAX_DEPTH = 256;
const DEFAULT_MAX_ELEMENTS = 50_000_000;

interface MutableElement {
  readonly name: string;
  readonly attributes: Record<string, string>;
  readonly children: MutableElement[];
  readonly line: number;
  readonly column: number;
}

/**
 * Incremental XML reader producing an ordered element tree.
 *
 * Security properties:
 * - the DOCTYPE is never dereferenced, no network or file access happens;
 * - only the five predefined XML entities are expanded, custom entity
 *   declarations are not honoured (a reference to one is a parse error), so
 *   entity-expansion attacks are impossible;
 * - nesting depth and element count are bounded.
 */
export class XmlTreeBuilder {
  private readonly parser = new SaxesParser({ xmlns: false, position: true });
  private readonly stack: MutableElement[] = [];
  private readonly maxDepth: number;
  private readonly maxElements: number;
  private root: MutableElement | undefined;
  private elementCount = 0;
  private hadDoctype = false;
  private failure: ReplayParseError | undefined;
  private finished = false;

  constructor(
    private readonly diagnostics: DiagnosticCollector,
    options: XmlParseOptions = {},
    private readonly hooks: XmlTreeHooks = {},
  ) {
    this.maxDepth = options.maxDepth ?? DEFAULT_MAX_DEPTH;
    this.maxElements = options.maxElements ?? DEFAULT_MAX_ELEMENTS;

    const { parser } = this;
    parser.on('error', (error) => {
      this.fail('XML_SYNTAX', error.message);
    });
    parser.on('doctype', () => {
      this.hadDoctype = true;
    });
    parser.on('opentag', (tag: SaxesTagPlain) => {
      this.open(tag);
    });
    parser.on('closetag', () => {
      this.close();
    });
    parser.on('text', (text) => {
      if (text.trim().length === 0) return;
      this.diagnostics.info(
        DiagnosticCode.UNEXPECTED_TEXT,
        `ignored text content ${JSON.stringify(truncate(text.trim(), 40))}`,
        { line: parser.line, column: parser.column },
      );
    });
  }

  /** Feeds the next chunk of XML text. */
  write(chunk: string): this {
    this.guard(() => this.parser.write(chunk));
    return this;
  }

  /** Signals the end of input and returns the (possibly pruned) document. */
  end(): XmlDocument {
    if (this.finished) {
      throw new ReplayParseError(
        'XML_ALREADY_FINISHED',
        'the builder has already produced its document',
      );
    }
    this.finished = true;
    this.guard(() => this.parser.close());
    if (!this.root) {
      throw new ReplayParseError('XML_EMPTY', 'document contains no root element');
    }
    return { root: this.root, hadDoctype: this.hadDoctype };
  }

  private guard(action: () => void): void {
    try {
      action();
    } catch (error) {
      if (this.failure) throw this.failure;
      // Errors raised by hooks (validation, strict mode) pass through untouched.
      if (error instanceof ReplayError) throw error;
      throw new ReplayParseError('XML_SYNTAX', errorMessage(error), {
        context: { line: this.parser.line, column: this.parser.column },
        cause: error,
      });
    }
  }

  private fail(code: string, message: string): never {
    this.failure ??= new ReplayParseError(code, message, {
      context: { line: this.parser.line, column: this.parser.column },
    });
    throw this.failure;
  }

  private open(tag: SaxesTagPlain): void {
    const depth = this.stack.length;
    if (depth >= this.maxDepth) {
      this.fail('XML_TOO_DEEP', `element nesting exceeds the limit of ${String(this.maxDepth)}`);
    }
    if (++this.elementCount > this.maxElements) {
      this.fail('XML_TOO_LARGE', `element count exceeds the limit of ${String(this.maxElements)}`);
    }
    const element: MutableElement = {
      name: tag.name,
      attributes: tag.attributes,
      children: [],
      line: this.parser.line,
      column: this.parser.column,
    };
    if (depth === 0) {
      if (this.root)
        this.fail('XML_MULTIPLE_ROOTS', `unexpected second root element <${tag.name}>`);
      this.root = element;
    }
    this.stack.push(element);
    this.hooks.onOpen?.(element, depth);
  }

  private close(): void {
    const element = this.stack.pop();
    if (!element) return;
    const parent = this.stack[this.stack.length - 1];
    const keep = this.hooks.onClose?.(element, this.stack.length, parent) ?? true;
    if (keep && parent) parent.children.push(element);
  }
}

/** Parses a complete XML string into an ordered element tree. */
export function parseXml(
  xml: string,
  diagnostics: DiagnosticCollector,
  options: XmlParseOptions = {},
): XmlDocument {
  return new XmlTreeBuilder(diagnostics, options).write(xml).end();
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
