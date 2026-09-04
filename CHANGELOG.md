# Changelog

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
