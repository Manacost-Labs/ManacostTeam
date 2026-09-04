# @manacost/hearthstone-replay

A lossless, strictly typed parser and observed-state engine for Hearthstone
[HSReplay](https://hearthsim.info/hsreplay/) XML files, written for
TypeScript / Node.js and usable in the browser.

The goal of the project is a reliable foundation for everything that comes
after: semantic events, statistics, replay viewers and data preparation for
AI/ML. Version 0.3 covers the first four layers of the pipeline:

```
XML  →  raw packets  →  entity store / game state  →  semantic events
                         (timeline, tag history)
```

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
state depends on it, and every event keeps the `packetIndex` it came from.

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
- Semantic events interpret patterns observed in current logs (see
  `docs/replay-format.md`). Mechanics the extractor does not know appear only
  as `ZONE_CHANGED` / `TRIGGERED` / raw packets, never as wrong events.
- `ATTACK.defender` relies on the DEFENDING tag; `DAMAGE.source` is the
  enclosing block's entity, which is the attacker or the effect source but not
  a full attribution chain.
- No Power.log support, no card database.

## Roadmap

- **v0.4** – statistics over events (tempo, resources, damage per turn), a
  viewer-oriented board model per turn, secrets and weapon events.
- **later** – Power.log parser sharing the packet layer, card database hooks,
  ML feature extraction.

## Development

```bash
pnpm install
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

`pnpm test:golden` regenerates `test/fixtures/test.expected.json` after an
intentional parser change.

Scripts invoke tools through `pnpm exec` on purpose: a project directory whose
name contains `:` (as in `@manacost:hearthstone-replay`) breaks the
`node_modules/.bin` `PATH` entry that plain `tsc` / `vitest` calls rely on.
