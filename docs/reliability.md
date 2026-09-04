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
  really happened in a game, only the log. `CARD_DRAWN`
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
- In a manual run on the corpus (2026-09-04), entities, card ids, tags,
  player ids, packet order and game results agreed with python-hsreplay /
  python-hslog on every file both implementations can read (see
  `docs/differential-testing.md`). The differential harness is not part of
  CI.

Not a simulator: it does not know what a tag means, never infers a tag that
the log did not write, and reports re-created entities (`ENTITY_RECREATED`)
after a `GAME_RESET` block rather than deciding what happened.

## What the semantic layer does NOT guarantee

- **Completeness.** Mechanics the rules do not cover produce no event.
  Opening-hand dealing and mulligan replacements are deliberately not
  `CARD_DRAWN`; spells and enchantments leaving play are not `ENTITY_DIED`;
  an entity whose card type was never revealed never dies.
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
  Tavern Brawl, friendly, vs AI), three Mercenaries logs and two tiny
  Battlegrounds logs. Battlegrounds combat phases, Duels and Arena are not
  covered by the corpus and the rules have not been checked against them.
- **Client builds.** The corpus spans builds 10956 to 250339. Newer logs may
  introduce elements, attributes, tags and enum values the library does not
  name; they are preserved and surfaced by `analyzeUnknowns`, not
  interpreted.

## How to extend a rule

1. Add or find a corpus replay that shows the case.
2. Write the failing test against the rule id.
3. Change the rule in `src/semantic/rules.ts` and the extractor.
4. Re-run the corpus and differential harness.
