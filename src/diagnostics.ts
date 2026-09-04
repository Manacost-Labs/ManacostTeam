import { ReplayValidationError } from './errors.js';

export type DiagnosticLevel = 'info' | 'warning' | 'error';

/** Stable machine-readable diagnostic codes emitted by the parser and state engine. */
export const DiagnosticCode = {
  /** An element in packet position that the parser does not know. */
  UNKNOWN_NODE: 'UNKNOWN_NODE',
  /** An attribute the parser does not know on a known element. Preserved in `unknownAttributes`. */
  UNKNOWN_ATTRIBUTE: 'UNKNOWN_ATTRIBUTE',
  /** A child element the parser did not expect under a payload element. Preserved in `unknownChildren`. */
  UNEXPECTED_CHILD: 'UNEXPECTED_CHILD',
  /** A required attribute is missing or has an invalid value; the element became an UnknownPacket. */
  MALFORMED_PACKET: 'MALFORMED_PACKET',
  /** An integer attribute is outside the safe integer range and lost precision. */
  UNSAFE_INTEGER: 'UNSAFE_INTEGER',
  /** Non-whitespace text content was found and ignored. */
  UNEXPECTED_TEXT: 'UNEXPECTED_TEXT',
  /** The root element is not `HSReplay`. */
  UNEXPECTED_ROOT: 'UNEXPECTED_ROOT',
  /** More than one `Game` element; only the first is parsed. */
  MULTIPLE_GAMES: 'MULTIPLE_GAMES',
  /** An entity reference is a name rather than an id and could not be resolved. */
  UNRESOLVED_ENTITY_REF: 'UNRESOLVED_ENTITY_REF',
  /** A packet refers to an entity id that was never created; a placeholder entity was created. */
  UNKNOWN_ENTITY: 'UNKNOWN_ENTITY',
  /** A FullEntity re-created an entity id that already exists; its tags were replaced. */
  ENTITY_RECREATED: 'ENTITY_RECREATED',
  /** The same tag appears twice in one entity definition; the last value wins. */
  DUPLICATE_TAG: 'DUPLICATE_TAG',
} as const;

export type DiagnosticCode = (typeof DiagnosticCode)[keyof typeof DiagnosticCode];

export interface ReplayDiagnostic {
  readonly level: DiagnosticLevel;
  readonly code: DiagnosticCode;
  readonly message: string;
  readonly packetIndex?: number;
  readonly line?: number;
  readonly column?: number;
}

export interface DiagnosticContext {
  readonly packetIndex?: number;
  readonly line?: number;
  readonly column?: number;
}

/**
 * Collects diagnostics for one parse. In strict mode every `error` and every
 * `violation` is turned into a thrown `ReplayValidationError`.
 */
export class DiagnosticCollector {
  readonly items: ReplayDiagnostic[] = [];
  readonly strict: boolean;

  constructor(strict = false) {
    this.strict = strict;
  }

  info(code: DiagnosticCode, message: string, context: DiagnosticContext = {}): void {
    this.push('info', code, message, context);
  }

  warning(code: DiagnosticCode, message: string, context: DiagnosticContext = {}): void {
    this.push('warning', code, message, context);
  }

  /** Always recorded as an error; throws in strict mode. */
  error(code: DiagnosticCode, message: string, context: DiagnosticContext = {}): void {
    this.push('error', code, message, context);
    if (this.strict) throw new ReplayValidationError(code, message, { context });
  }

  /**
   * Something the lenient parser tolerates but that strict mode must reject:
   * a warning by default, a thrown error in strict mode.
   */
  violation(code: DiagnosticCode, message: string, context: DiagnosticContext = {}): void {
    if (this.strict) {
      this.push('error', code, message, context);
      throw new ReplayValidationError(code, message, { context });
    }
    this.push('warning', code, message, context);
  }

  private push(
    level: DiagnosticLevel,
    code: DiagnosticCode,
    message: string,
    context: DiagnosticContext,
  ): void {
    const item: {
      level: DiagnosticLevel;
      code: DiagnosticCode;
      message: string;
      packetIndex?: number;
      line?: number;
      column?: number;
    } = { level, code, message };
    if (context.packetIndex !== undefined) item.packetIndex = context.packetIndex;
    if (context.line !== undefined) item.line = context.line;
    if (context.column !== undefined) item.column = context.column;
    this.items.push(item);
  }
}
