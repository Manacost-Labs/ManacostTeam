import { type DiagnosticCollector, DiagnosticCode } from '../../diagnostics.js';
import { type XmlElement } from '../xml/nodes.js';
import { type EntityRef, parseEntityRef } from './entity-ref.js';

/** Thrown internally when an element cannot be turned into its packet. Never leaves the packetizer. */
export class MalformedElementError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'MalformedElementError';
  }
}

const INTEGER = /^-?\d+$/;

/**
 * Typed access to the attributes of one element. Tracks which attributes were
 * read so that unrecognised ones can be preserved and reported.
 */
export class AttributeReader {
  private readonly consumed = new Set<string>();

  constructor(
    readonly element: XmlElement,
    private readonly diagnostics: DiagnosticCollector,
    private readonly packetIndex: number | undefined,
  ) {}

  has(name: string): boolean {
    return Object.hasOwn(this.element.attributes, name);
  }

  optionalString(name: string): string | undefined {
    this.consumed.add(name);
    return this.element.attributes[name];
  }

  string(name: string): string {
    const value = this.optionalString(name);
    if (value === undefined) throw this.missing(name);
    return value;
  }

  optionalInt(name: string): number | undefined {
    const raw = this.optionalString(name);
    if (raw === undefined) return undefined;
    const text = raw.trim();
    if (!INTEGER.test(text)) {
      throw new MalformedElementError(
        `attribute ${name}=${JSON.stringify(raw)} on <${this.element.name}> is not an integer`,
      );
    }
    const value = Number(text);
    if (!Number.isSafeInteger(value)) {
      this.diagnostics.warning(
        DiagnosticCode.UNSAFE_INTEGER,
        `attribute ${name}=${raw} on <${this.element.name}> exceeds the safe integer range`,
        this.context(),
      );
    }
    return value;
  }

  int(name: string): number {
    const value = this.optionalInt(name);
    if (value === undefined) throw this.missing(name);
    return value;
  }

  optionalBool(name: string): boolean | undefined {
    const raw = this.optionalString(name);
    if (raw === undefined) return undefined;
    const text = raw.trim().toLowerCase();
    if (text === 'true' || text === '1') return true;
    if (text === 'false' || text === '0') return false;
    throw new MalformedElementError(
      `attribute ${name}=${JSON.stringify(raw)} on <${this.element.name}> is not a boolean`,
    );
  }

  optionalEntity(name: string): EntityRef | undefined {
    const raw = this.optionalString(name);
    return raw === undefined ? undefined : parseEntityRef(raw);
  }

  entity(name: string): EntityRef {
    return parseEntityRef(this.string(name));
  }

  /**
   * Attributes that were never read. Reported once per element and returned
   * so the packet can keep them.
   */
  unknown(): Readonly<Record<string, string>> | undefined {
    let result: Record<string, string> | undefined;
    for (const [key, value] of Object.entries(this.element.attributes)) {
      if (this.consumed.has(key)) continue;
      result ??= {};
      result[key] = value;
    }
    if (result) {
      this.diagnostics.info(
        DiagnosticCode.UNKNOWN_ATTRIBUTE,
        `unknown attribute(s) on <${this.element.name}>: ${Object.keys(result).join(', ')}`,
        this.context(),
      );
    }
    return result;
  }

  context(): { packetIndex?: number; line: number; column: number } {
    const { line, column } = this.element;
    return this.packetIndex === undefined
      ? { line, column }
      : { packetIndex: this.packetIndex, line, column };
  }

  private missing(name: string): MalformedElementError {
    return new MalformedElementError(
      `required attribute "${name}" is missing on <${this.element.name}>`,
    );
  }
}
