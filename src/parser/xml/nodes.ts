/**
 * Minimal ordered XML element tree. This is the only representation the rest
 * of the library ever sees of the underlying XML; the SAX parser used to build
 * it is an implementation detail of `parser.ts`.
 *
 * Text content is intentionally not represented: HSReplay elements never carry
 * text, and stray text is reported as a diagnostic instead.
 */
export interface XmlElement {
  readonly name: string;
  readonly attributes: Readonly<Record<string, string>>;
  readonly children: readonly XmlElement[];
  /** 1-based line of the start tag, for diagnostics. */
  readonly line: number;
  /** 1-based column of the start tag, for diagnostics. */
  readonly column: number;
}

export interface XmlDocument {
  readonly root: XmlElement;
  /** Names of processing instructions, doctype and comments are dropped; only their presence is recorded. */
  readonly hadDoctype: boolean;
}
