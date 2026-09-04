# API stability

The package is pre-1.0, so minor versions may still change public types.
This page says which exports you can build on today, which are still
moving, and which are implementation details that happen to be reachable.
Breaking changes to **stable** exports are always listed under "Changed" in
the changelog with a migration note; **experimental** exports may change in
any minor release; **internal** modules are not part of the contract at all.

## Stable

Entry point `@manacost/hearthstone-replay`:

| Area                   | Exports                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Parsing                | `parseReplay`, `parseReplayDocument`, `parseReplayStream`, `ParseReplayOptions`, `Replay`, `ReplayDocument`, `ReplayMetadata`, `GameMetadata`, `ReplayPlayer`, `DocumentHeader`                                                                                                                                                                                                                                                                           |
| Errors and diagnostics | `ReplayError`, `ReplayParseError`, `ReplayValidationError`, `ReplayErrorContext`, `DiagnosticCode`, `ReplayDiagnostic`, `DiagnosticLevel`, `STRICT_VIOLATION_CODES`, `isStrictViolation`                                                                                                                                                                                                                                                                  |
| Raw packets            | `ReplayPacketType`, every `*Packet` interface, `ReplayPacket`, `ContainerPacket`, `isContainerPacket`, `TagPair`, `DeckList`, `DeckCard`, `OptionEntry`, `SubOptionEntry`, `OptionTarget`, `ChoiceEntry`, `MetaDataInfo`, `SubSpellTarget`, `EntityRef`, `EntityIdRef`, `EntityNameRef`, `parseEntityRef`, `entityId`, `entityRefFromId`, `formatEntityRef`, `flattenPackets`, `walkPackets`, `PacketVisit`, `XmlElement` (as carried by `UnknownPacket`) |
| Tags and enums         | `GameTag`, `Zone`, `CardType`, `Step`, `PlayState`, `GameEntityState`, `MulliganState`, `BlockType`, `MetaDataType`, `ChoiceType`, `OptionType`, `GameType`, `FormatType`, `TAG_VALUE_ENUMS`, `enumName`, `describeTagValue`, `createTagRegistry`, `defaultTagRegistry`, `TagRegistry`, `EnumTable`                                                                                                                                                       |
| State                  | `Entity`, `PlayerInfo`, `EntityStore`, `GameState`, `createGameState`, `applyPacket`, `applyPackets`, `createEntity`, `getTag`, `getZone`, `getController`, `getZonePosition`, `getCardType`, `snapshotState`, `restoreState`, `GameStateSnapshot`, `EntitySnapshot`, `ReplayTimeline`, `createTimeline`, `TimelineOptions`, `collectTagHistory`, `TagHistory`, `TagValueRecord`, `TagHistoryFilter`                                                      |
| Semantic events        | `extractEvents`, `ExtractEventsOptions`, `SemanticEventType`, `SemanticEvent` and every `*Event` interface, `EntityFacts`, `EventInitiator`, `PlayerResult`, `SemanticEvidence`, `SemanticEvidenceLevel`, `SemanticRuleId`, `SemanticRule`, `SEMANTIC_RULES`                                                                                                                                                                                              |

Entry point `@manacost/hearthstone-replay/node`: everything above plus
`parseReplayFile`, `parseReplayDocumentFile`, `parseReplayFileStream`,
`parseReplayDocumentFileStream`.

Stability promises for stable exports:

- packet shapes are lossless mirrors of the XML: a field is only ever added
  when a new element or attribute is found in real replays;
- new enum members (`ReplayPacketType`, `SemanticEventType`,
  `SemanticRuleId`, `DiagnosticCode`) may be added in minor releases; switch
  over them with a default branch;
- semantic rules may become _stricter_ in a minor release when the corpus
  shows a false positive (fewer events, never new meanings for an existing
  event type). Each such change is listed in the changelog with the corpus
  evidence.

## Experimental

| Export                                                                                             | Why it may change                                                     |
| -------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `streamReplay`, `ReplayStreamEvent`, `ReplayStreamChunk`, `ReplayStreamSource`                     | event shapes may gain fields (progress, byte offsets)                 |
| `analyzeUnknowns`, `UnknownReport`, `UnknownOccurrence`, `LabeledReplay`, `AnalyzeUnknownsOptions` | report shape follows the needs of the corpus tooling                  |
| `XmlTreeBuilder`, `parseXml`, `XmlTreeHooks`, `XmlParseOptions`, `XmlDocument`                     | the XML layer is exposed for advanced streaming use; hooks may change |
| `GameState.turn` / `step` / `currentPlayer` / `findPlayerByName`                                   | convenience accessors on the state, may move to helper functions      |

## Internal

Not exported from the package: `DiagnosticCollector`, `AttributeReader`,
node parsers, `GamePacketizer`, `assembleReplay`, `locateGames`, the
metadata readers. Tests import them from `src/`; consumers cannot. The
`test/`, `scripts/` and `docs/` directories are not shipped.

## Versioning

- `0.x.y`: `x` bumps for any change to a stable export, `y` for additions
  and fixes that keep every existing program compiling and every existing
  event meaning intact.
- `1.0.0` will be cut when the semantic rule set has been stable across two
  Hearthstone expansions of corpus growth without a rule correction.
