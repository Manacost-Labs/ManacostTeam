# Replay corpus

`test/corpus/manifest.json` lists every real replay the tests run against,
with its origin, license, checksum and metadata read from the file itself.
Unknown values are `null`; nothing in the manifest is guessed.

## Contents

|                                        |                                                                                                                                                                                   |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Replays                                | 37 (36 from HearthSim plus the project's own `test.xml`)                                                                                                                          |
| HSReplay versions                      | 1.0, 1.3, 1.4, 1.5, 1.6, 1.7                                                                                                                                                      |
| Client builds                          | 10956, 14406, 14830, 15590, 18336, 18792, 19632, 20457, 23966, 24769, 25252, 25770, 27641, 37060, 39954, 45310, 88998, 175913, 195635, 250339 (16 files carry no build attribute) |
| Game modes (from `Game type`/`format`) | Standard ranked 8, Wild ranked 3, vs AI 3, casual 1, Tavern Brawl 1, Mercenaries 3, Battlegrounds 2, unknown (no `type` attribute) 16                                             |
| Sizes                                  | 12 KB – 2.3 MB, 24 MB in total                                                                                                                                                    |

Directories group files by what the `Game` element says (`standard/`,
`wild/`, `friendly/`, `tavern_brawl/`, `mercenaries/`), by absence of that
information (`legacy/`, mostly HSReplay 1.3–1.4 files without `type`) and by
what makes a file interesting for robustness (`edge/`).

## Sources and licenses

- **HearthSim/hsreplay-test-data**, commit
  `715d408e7047abdbde519313593f1be603916bec`, directory
  `hsreplaynet-tests/replays/`. Licensed **CC0-1.0**. These are the fixtures
  HSReplay.net itself tests against. Files whose name contains `annotated`
  carry extra human-readable attributes (`GameTagName`, `EntityCardName`, …)
  that the parser preserves as unknown attributes.
- **`test.xml`** – a Hearthstone Deck Tracker export provided by the project
  owner (ranked Standard, build 250339). Used as the golden fixture.

The joust sample replay was not included because its repository states no
license.

## Edge cases covered

| File                                  | Why it is there                                                                                  |
| ------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `hslog.xml`                           | HSReplay 1.0: UTF-8 BOM, `DOCTYPE … []`, legacy `<Action>` elements, `x-*` attributes on `Game`. |
| `no_block.annotated.xml`              | Reconnect log without a single `Block`; `Game reconnecting="true"`.                              |
| `annotated.truncated.27641.xml`       | Log cut before the game ended: no `GAME_ENDED`.                                                  |
| `annotated.missing_turns.27641.xml`   | Turn numbers out of order in the log itself (`TURN_NOT_MONOTONIC`).                              |
| `annotated.toki_game_reset.23966.xml` | Two `GAME_RESET` blocks re-creating entities and rewinding the turn.                             |
| `annotated.bounce.hsreplay.xml`       | `<Target>` entries without `entity` and with numeric error codes.                                |
| `anomalies.185749.annotated.xml`      | Anomaly entities in a constructed game, no `Game type`.                                          |
| `battlegrounds_*`                     | Minimal Battlegrounds logs (`GameType` 23) for format compatibility only.                        |

## Known gaps

- No Arena, Duels, Twist or full-length Battlegrounds replays.
- No replay from a client build newer than 250339.
- Only one non-English player name.
- 16 files do not state their game type; their mode is unknown, not guessed.
- Mercenaries and Battlegrounds semantic rules are untested beyond
  "nothing crashes and the invariants hold".

Until these gaps close, "works on the corpus" is the claim; "works with every
Hearthstone replay" is not.

## Reproducing and extending

```bash
pnpm corpus:verify        # checksums and a summary
pnpm test:corpus          # invariants on every entry
```

To add a replay: copy it under the matching directory, add a manifest entry
with `source`, `sourceRepository`, `sourceCommit`, `license`, the values
read from the file (`hsreplayVersion`, `build`, `gameType`, `formatType`),
`gameMode`, `annotated`, `notes`, `sizeBytes`, `sha256` and `knownAnomalies`.
`pnpm test:corpus` fails on any mismatch.

To see what a new build introduces:

```ts
import { analyzeUnknowns } from '@manacost/hearthstone-replay';
const report = analyzeUnknowns(replays); // unknown nodes, attributes, tags, enum values with counts and first occurrences
```
