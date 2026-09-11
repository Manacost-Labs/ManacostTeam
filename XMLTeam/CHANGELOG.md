# Changelog

## 0.5.0

Compatibility, corpus and reliability release. No architectural change.

### Added

- `CACHED_TAG_FOR_DORMANT_CHANGE`, `RESET_GAME` and `VO_SPELL` packets for the elements python-hsreplay writes when converting Power.log files; previously `UNKNOWN`.
- `ENTITY_DIED.viaDeathsBlock`: whether the entity left play inside a DEATHS block (false for a weapon replaced by a new one).
- `analyzeUnknowns`: `fileCount`, `firstBuild`, `lastBuild`, `sampleFile` / `samplePacketIndex` (first occurrence in the newest build) per unknown; `LabeledReplay.build`.
- Corpus tooling: `pnpm corpus:import` (checksum, dedupe, metadata from the file, confirmed features, accepted-license check), `pnpm corpus:refresh` (recompute derived manifest fields), `pnpm corpus:report` (`docs/generated/corpus-report.{md,json}` with per-rule coverage), `pnpm corpus:unknowns` (diff against `docs/generated/unknowns-baseline.json`), `pnpm benchmark:corpus`.
- Differential harness outcomes `MATCH` / `DIVERGENCE` / `REFERENCE_UNSUPPORTED` / `OUR_FAILURE`, report artifacts, pinned `scripts/differential/requirements.txt`, weekly `Differential` workflow.
- `docs/api-stability.md` (stable / experimental / internal exports).

### Changed

- `CARD_PLAYED` is no longer emitted when the played entity has a known card type that is not a playable card: Battlegrounds tavern buttons (CardType 12, 177 blocks in the corpus), hero buddies and drag targets (22, 238) and Mercenaries abilities (23, 230) go through PLAY blocks too. Never-revealed entities (opponent secrets) are still reported with `cardType` undefined.
- `CardType` values corrected from HearthSim's `hearthstone.enums`: `LOCATION` is 39 (was 16), `MOVE_MINION_HOVER_TARGET` 22, `LETTUCE_ABILITY` 23, `BATTLEGROUND_QUEST_REWARD` 40, `BATTLEGROUND_SPELL` 42, `BATTLEGROUND_ANOMALY` 43, `BATTLEGROUND_TRINKET` 44; added `BATTLEGROUND_HERO_BUDDY` 24 and `PET` 45. `MetaDataType` 17–28, `Step` 18–20, `Zone` 8–9 and `BlockType.DECK_ACTION` (13) added; `HOLD_DRAWN_CARD` is 17 (was 18). `MAIN_STEPS` exported. The old `LOCATION` value never matched a real entity, so location activations and location deaths are reported for the first time.
- `HEALING` no longer has a `source`, and `SemanticRuleId.HEALING_SOURCE` is gone: the log writes no LAST_AFFECTED_BY for healing (0 of 338 healing packets in the corpus), so the rule could never fire.
- Package scripts call tools as `node node_modules/<tool>/…` (see README); `packageManager` pinned to pnpm 10.34.5; `pnpm-workspace.yaml` allows the esbuild build script.
- Package smoke test now also compiles a TypeScript consumer against the shipped declarations and bundles the core entry for the browser with esbuild, failing on any `node:` import.

### Fixed

- `TagValueRecord` history and `analyzeUnknowns` handle the new packet types; `ENTITY_DIED` no longer fires for unknown card types that only exist in Battlegrounds/Mercenaries logs.

### Testing

- Corpus grown from 37 to 104 real replays (81.7 MB, 30 client builds 10956–250339, HSReplay 1.0–1.7, Standard/Wild/Classic/Battlegrounds/Mercenaries/Puzzle Lab/Tavern Brawl/friendly), each with recorded semantic event counts.
- New properties: corpus replays under random byte chunking and random checkpoint intervals, unknown attribute/element preservation with telemetry agreement; nine more XML mutations (duplicate attributes, namespace prefixes, whitespace/comments/PIs, empty elements, 20 000 packets, truncated UTF-8, DOCTYPE variants, no prolog); Unicode player names in eight scripts; GAME_RESET timeline and tag-history tests on every reset replay.
- Coverage thresholds (95% statements/lines, 93% functions, 85% branches overall; parser/state/semantic per-directory gates).

### Compatibility

- Differential run: 94 MATCH, 0 DIVERGENCE, 0 OUR_FAILURE, 10 REFERENCE_UNSUPPORTED (allowlisted: HSReplay 1.0 `<Action>`, time-only timestamps).
- Unknowns baseline: 715 unnamed GameTags and 18 unnamed enum values recorded for patch tracking; no unknown elements remain in the corpus.

## 0.4.0

Hardening release: same architecture, more evidence.

- **Semantic provenance**: every event carries `evidence { level, rule, packetIndices }`; rules are registered in `SEMANTIC_RULES` / `SemanticRuleId` with source and caveats.
- **Rule corrections** (breaking for consumers of 0.3 events):
  - `ENTITY_DIED` is no longer emitted for spells and enchantments leaving play (455 + 225 false positives on the corpus); only minions, heroes, weapons and locations die.
  - `CARD_DRAWN` is no longer emitted for the opening hand and mulligan replacements (DECK → HAND before the first MAIN step).
  - `DAMAGE.source` / `HEALING.source` now come from the `LAST_AFFECTED_BY` tag the log writes (rule `DAMAGE_SOURCE`); the enclosing block entity moved to `blockEntity`. In the corpus the two differed in 22% of attributed damage events.
  - `CARD_PLAYED`, `HERO_POWER_USED`, `ATTACK` gain `initiator: 'player' | 'effect'`.
  - New observed event `GAME_RESET`.
- **Parser compatibility** found on the corpus: legacy HSReplay 1.0 `<Action>` elements parse as `BLOCK` (`LEGACY_ELEMENT` info); `<Target>` without `entity` is accepted; unknown attributes are reported once per element kind (`infoOnce`) instead of once per element.
- **Type changes** (breaking): `OptionTarget.entity` is optional; `TagValueRecord.value` is `number | undefined`; `evidence` (all events) and `initiator` (`CARD_PLAYED`, `HERO_POWER_USED`, `ATTACK`) are new required event fields; `SemanticEventType.GAME_RESET` is a new union member. Game-level diagnostics now list the `Game` element's own unknown attributes before packet diagnostics (same order as the streaming parser).
- `STRICT_VIOLATION_CODES` / `isStrictViolation` document exactly what strict mode rejects.
- `collectTagHistory` records tags cleared by a re-definition of an entity (`value: undefined`), matching the state engine.
- `analyzeUnknowns(replays)`: unknown nodes, attributes, children, tags and enum values with frequencies and first occurrences.
- Replay corpus (`test/corpus`, 36 CC0 HearthSim fixtures + `test.xml`, manifest with checksums), corpus invariant tests, fast-check property tests, XML mutation tests, differential harness against python-hsreplay, GitHub Actions CI (Node 20/22/24, coverage, package smoke test, benchmark), `pnpm benchmark`, `pnpm pack:smoke`.

## 0.3.0

- Semantic events: `extractEvents` with `GAME_STARTED`, `GAME_ENDED`, `TURN_STARTED`, `CHOICE_OFFERED`, `CHOICE_MADE`, `OPTION_CHOSEN`, `CARD_PLAYED`, `HERO_POWER_USED`, `ATTACK`, `CARD_DRAWN`, `ZONE_CHANGED`, `ENTITY_DIED`, `DAMAGE`, `HEALING`, `TRIGGERED`, `FATIGUE`, `CONCEDED`.
- Streaming: `streamReplay` (async generator of document / game / packet events) and `parseReplayStream`; `parseReplayFileStream` / `parseReplayDocumentFileStream` in the Node entry.
- `XmlTreeBuilder`: incremental XML reader with `onOpen` / `onClose` hooks, exported for advanced use.
- Internal: metadata readers moved to `parser/metadata.ts`, `GamePacketizer` exported.

## 0.2.0

- `parseReplayDocument` / `parseReplayDocumentFile`: every `Game` of a document, each with its own packets, state and diagnostics.
- `ReplayTimeline` (`createTimeline`): checkpointed random access to the observed state after any packet.
- `snapshotState` / `restoreState`: immutable state snapshots.
- `collectTagHistory`: chronological values of every tag per entity.
- Enum value tables: `Step`, `PlayState`, `GameEntityState`, `MulliganState`, `BlockType`, `MetaDataType`, `ChoiceType`, `OptionType`, `GameType`, `FormatType`; `describeTagValue`, `enumName`.
- `GameState.turn`, `step`, `currentPlayer`, `findPlayerByName`.
- Name-based entity references now resolve to players by name.
- `GameTag.MULLIGAN_STATE`.

## 0.1.0

- Initial release: hardened XML layer, lossless raw packets with document-order indexes, block hierarchy, diagnostics with strict mode, `EntityStore` and observed-state engine, `test.xml` integration and golden tests.
