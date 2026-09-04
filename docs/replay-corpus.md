# Replay corpus

`test/corpus/manifest.json` lists every real replay the tests run against,
with its origin, license, checksum, metadata read from the file itself,
features confirmed from its packets and the semantic event counts recorded
on the current rules. Unknown values are `null`; nothing in the manifest is
guessed from a file name. The machine-generated
[corpus report](generated/corpus-report.md) has the exact numbers, the
per-rule coverage and every unknown tag, attribute and enum value.

## Contents (v0.5)

|                                        |                                                                                                                                                   |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Replays                                | 104 files, 107 games, 81.7 MB (from 37 files / 24 MB in v0.4)                                                                                     |
| HSReplay versions                      | 1.0 (1), 1.3 (16), 1.4 (17), 1.5 (3), 1.6 (7), 1.7 (60)                                                                                           |
| Client builds                          | 30 distinct builds from 10956 (2016) to 250339 (2026); 25 files carry no build attribute                                                          |
| Game modes (from `Game type`/`format`) | Standard 15, Wild 4, Classic 3, Battlegrounds 14, Mercenaries 3, vs AI 3, vs friend 2, casual 1, Tavern Brawl 1, unknown (no `type` attribute) 58 |
| Multi-game documents                   | 1 (four Mercenaries bounty games in one file)                                                                                                     |

Directories group files by what the `Game` element says (`standard/`,
`wild/`, `classic/`, `friendly/`, `tavern_brawl/`, `battlegrounds/`,
`mercenaries/`), by absence of that information (`legacy/`, mostly HSReplay
1.3–1.4 files without `type`), by origin (`converted/`, see below) and by
what makes a file interesting for robustness (`edge/`).

## Sources and licenses

| Source                                                                                                                          | Files | License         | Notes                                                                                                                                                                                                                                                                                                                                                                                           |
| ------------------------------------------------------------------------------------------------------------------------------- | ----: | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [HearthSim/hsreplay-test-data](https://github.com/HearthSim/hsreplay-test-data) `hsreplaynet-tests/replays/`, commit `715d408e` |    92 | CC0-1.0         | The fixtures HSReplay.net tests against, 2016–2024. Files named `*annotated*` carry extra attributes (`GameTagName`, `EntityCardName`, …) that the parser preserves as unknown attributes. Every non-Battlegrounds XML file of that directory is included; Battlegrounds files above 3 MB are not.                                                                                              |
| HearthSim/hsreplay-test-data Power.log fixtures, converted                                                                      |     8 | CC0-1.0         | `hslog-tests/*.power.log` and `data/zayle.log` converted with python-hsreplay 1.16.2 / python-hslog 1.20.0 (`converted/`). The games are real; the XML was written by the reference implementation, not by hand. They carry no build attribute and time-only timestamps. Other logs of that repository either produce empty documents or fail in the reference converter (`MissingPlayerData`). |
| [patruff/hearthbreaker](https://github.com/patruff/hearthbreaker) `hsreplays_xml/`, commit `1ba8e03c`                           |     3 | MIT             | HSReplay.net downloads of the author's Classic ranked games (2022, builds 126451–131660). 37 of the 40 sampled files begin with a browser status line before the XML prolog and are not well-formed; only the 3 clean ones were imported.                                                                                                                                                       |
| `test.xml`                                                                                                                      |     1 | project fixture | Hearthstone Deck Tracker export provided by the project owner (ranked Standard, build 250339). Golden fixture.                                                                                                                                                                                                                                                                                  |

Not included: `beheh/hsreplay-examples` (35 files, no license), `HearthSim/Joust`
`sample.hsreplay` (no license), Battlegrounds fixtures above 3 MB (repository size).

## Confirmed features

Counted from packets by `scripts/corpus/import.mjs`, never inferred from
names: DEATHS blocks 65 files, attacks 63, mulligan 55, hero powers 50,
discover/choices 43, deck lists 34, sub-spells 29, weapons 29, forced
attacks 21, secrets 19, fatigue 12, `ChangeEntity` 12, effect-initiated
plays 9, `ShuffleDeck` 8, GAME_RESET 2, redirected attacks 2.

## Edge cases and anomalies

| Anomaly                 | Files | Meaning                                                                                                                   |
| ----------------------- | ----: | ------------------------------------------------------------------------------------------------------------------------- |
| `REFERENCE_UNSUPPORTED` |    10 | python-hsreplay cannot read the file (HSReplay 1.0 `<Action>`, time-only timestamps); allowlisted in the differential run |
| `GAME_RESET`            |     3 | `GAME_RESET` blocks re-create entities and rewind the turn                                                                |
| `TURN_NOT_MONOTONIC`    |     3 | turn numbers go backwards without a reset (inconsistent logs, Mercenaries bounties)                                       |
| `MULTIPLE_GAMES`        |     1 | several `Game` elements in one document                                                                                   |
| `RECONNECT`             |     1 | `Game reconnecting="true"`, log starts mid-game                                                                           |

## Known gaps

- **No Arena, Twist or Duels replays.** No licensed public fixture was found
  (GitHub code search for `type="5"` / `format="4"` documents only returns
  test snippets). Until one exists, nothing here is validated for those modes.
- **Modern builds are thin.** Only `test.xml` (250339) and one hsreplay-test-data
  file (248348) are from 2025–2026; the 2022 Classic files are the next newest.
  Mechanics introduced after 2024 (Starship, Tourist, Forge, Excavate, Quickdraw,
  Miniaturize, Titans) have no fixture and are not validated. Locations are
  present in four files (16 activations).
- **Battlegrounds** has 14 short-to-medium games (builds 36393–210640): hero
  entities, tavern buttons, recruit and combat phases, forced attacks and
  player elimination are exercised; Duos, trinkets and games longer than
  ~3 MB are not.
- 58 files do not state their game type; their mode is unknown, not guessed.
- Only three non-English player names in real files; Unicode handling is
  covered by synthetic tests instead.

Until these gaps close, the claim is "validated against these 104 fixtures",
not "works with every Hearthstone replay".

## Tooling

```bash
pnpm corpus:import ./replay.xml --source <url> --repository owner/repo --commit <sha> --license CC0-1.0 [--notes ...] [--mode ...] [--folder ...] [--edge]
pnpm corpus:verify        # checksums and a summary
pnpm corpus:report        # docs/generated/corpus-report.{md,json}
pnpm corpus:unknowns      # new unknown tags/nodes/enum values vs docs/generated/unknowns-baseline.json (--update to re-baseline)
pnpm corpus:stats         # zone-transition and attribution statistics behind the semantic rules
pnpm test:corpus          # invariants and recorded event counts on every entry
UPDATE_CORPUS_COUNTS=1 pnpm test:corpus   # re-record event counts after an intended rule change
```

The importer refuses licenses outside its accepted list, duplicates (by
SHA-256), and files the parser cannot read without errors unless
`--allow-errors` is given. It reads version, build, game type and format from
the file, derives the mode from those two attributes only, confirms features
and anomalies from the packets, and records the event counts.

## Size

The corpus is 81.7 MB of plain XML that git compresses to about 6 MB in
the pack (gzip ratio ≈ 15:1). Storing `.xml.gz` would shrink the checkout
but not the repository history, and would make fixtures opaque to `grep`
and diffs, so plain XML stays until the corpus passes roughly 250 MB.
