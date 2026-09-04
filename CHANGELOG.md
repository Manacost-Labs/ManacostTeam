# Changelog

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
