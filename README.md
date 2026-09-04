# @manacost/hearthstone-replay

A lossless, strictly typed parser and observed-state engine for Hearthstone
[HSReplay](https://hearthsim.info/hsreplay/) XML files, written for
TypeScript / Node.js and usable in the browser.

The goal of the project is a reliable foundation for everything that comes
after: semantic events, statistics, replay viewers and data preparation for
AI/ML. Version 0.5 covers the first four layers of the pipeline and validates them
against a corpus of 104 real replays:

```
XML  →  raw packets  →  entity store / game state  →  semantic events
        (observed)      (observed, accumulated)      (interpretation, with evidence)
                         timeline, tag history
```

Three kinds of truth, and the library never blurs them:

- **raw packets** are the most exact representation of the replay: every
  element, attribute and value, in document order, nothing interpreted;
- **state** is the observed state: the tags the log has set so far, no rules
  of the game applied;
- **semantic events** are interpretation: each one says which rule produced
  it and from which packets (`evidence`); every rule is checked against the
  invariants, rule tests and recorded event counts of the corpus, and rules
  with known counter-examples are not shipped.

See [docs/reliability.md](docs/reliability.md) for the exact guarantees of
each layer and [docs/replay-corpus.md](docs/replay-corpus.md) for what the
library has actually been validated on.

## Installation

```bash
pnpm add @manacost/hearthstone-replay
```

Requires Node.js 20+ (ESM only). The core entry point has no Node.js
dependencies; file-system helpers live under the `/node` subpath.

## Basic usage

```ts
import { parseReplayFile } from '@manacost/hearthstone-replay/node';

const replay = await parseReplayFile('./test.xml');

console.log(replay.packets.length); // top-level packets
console.log(replay.packetCount); // every packet, nested ones included
console.log([...replay.entities.values()]);
console.log(replay.diagnostics);
```

In a browser, or when the XML is already in memory:

```ts
import { parseReplay, flattenPackets, GameTag, Zone, getZone } from '@manacost/hearthstone-replay';

const replay = parseReplay(xmlString); // synchronous

for (const packet of flattenPackets(replay.packets)) {
  if (packet.type === 'TAG_CHANGE' && packet.tag === GameTag.ZONE && packet.value === Zone.PLAY) {
    console.log(`packet #${packet.index}: entity ${packet.entity.id} entered play`);
  }
}

for (const entity of replay.entities) {
  if (getZone(entity) === Zone.PLAY) console.log(entity.id, entity.cardId, entity.tags);
}
```

`parseReplay` accepts options:

```ts
parseReplay(xml, {
  strict: true, // throw ReplayValidationError on anything the lenient parser would only report
  maxDepth: 256, // XML nesting limit
});
```

## What you get

```ts
interface Replay {
  metadata: ReplayMetadata; // HSReplay version, client build, Game attributes, players
  packets: ReplayPacket[]; // top-level packets in document order; BLOCK / SUB_SPELL hold their children
  packetCount: number; // total packets including nested ones
  entities: EntityStore; // final observed state, Map-backed
  state: GameState; // entities + game / player entity ids
  diagnostics: ReplayDiagnostic[]; // { level, code, message, packetIndex?, line?, column? }
}
```

Packets are a discriminated union on `type`:

| Packet type                                    | XML element                                  | Notes                                                                                          |
| ---------------------------------------------- | -------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `GAME_ENTITY`                                  | `GameEntity`                                 | initial tags                                                                                   |
| `PLAYER`                                       | `Player`                                     | player number, name, account ids (strings), optional deck list                                 |
| `FULL_ENTITY`                                  | `FullEntity`                                 | creation of an entity, optional `cardId`                                                       |
| `SHOW_ENTITY`                                  | `ShowEntity`                                 | reveal of a hidden entity                                                                      |
| `CHANGE_ENTITY`                                | `ChangeEntity`                               | card id change                                                                                 |
| `HIDE_ENTITY`                                  | `HideEntity`                                 | entity hidden, target zone                                                                     |
| `TAG_CHANGE`                                   | `TagChange`                                  | `entity`, `tag`, `value`, optional `hasChangeDef`                                              |
| `BLOCK`                                        | `Block`                                      | container with `children`, `blockType`, `target`, `effectIndex`, `triggerKeyword`, `subOption` |
| `SUB_SPELL`                                    | `SubSpell`                                   | container with `targets` and `children`                                                        |
| `META_DATA`                                    | `MetaData`                                   | `meta`, `data`, `info[]`                                                                       |
| `CHOICES` / `CHOSEN_ENTITIES` / `SEND_CHOICES` | `Choices` / `ChosenEntities` / `SendChoices` | choice lists                                                                                   |
| `OPTIONS` / `SEND_OPTION`                      | `Options` / `SendOption`                     | option trees with sub-options and targets                                                      |
| `SHUFFLE_DECK`                                 | `ShuffleDeck`                                | player number                                                                                  |
| `UNKNOWN`                                      | anything else                                | element name, attributes and raw children preserved                                            |

Every packet has a sequential `index` in document order. Nothing is
interpreted at this level: tags stay numeric, timestamps stay strings, and
attributes the parser does not know are kept in `unknownAttributes`.

Entity references are a union, because the format allows non-numeric values:

```ts
type EntityRef = { kind: 'id'; id: number } | { kind: 'name'; name: string };
```

Tag ids get names through `GameTag`, `Zone`, `CardType` and
`createTagRegistry(extra)`. Enum value tables (`Step`, `PlayState`,
`GameEntityState`, `MulliganState`, `BlockType`, `MetaDataType`,
`ChoiceType`, `OptionType`, `GameType`, `FormatType`) and
`describeTagValue(tag, value)` name the numbers packets carry. Every table is
partial by design; unknown tags and values are never rejected.

## State over time

The final state is not the only one you can get. A timeline takes immutable
checkpoints at a fixed interval and reconstructs the state after any packet:

```ts
import { createTimeline, collectTagHistory, GameTag } from '@manacost/hearthstone-replay';

const timeline = createTimeline(replay, { checkpointInterval: 1000 });
const state = timeline.stateAt(4321); // fresh mutable GameState after packet #4321
console.log(state.turn, state.step, state.currentPlayer?.player?.name);

const history = collectTagHistory(replay.packets, {
  entities: new Set([1]),
  tags: new Set([GameTag.TURN]),
});
for (const { packetIndex, value } of history.get(1)!.get(GameTag.TURN)!) {
  console.log(`turn ${value} starts at packet #${packetIndex}`);
}
```

`snapshotState(state, packetIndex)` and `restoreState(snapshot)` are the
primitives underneath, usable on their own.

## Semantic events

`extractEvents` replays the packets through the state engine and reports what
happened in game terms. It is a separate layer: nothing in the packets or the
state depends on it, and every event keeps the `packetIndex` it came from
plus an `evidence` record saying how it was inferred:

```ts
const events = extractEvents(replay);

for (const event of events) {
  console.log(event.type, event.evidence.level, event.evidence.rule, event.evidence.packetIndices);
}
// CARD_DRAWN derived CARD_DRAWN [ 521 ]
// DAMAGE derived DAMAGE_SOURCE [ 704, 706 ]   ← MetaData packet + LAST_AFFECTED_BY tag change
// ZONE_CHANGED observed ZONE_CHANGED [ 521 ]
```

`evidence.level` is `observed` (the event restates one packet), `derived`
(a rule combined the packet with known state) or `heuristic` (reserved for
rules with known counter-examples; none ship today). The rules themselves
are listed in `SEMANTIC_RULES` with their source and caveats.

```ts
import { extractEvents, SemanticEventType } from '@manacost/hearthstone-replay';

for (const event of extractEvents(replay)) {
  switch (event.type) {
    case SemanticEventType.CARD_PLAYED:
      console.log(`turn ${event.turn}: player ${event.playerEntityId} played ${event.cardId}`);
      break;
    case SemanticEventType.ATTACK:
      console.log(`${event.entity} attacks ${event.defender ?? event.target}`);
      break;
    case SemanticEventType.DAMAGE:
      console.log(`${event.amount} damage to ${event.target.id} from ${event.source}`);
      break;
  }
}
```

| Event                                                                        | Derived from                                     |
| ---------------------------------------------------------------------------- | ------------------------------------------------ |
| `GAME_STARTED`, `GAME_ENDED` (winners, losers)                               | `GameEntity`; game STATE → COMPLETE              |
| `TURN_STARTED` (turn, current player)                                        | TURN tag change on the game entity               |
| `CHOICE_OFFERED`, `CHOICE_MADE` (mulligan, discover)                         | `Choices`, `ChosenEntities`                      |
| `OPTION_CHOSEN` (the command a player sent)                                  | `SendOption` resolved against the last `Options` |
| `CARD_PLAYED`, `HERO_POWER_USED`                                             | `Block` of type PLAY, card type after the block  |
| `ATTACK` (target, and the defender after redirects)                          | `Block` of type ATTACK, DEFENDING tag            |
| `ZONE_CHANGED`, `CARD_DRAWN` (deck → hand), `ENTITY_DIED` (play → graveyard) | ZONE tag changes, `HideEntity`, reveals          |
| `DAMAGE`, `HEALING` (amount, target, source)                                 | `MetaData` DAMAGE / HEALING                      |
| `TRIGGERED` (trigger keyword)                                                | `Block` of type TRIGGER with `triggerKeyword`    |
| `FATIGUE`, `CONCEDED`                                                        | `Block` of type FATIGUE; PLAYSTATE → CONCEDED    |

Pass `{ types: new Set([SemanticEventType.CARD_PLAYED]) }` to keep only some
event types.

## Corpus, telemetry and validation

Validated against 104 real replay fixtures (CC0 and MIT sources, see
[docs/replay-corpus.md](docs/replay-corpus.md)) spanning HSReplay 1.0–1.7,
30 client builds from 10956 to 250339 and Standard, Wild, Classic,
Battlegrounds, Mercenaries, Tavern Brawl, Puzzle Lab and friendly games.
That is the claim; "works with every Hearthstone replay" is not, and Arena,
Twist and Duels are not covered yet. Every fixture is checked for parser and
state invariants and for its recorded semantic event counts; property-based
tests (fast-check) cover parser roundtrips, random streaming chunkings of
synthetic and real files, snapshot isolation and timeline reconstruction;
mutation tests feed the parser malformed and hostile XML; a weekly
differential run compares the raw and state layers with python-hsreplay
(94 matches, 0 divergences on the current corpus). After a Hearthstone patch:

```ts
import { analyzeUnknowns } from '@manacost/hearthstone-replay';

const report = analyzeUnknowns(replays);
console.log(report.tags, report.enumValues, report.nodes, report.attributes);
// { '2175': { count: 37, fileCount: 3, firstBuild: 195635, lastBuild: 250339, firstFile: '…', samplePacketIndex: 812, … }, … }
```

`pnpm corpus:unknowns` diffs the corpus against a recorded baseline and
`pnpm corpus:report` regenerates [docs/generated/corpus-report.md](docs/generated/corpus-report.md)
with per-rule coverage. API guarantees per export are listed in
[docs/api-stability.md](docs/api-stability.md).

## Streaming

```ts
import { parseReplayStream, streamReplay } from '@manacost/hearthstone-replay';
import { parseReplayFileStream } from '@manacost/hearthstone-replay/node';

const replay = await parseReplayFileStream('./huge.xml'); // same result as parseReplayFile

for await (const event of streamReplay(chunks)) {
  // 'document' | 'game-start' | 'packet' | 'game-end' | 'end'
  if (event.kind === 'packet') handle(event.packet);
}
```

`streamReplay` accepts any sync or async iterable of strings or bytes. Each
top-level packet is emitted as soon as its element closes and then released,
so memory depends on the largest single packet, not on the file.

## Documents with several games

```ts
import { parseReplayDocument } from '@manacost/hearthstone-replay';

const document = parseReplayDocument(xml);
for (const game of document.games) console.log(game.metadata.game.id, game.packetCount);
```

`parseReplay` returns the first game and adds a `MULTIPLE_GAMES` diagnostic
when there are more.

## Architecture overview

See [docs/architecture.md](docs/architecture.md) for the full picture and
[docs/replay-format.md](docs/replay-format.md) for what the real fixture
contains.

```
src/
  parser/xml/        XML string → ordered element tree (saxes, hardened)
  parser/packets/    element tree → typed raw packets with indexes
  tags/              GameTag / Zone / CardType names, extensible registry
  state/             Entity, EntityStore, state engine (applyPacket)
  parse-replay.ts    orchestration and the public parseReplay()
  node.ts            parseReplayFile() for Node.js
```

## Security

Replay files are untrusted input. The parser never dereferences the
`DOCTYPE`, expands only the five predefined XML entities, rejects references
to declared entities, bounds nesting depth and element count, and reports
rather than crashes on missing attributes, unexpected elements and oversized
integers.

## Current limitations

- Name-based entity references resolve only through exact player names;
  `UNKNOWN HUMAN PLAYER` is reported and skipped.
- The state engine records observed state only. It applies entity
  definitions, reveals, hides, card-id changes and tag changes. It does not
  simulate rules.
- `GameTag` names and enum tables cover a fundamental subset; everything else
  is numeric (`BlockType` 13 and `MetaDataType` 20/24 seen in current logs are
  not named yet).
- Semantic rules are validated on the corpus described in
  `docs/replay-corpus.md`: constructed games from 2016 to 2026, three
  Mercenaries logs and two tiny Battlegrounds logs. Battlegrounds combat,
  Duels and Arena are not covered. Mechanics the extractor does not know
  appear only as `ZONE_CHANGED` / `TRIGGERED` / raw packets rather than as
  guessed events; whether a rule fires wrongly on a mechanic outside the
  corpus cannot be excluded.
- `DAMAGE.source` exists only when the log recorded LAST_AFFECTED_BY for the
  target before its next hit (about seven damage events out of eight in the
  corpus; absorbed hits never carry it); `blockEntity` is context.
- No Power.log support, no card database.

## Roadmap

- **v0.6** – Arena / Twist / recent-build fixtures as they become available,
  location and secret events once the corpus proves them, statistics over
  events (tempo, resources, damage per turn), a viewer-oriented board model.
- **later** – Power.log parser sharing the packet layer, card database hooks,
  ML feature extraction.

## Development

```bash
pnpm install
pnpm typecheck
pnpm lint
pnpm test            # unit, integration, golden, property, corpus
pnpm test:coverage   # with thresholds
pnpm build
pnpm pack:smoke      # tarball contents, Node import, TypeScript consumer, browser bundle of the core entry
pnpm benchmark       # one replay; pnpm benchmark:corpus for the whole corpus (baselines, not gates)
pnpm corpus:verify && pnpm corpus:report && pnpm corpus:unknowns
PYTHON=.venv/bin/python pnpm differential   # see docs/differential-testing.md
```

`pnpm test:golden` regenerates `test/fixtures/test.expected.json` after an
intentional parser change.

Scripts invoke tools as `node node_modules/<tool>/…` on purpose: a project
directory whose name contains `:` (as in `@manacost:hearthstone-replay`)
breaks the `node_modules/.bin` `PATH` entry that plain `tsc` / `vitest`
calls rely on, and `pnpm exec` behaves differently across pnpm majors.
