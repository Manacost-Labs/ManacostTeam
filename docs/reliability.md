# Reliability: what the library does and does not guarantee

`@manacost/hearthstone-replay` has three layers with three different kinds
of truth. Consumers, and especially anything that trains on the output,
must know which one they are looking at.

| Layer           | Kind of truth             | Guarantee                                                                    |
| --------------- | ------------------------- | ---------------------------------------------------------------------------- |
| Raw packets     | **observed**              | A lossless, typed mirror of the XML. Nothing is interpreted.                 |
| Game state      | **observed, accumulated** | The entity tags the log has set so far. No rules of the game are applied.    |
| Semantic events | **interpretation**        | Each event says how it was inferred (`evidence`). Some rules are heuristics. |

## Evidence levels

Every semantic event carries `evidence: { level, rule, packetIndices }`.

- **observed** – the event restates one packet. `ZONE_CHANGED` is the tag
  change itself, `DAMAGE` is the `MetaData` packet, `CHOICE_OFFERED` is the
  `Choices` packet, `GAME_RESET` is the block. The only interpretation is the
  name.
- **derived** – the event combines a packet with state the log had already
  established, through a rule that is defined once in
  `src/semantic/rules.ts`, is unit-tested on synthetic layouts and is
  checked on every replay of the corpus by invariants and recorded event
  counts. "Checked" is not "proven": there is no ground truth for what
  really happened in a game, only the log. The
  [corpus report](generated/corpus-report.md) shows how many files and
  events exercise each rule; a rule with few events is weakly validated. `CARD_DRAWN`
  is `ZONE` DECK → HAND during a MAIN step; `ENTITY_DIED` is `ZONE` PLAY →
  GRAVEYARD of a minion, hero, weapon or location; `DAMAGE_SOURCE` reads the
  `LAST_AFFECTED_BY` tag the log writes right after the damage.
- **heuristic** – the rule is plausible but has known counter-examples or
  insufficient data. No shipped rule is currently marked heuristic: rather than
  emit a heuristic event, the extractor stays silent and leaves the raw
  `ZONE_CHANGED` / `TRIGGERED` events and the packets. This is deliberate:
  **a missing event is cheaper than a wrong one.**

`packetIndices` always contains the event's own `packetIndex` and any other
packet the rule read (the `DEFENDING` tag change for an attack, the
`LAST_AFFECTED_BY` tag change for a damage source, the `Choices` packet for a
`CHOICE_MADE`). No numeric confidence is attached: there is no statistical
basis for one.

## Parser guarantees

Checked by unit, property (fast-check) and corpus tests:

- Every element in packet position becomes exactly one packet; unknown
  elements become `UNKNOWN` packets, unknown attributes and unexpected
  children are preserved on the packet. Nothing is dropped silently.
- Packet indexes are gap-free, unique and in document order; container
  children keep their order.
- Serialising a model and parsing it back yields the model (roundtrip
  property over generated documents).
- Streaming parse equals in-memory parse for every chunking, including cuts
  inside UTF-8 sequences, tags and attributes (property over random
  chunkings, one-byte chunks, and every corpus file).
- Parsing is deterministic.
- Strict mode throws exactly when a diagnostic listed in
  `STRICT_VIOLATION_CODES` (or any error) was recorded; lenient mode never
  throws for well-formed XML.
- The DOCTYPE is never dereferenced, only the five predefined entities are
  expanded, references to declared entities are parse errors, nesting and
  element count are bounded, and no network request is ever made (the
  mutation tests fail if `fetch` is called).

Malformed XML (truncated file, mismatched tags, entity expansion attempts)
raises `ReplayParseError` with line and column.

## State engine guarantees

- Applies `GameEntity`, `Player`, `FullEntity`, `ShowEntity`,
  `ChangeEntity`, `HideEntity` and `TagChange` in packet order; the tag map
  is the only source of truth.
- `restoreState(snapshotState(s))` equals `s` and is independent of it.
- `timeline.stateAt(i)` equals applying the leaf packets `0..i` in order for
  any checkpoint interval.
- `collectTagHistory` ends, for every tag, on the value the final state holds.
- Differential run on the corpus (2026-09-04, and weekly in CI): entities,
  card ids, tags, player ids, packet order and game results agree with
  python-hsreplay / python-hslog on all 94 files both implementations can
  read; the 10 files the reference rejects are allowlisted in the manifest
  (see `docs/differential-testing.md`).

Not a simulator: it does not know what a tag means, never infers a tag that
the log did not write, and reports re-created entities (`ENTITY_RECREATED`)
after a `GAME_RESET` block rather than deciding what happened.

## What the semantic layer does NOT guarantee

- **Completeness.** Mechanics the rules do not cover produce no event.
  Opening-hand dealing and mulligan replacements are deliberately not
  `CARD_DRAWN`; cards that go from deck to graveyard (burned or milled) are
  reported only as `ZONE_CHANGED` because the log does not say why; spells
  and enchantments leaving play are not `ENTITY_DIED`; an entity whose card
  type was never revealed never dies.
- **Card plays.** `CARD_PLAYED` requires the entity to be a minion, spell,
  weapon, hero or location once the PLAY block has been applied, or to have no
  card type at all (an opponent's secret played from hand and never revealed).
  Battlegrounds tavern buttons, hero buddies and Mercenaries abilities also go
  through PLAY blocks and are not reported (645 such blocks in the corpus).
  Location activations are `CARD_PLAYED` with `cardType` LOCATION (16 in the
  corpus).
- **"Died".** `ENTITY_DIED` means the entity was destroyed: minions and heroes
  through DEATHS blocks, weapons also when replaced by a new weapon
  (`viaDeathsBlock: false`, 12 of 76 weapon cases in the corpus). A future
  major version may rename it `ENTITY_DESTROYED`; the field
  `viaDeathsBlock` already lets consumers separate the two today.
- **Healing.** The log writes no `LAST_AFFECTED_BY` for healing (0 of 338
  healing packets in the corpus), so `HEALING` carries `blockEntity` only and
  the former `HEALING_SOURCE` rule was removed rather than left unvalidated.
- **Attribution.** `DAMAGE.source` exists only when the log wrote
  `LAST_AFFECTED_BY` for the target before its next hit; absorbed hits
  (Divine Shield, Immune) never carry it, and a layout the rule does not
  anticipate would also leave it empty. `blockEntity` is context, not the
  cause: in the corpus it differs from `LAST_AFFECTED_BY` in about one
  attributed damage event out of five.
- **Player intent.** `CARD_PLAYED.initiator` is `player` for a top-level
  PLAY block and `effect` for a nested one. That is what the log structure
  says; it is not proof that a human chose the card.
- **Redirected attacks.** `ATTACK.target` (block attribute) and
  `ATTACK.defender` (DEFENDING tag) can differ or be absent; both are
  reported, neither is corrected.
- **Monotonic turns.** `TURN_STARTED.turn` follows the log. It goes
  backwards after `GAME_RESET` and in logs that are themselves inconsistent
  (one such file is in the corpus, flagged `TURN_NOT_MONOTONIC`).
- **Game modes.** Rules were validated on constructed games (Standard, Wild,
  Classic, Tavern Brawl, friendly, vs AI), nine Mercenaries logs, two Puzzle
  Lab logs and fourteen Battlegrounds games. In Battlegrounds the rules stay
  conservative: no draws (there are none), no card plays for tavern buttons,
  attacks and deaths from the real combat phases. Arena, Twist and Duels are
  not in the corpus (see `docs/replay-corpus.md`).
- **Client builds.** The corpus spans 30 builds from 10956 to 250339, but only
  two files are newer than 2024. Newer logs may introduce elements,
  attributes, tags and enum values the library does not name; they are
  preserved and surfaced by `analyzeUnknowns` and `pnpm corpus:unknowns`,
  not interpreted. The current baseline lists 715 unnamed tags and 18
  unnamed enum values (`BlockType` 13, `CardType` 22/23/39/40/42/44, `Step`
  18–20, `MetaDataType` 19–25, `Zone` 8).

## How to extend a rule

1. Add or find a corpus replay that shows the case.
2. Write the failing test against the rule id.
3. Change the rule in `src/semantic/rules.ts` and the extractor.
4. Re-run the corpus and differential harness.
