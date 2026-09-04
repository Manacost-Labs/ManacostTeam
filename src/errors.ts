/**
 * Context attached to every error raised by the library. All fields are
 * optional because different stages know different things: the XML layer
 * knows lines, the packet layer knows packet indexes.
 */
export interface ReplayErrorContext {
  readonly packetIndex?: number;
  readonly line?: number;
  readonly column?: number;
  readonly element?: string;
}

export interface ReplayErrorOptions {
  readonly context?: ReplayErrorContext;
  readonly cause?: unknown;
}

function formatContext(context: ReplayErrorContext): string {
  const parts: string[] = [];
  if (context.element !== undefined) parts.push(`element <${context.element}>`);
  if (context.packetIndex !== undefined) parts.push(`packet #${String(context.packetIndex)}`);
  if (context.line !== undefined) {
    const column = context.column !== undefined ? `:${String(context.column)}` : '';
    parts.push(`line ${String(context.line)}${column}`);
  }
  return parts.length > 0 ? ` (${parts.join(', ')})` : '';
}

/** Base class of every error thrown by `@manacost/hearthstone-replay`. */
export class ReplayError extends Error {
  readonly code: string;
  readonly context: ReplayErrorContext;

  constructor(code: string, message: string, options: ReplayErrorOptions = {}) {
    const context = options.context ?? {};
    super(`${code}: ${message}${formatContext(context)}`, { cause: options.cause });
    this.name = new.target.name;
    this.code = code;
    this.context = context;
  }
}

/** The input could not be read as XML / HSReplay at all. */
export class ReplayParseError extends ReplayError {}

/** The XML was well-formed but its content violates the HSReplay format. */
export class ReplayValidationError extends ReplayError {}
