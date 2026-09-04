# Architecture

`@manacost/hearthstone-replay` is built as a pipeline of independent layers.
Each layer consumes the output of the previous one and knows nothing about
the layers above it.

```
XML string
  │  src/parser/xml            saxes-based reader, hardened against untrusted input
  ▼
Ordered element tree (XmlElement)
  │  src/parser/packets        one parser per element, sequential indexes
  ▼
Raw packets (ReplayPacket[])
  │  src/state                 applyPacket(state, packet)
  ▼
EntityStore / GameState
  │  src/semantic              extractEvents(): replays packets through the engine
  ▼
Semantic events
  │  (later)                   statistics, viewer, ML features
  ▼
Analysis
```

## Layer 1 – XML

`parser/xml/parser.ts` turns the document into a minimal tree of
`XmlElement { name, attributes, children, line, column }`. It is the only
module that touches the SAX library.

Design points:

- **Order is sacred.** Children are kept in an array, in document order. The
  tree never becomes a keyed object, so sibling order can not be lost.
- **No text.** HSReplay elements carry no text; non-whitespace text is
  reported as an `UNEXPECTED_TEXT` diagnostic and dropped.
- **Untrusted input.** The DOCTYPE is never fetched, custom entity
  declarations are not honoured (a reference to one is a parse error), and
  nesting depth / element count are bounded. Malformed XML raises
  `ReplayParseError` with line and column.

## Layer 2 – Raw packets

`parser/packets/` converts the children of `Game` into `ReplayPacket`
values. Three elements are _containers_ whose children are packets: `Game`,
`Block` and `SubSpell`. All other elements are _leaf packets_; their children
(`Tag`, `Choice`, `Info`, `Option`, `SubSpellTarget`, `Card`) are payload and
become fields of the packet, not packets of their own.

- `types.ts` – the packet union. Field names follow the XML attribute names
  except where they would collide with the packet discriminator or index
  (`type` → `blockType` / `choiceType` / `optionType`, Block `index` →
  `actionIndex`).
- `node-parsers.ts` – one function per element. They only read attributes
  and payload; containers delegate child conversion back to the packetizer.
- `packetizer.ts` – assigns pre-order indexes, dispatches by element name,
  and turns anything unknown or malformed into an `UnknownPacket` with a
  diagnostic (or an exception in strict mode).
- `attributes.ts` – typed attribute access that tracks what was read, so the
  leftovers can be preserved in `unknownAttributes`.
- `entity-ref.ts` – the `EntityRef` union. Modern files only contain numeric
  ids, but the format allows names, and the parser must not lie about that.
- `walk.ts` – `walkPackets` / `flattenPackets` for flat iteration without
  destroying the hierarchy.

Losslessness rules:

1. Every element in packet position becomes exactly one packet.
2. Unknown attributes are kept (`unknownAttributes`), unknown children of
   payload elements are kept (`unknownChildren`), unknown elements are kept
   whole (`UnknownPacket`).
3. Values are stored raw: numeric tags, string timestamps, verbatim
   `effectCardId`, string account ids.
4. A malformed payload item is skipped and reported; a malformed packet
   becomes an `UnknownPacket` and is reported. Nothing is silently dropped.

## Layer 3 – State

`state/` reconstructs the _observed_ state of the game: what the log says,
not what the rules imply.

- `entity.ts` – `Entity { id, cardId?, tags: Map<number, number>, player? }`
  and accessor functions (`getZone`, `getController`, …). The tag map is the
  single source of truth; accessors only read it.
- `entity-store.ts` – Map-backed `EntityStore` with O(1) lookups.
- `engine.ts` – `GameState` plus `applyPacket(state, packet, diagnostics)`.
  Handles `GAME_ENTITY`, `PLAYER`, `FULL_ENTITY`, `SHOW_ENTITY`,
  `CHANGE_ENTITY`, `HIDE_ENTITY`, `TAG_CHANGE`, and recurses into containers.
  Everything else is informational and leaves state untouched.

The state is mutable and updated in place. A replay with tens of thousands of
packets must not copy the world after every step. Time travel is layered on
top of this model, not baked into it:

- `snapshot.ts` – `snapshotState` / `restoreState`: immutable deep copies of
  a `GameState` and the way back to a mutable one.
- `timeline.ts` – `ReplayTimeline`: walks the flat packet list once, applies
  leaf packets, stores a checkpoint every N packets, and answers
  `stateAt(packetIndex)` by restoring the nearest checkpoint and replaying at
  most N packets. Memory grows with `packetCount / N` snapshots, lookups cost
  O(N) applies.
- `tag-history.ts` – `collectTagHistory`: every value each tag took, with the
  packet index that set it. A pure function of the packets; it mirrors what
  the engine applies (definitions, reveals, changes, hides, tag changes).

Name-based entity references resolve through the players' names; anything
else is reported as `UNRESOLVED_ENTITY_REF`.

## Layer 4 – Semantic events

`semantic/extract.ts` walks the packet hierarchy once, applying each leaf
packet to a private `GameState` so that every event can be described with
the facts known _at that moment_: card id, card type, controller, turn.

- Leaf events (`ZONE_CHANGED`, `CARD_DRAWN`, `ENTITY_DIED`, `TURN_STARTED`,
  `DAMAGE`, …) are emitted when their packet is applied. Zone transitions
  compare the zone before and after the packet, so reveals that move a card
  count too.
- Block events (`CARD_PLAYED`, `HERO_POWER_USED`, `ATTACK`) need what the
  block reveals (a card shown inside its own PLAY block, the DEFENDING tag
  inside an ATTACK block). A slot is reserved when the block opens and filled
  when it closes, so the event still precedes its children in the output.
- Nothing is guessed: an unknown mechanic yields raw zone changes and
  triggers, not a wrong `CARD_PLAYED`.

The extractor is a pure function of the packets. It never feeds anything back
into the state layer, and the state layer does not know it exists.

## Streaming

`parser/stream.ts` uses the same XML builder with two hooks: `onOpen` reads
document and game metadata as soon as their start tags arrive, `onClose`
packetizes each top-level child of a game the moment it is complete and
detaches it from the tree. `streamReplay` yields `document`, `game-start`,
`packet`, `game-end` and `end` events; `parseReplayStream` folds them into the
same `ReplayDocument` that `parseReplayDocument` produces.

## Diagnostics and strictness

`DiagnosticCollector` accumulates `{ level, code, message, packetIndex?,
line?, column? }`. Every code is listed in `DiagnosticCode`. In lenient mode
(default) the parser records and continues; in strict mode
(`{ strict: true }`) every error and every tolerated violation becomes a
`ReplayValidationError`. This lets a batch job over millions of replays keep
going while still knowing exactly which files were odd and why.

## Why the layers stay independent

- **Raw packets are the archive.** They are a faithful, typed mirror of the
  file. Anything derived from them can be recomputed; if they are wrong,
  everything above is wrong. They therefore never depend on state or on
  card knowledge.
- **State is a projection.** Two different consumers (a viewer that needs
  every intermediate board, a statistics job that needs only the end) can
  build different projections from the same packets. Baking state into the
  packets would force one projection on everyone.
- **Semantic events are interpretation.** "Card played" or "minion died" are
  inferred from patterns of blocks and tag changes, and those patterns change
  between Hearthstone builds. Keeping them in their own layer means a new
  build breaks one layer, not the parser.
- **Analysis is opinion.** Mistake detection, win-condition tracking or ML
  features depend on domain models that will be revised constantly. They must
  be able to iterate without touching the parser or the state engine.

Each boundary is a plain data type (`XmlElement`, `ReplayPacket`, `Entity`),
so each layer can be tested, replaced or reused (for instance by a future
Power.log parser that emits the same packets) on its own.

## Module dependency direction

```
errors ← diagnostics ← parser/xml ← parser/packets ← parser/metadata ← parse-replay ← parser/stream ← index ← node
                                       ▲                ▲                    ▲
                                       └──── tags ──────┴──── state ─────────┘
                                                              │
                                             state/snapshot ← state/timeline, state/tag-history
                                             semantic/extract ← (packets, state, tags)
```

Arrows point from dependency to dependant. There are no cycles; `tags` is a
leaf used by both the packet layer (documentation only) and the state layer.
