import { createReadStream } from 'node:fs';
import { readFile } from 'node:fs/promises';

import { firstGame, parseReplay, parseReplayDocument } from './parse-replay.js';
import { parseReplayStream } from './parser/stream.js';
import { type ParseReplayOptions, type Replay, type ReplayDocument } from './replay.js';

export * from './index.js';

/** Reads an HSReplay XML file from disk and parses its first game. Node.js only. */
export async function parseReplayFile(
  path: string | URL,
  options: ParseReplayOptions = {},
): Promise<Replay> {
  const xml = await readFile(path, 'utf8');
  return parseReplay(xml, options);
}

/** Reads an HSReplay XML file from disk and parses every game in it. Node.js only. */
export async function parseReplayDocumentFile(
  path: string | URL,
  options: ParseReplayOptions = {},
): Promise<ReplayDocument> {
  const xml = await readFile(path, 'utf8');
  return parseReplayDocument(xml, options);
}

/**
 * Streams an HSReplay XML file from disk through `parseReplayStream`, so the
 * whole file is never held in memory. Node.js only.
 */
export async function parseReplayDocumentFileStream(
  path: string | URL,
  options: ParseReplayOptions = {},
): Promise<ReplayDocument> {
  return parseReplayStream(createReadStream(path), options);
}

/** Streaming counterpart of `parseReplayFile`: first game of the file. Node.js only. */
export async function parseReplayFileStream(
  path: string | URL,
  options: ParseReplayOptions = {},
): Promise<Replay> {
  return firstGame(await parseReplayDocumentFileStream(path, options), options);
}
