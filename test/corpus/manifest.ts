import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export interface CorpusEntry {
  readonly file: string;
  readonly source: string;
  readonly sourceRepository: string | null;
  readonly sourceCommit: string | null;
  readonly license: string;
  readonly hsreplayVersion: string | null;
  readonly build: number | null;
  readonly gameType: number | null;
  readonly formatType: number | null;
  readonly gameMode: string | null;
  readonly annotated: boolean;
  readonly notes: string;
  /** Documented deviations from the usual invariants, e.g. `TURN_NOT_MONOTONIC`, `GAME_RESET`. */
  readonly knownAnomalies: readonly string[];
  /** Semantic event counts per type recorded on the current rules; a change here is a rule change. */
  readonly eventCounts: Readonly<Record<string, number>>;
  readonly sizeBytes: number;
  readonly sha256: string;
}

export interface CorpusManifest {
  readonly description: string;
  readonly entries: readonly CorpusEntry[];
}

export const MANIFEST_URL = new URL('./manifest.json', import.meta.url);

export function loadManifest(): CorpusManifest {
  return JSON.parse(readFileSync(MANIFEST_URL, 'utf8')) as CorpusManifest;
}

export function resolveCorpusPath(entry: CorpusEntry): string {
  return fileURLToPath(new URL(entry.file, MANIFEST_URL));
}

/** Reads every corpus replay as `{ label, xml }`, for scripts and tests that need them all. */
export function readCorpus(): { label: string; xml: string; entry: CorpusEntry }[] {
  return loadManifest().entries.map((entry) => ({
    label: entry.file,
    xml: readFileSync(resolveCorpusPath(entry), 'utf8'),
    entry,
  }));
}
