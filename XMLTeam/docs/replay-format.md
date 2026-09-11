# HSReplay format as observed in `test.xml`

This document records what the real fixture (`test.xml`, HSReplay 1.7, Hearthstone
build 250339, exported by Hearthstone Deck Tracker) actually contains. The parser
is designed against this data first and against the
[HSReplay 1.7 DTD](https://hearthsim.info/hsreplay/dtd/hsreplay-1.7.dtd) second.
Where the two disagree, the file wins.

## Document shape

```
<?xml version='1.0' encoding='utf-8'?>
<!DOCTYPE hsreplay SYSTEM "https://hearthsim.info/hsreplay/dtd/hsreplay-1.7.dtd">
<HSReplay build="250339" version="1.7">
  <Game ts="…" id="13991" format="2" type="7" scenarioID="2">
    <GameEntity id="1"> <Tag …/> … </GameEntity>
    <Player id="2" playerID="1" accountHi="…" accountLo="…" name="…"> <Tag …/> … </Player>
    <Player id="3" playerID="2" …> <Deck><Card id="TIME_702"/>…</Deck> <Tag …/> … </Player>
    <FullEntity …/> … <TagChange …/> <Block …> … </Block> <Options …> … </Options> <SendOption …/>
  </Game>
</HSReplay>
<!-- https://hsreplay.net/replay/… -->
```

- Root element: `HSReplay` (`build`, `version`).
- Exactly one `Game` element. The DTD allows several; v0.1 parses the first and
  reports the rest with a diagnostic.
- A `DOCTYPE` with an external `SYSTEM` DTD is present. It must never be fetched.
- A trailing XML comment after the root element. It must be tolerated.
- No element carries text content. Everything is attributes + child elements.
- `accountHi` is a 57-bit integer (`144115193835963207`), larger than
  `Number.MAX_SAFE_INTEGER`. Account identifiers must be kept as strings.
- Maximum tag value observed: `2147483647` (Int32 max). No negative values.
- Maximum nesting depth: 8 (`HSReplay > Game > Block > Block > SubSpell > Block > MetaData > Info`).

## Element inventory

| Element          | Count | Attributes (count = occurrences)                                                                                   | Parents                                       |
| ---------------- | ----- | ------------------------------------------------------------------------------------------------------------------ | --------------------------------------------- |
| `TagChange`      | 6921  | `entity`, `tag`, `value`, `hasChangeDef` (17, always `"true"`)                                                     | Game 441, Block 5717, SubSpell 763            |
| `Tag`            | 4932  | `tag`, `value`                                                                                                     | GameEntity, Player, FullEntity, ShowEntity    |
| `Option`         | 964   | `index`, `type`, `entity` (901), `error` (665)                                                                     | Options                                       |
| `Target`         | 536   | `index`, `entity`, `error` (239)                                                                                   | Option                                        |
| `Block`          | 520   | `entity`, `type`, `effectCardId`, `ts`, `effectIndex` (247), `target` (51), `triggerKeyword` (48), `subOption` (6) | Game 375, Block 143, SubSpell 2               |
| `Info`           | 462   | `index`, `entity`                                                                                                  | MetaData                                      |
| `MetaData`       | 439   | `meta`, `data`, `infoCount`                                                                                        | Block 277, Game 98, SubSpell 64               |
| `FullEntity`     | 259   | `id`, `cardID` (106)                                                                                               | Game 78, Block 106, SubSpell 75               |
| `ShowEntity`     | 118   | `entity`, `cardID`                                                                                                 | Block 83, Game 2, SubSpell 33                 |
| `SubSpell`       | 74    | `spellPrefabGuid`, `source`, `targetCount`, `ts`                                                                   | Block                                         |
| `Options`        | 63    | `id`, `ts`                                                                                                         | Game                                          |
| `SendOption`     | 62    | `option`, `subOption`, `target`, `position`, `ts`                                                                  | Game                                          |
| `Choice`         | 61    | `index`, `entity`                                                                                                  | Choices 37, ChosenEntities 14, SendChoices 10 |
| `SubSpellTarget` | 57    | `index`, `entity`                                                                                                  | SubSpell                                      |
| `HideEntity`     | 42    | `entity`, `zone`, `ts`                                                                                             | Block 34, Game 8                              |
| `Card`           | 30    | `id`                                                                                                               | Deck                                          |
| `SubOption`      | 26    | `index`, `entity`                                                                                                  | Option                                        |
| `Choices`        | 12    | `entity`, `id`, `taskList`, `type`, `min`, `max`, `source`, `ts`                                                   | Block                                         |
| `ChosenEntities` | 12    | `entity`, `id`, `ts`                                                                                               | Block                                         |
| `SendChoices`    | 8     | `id`, `type`, `ts`                                                                                                 | Block                                         |
| `Player`         | 2     | `id`, `playerID`, `accountHi`, `accountLo`, `name`                                                                 | Game                                          |
| `ShuffleDeck`    | 2     | `player_id`                                                                                                        | Block                                         |
| `Game`           | 1     | `ts`, `id`, `format`, `type`, `scenarioID`                                                                         | HSReplay                                      |
| `GameEntity`     | 1     | `id`                                                                                                               | Game                                          |
| `Deck`           | 1     | (none)                                                                                                             | Player                                        |

Not present in the fixture but defined by the DTD: `ChangeEntity`. It is supported
by the parser anyway because it is part of the format; it is covered by a
synthetic unit-test fixture, not by `test.xml`.

## Deviations from the 1.7 DTD

| Observation                                                             | DTD                 | Handling                                                          |
| ----------------------------------------------------------------------- | ------------------- | ----------------------------------------------------------------- |
| `SubSpell` / `SubSpellTarget` elements                                  | not defined         | first-class packet `SUB_SPELL` (packet container, like `Block`)   |
| `ShuffleDeck player_id="1"`                                             | not defined         | first-class packet `SHUFFLE_DECK`                                 |
| `TagChange hasChangeDef="true"`                                         | not defined         | preserved as optional boolean                                     |
| `MetaData infoCount="1"`                                                | DTD names it `info` | both spellings accepted                                           |
| `Block effectCardId="System.Collections.Generic.List`1[System.String]"` | should be a card id | kept verbatim; it is a logger artefact and carries no information |
| `Deck` has no `type` attribute                                          | `type` required     | optional                                                          |
| Empty self-closing `<Block …/>`                                         | allowed             | `BLOCK` packet with zero children                                 |
| `Choices`, `ChosenEntities`, `SendChoices` inside `Block`               | allowed             | packets inside the block hierarchy                                |

## Elements seen only in other real replays (v0.5 corpus)

| Element                     | Attributes                                                                   | Origin                                    | Handling                                                    |
| --------------------------- | ---------------------------------------------------------------------------- | ----------------------------------------- | ----------------------------------------------------------- |
| `Action`                    | as `Block`                                                                   | HSReplay 1.0 (`edge/hslog.xml`)           | `BLOCK` packet + `LEGACY_ELEMENT` info                      |
| `CachedTagForDormantChange` | `entity`, `tag`, `value`                                                     | python-hsreplay ≥ 1.13 (Dormant mechanic) | `CACHED_TAG_FOR_DORMANT_CHANGE`; does not touch entity tags |
| `ResetGame`                 | `ts`                                                                         | python-hsreplay (RESET_GAME power)        | `RESET_GAME`                                                |
| `VOSpell`                   | `brass_ring_guid`, `vo_spell_prefab_guid`, `blocking`, `additional_delay_ms` | python-hsreplay (VO_SPELL power)          | `VO_SPELL`, cosmetic                                        |
| `Target` without `entity`   | `index`, `error`                                                             | HSReplay 1.5 options                      | `OptionTarget.entity` optional                              |

## Packet containers vs. payload elements

Three elements contain a sequence of packets and define the hierarchy:
`Game`, `Block`, `SubSpell`. Every other element is either a packet without
children or a packet whose children are _payload_, not packets:

| Packet element                                                     | Payload children                           |
| ------------------------------------------------------------------ | ------------------------------------------ |
| `GameEntity`, `Player`, `FullEntity`, `ShowEntity`, `ChangeEntity` | `Tag` (+ `Deck > Card` for `Player`)       |
| `MetaData`                                                         | `Info`                                     |
| `Choices`, `ChosenEntities`, `SendChoices`                         | `Choice`                                   |
| `Options`                                                          | `Option > (SubOption                       | Target)*` |
| `SubSpell`                                                         | `SubSpellTarget` (payload) **and** packets |

Payload children never receive a packet index. Packet indexes are assigned in
document order (pre-order), so a `Block` at index `n` has its first child at `n+1`.

## Entity references

Every `entity`, `source`, `target`, `id` attribute that refers to an entity is a
plain integer in this file. The DTD warns that an entity reference can also be
the string `UNKNOWN HUMAN PLAYER`, and older exporters wrote player names. The
parser therefore models entity references as a union (`id` or `name`).

Entity ids observed: 262 distinct ids in the range 1..331. Id `1` is the
`GameEntity`, ids `2` and `3` are the players. No entity id is created twice.
Every `ShowEntity` and `TagChange` refers to an id that was created earlier.

## Observed enum values (for orientation only)

- `Block.type`: 1 (ATTACK), 3 (POWER), 5 (TRIGGER), 6 (DEATHS), 7 (PLAY), 13.
- `Block.triggerKeyword`: 32, 217, 219, 338, 462, 685, 2311 (GameTag ids).
- `MetaData.meta`: 0, 1, 2, 5, 6, 7, 8, 9, 12, 20, 24.
- `Choices.type` / `SendChoices.type`: 1 (MULLIGAN), 2 (GENERAL).
- `Option.type`: 2 (END_TURN), 3 (POWER). `Option.error` / `Target.error` are
  `PlayReq` names such as `REQ_ENOUGH_MANA`, `REQ_YOUR_TURN`, `INVALID`.
- `HideEntity.zone`: 1..6.
- Tag `49` (ZONE) values 1..7, tag `50` (CONTROLLER) 1..2, tag `202` (CARDTYPE),
  tag `263` (ZONE_POSITION), tag `53` (ENTITY_ID) equals the entity id.
- Tag `17` (PLAYSTATE) ends at 8 (CONCEDED) → 5 (LOST) for player 3 and 4 (WON)
  for player 2; tag `204` (STATE) of the game entity ends at 3 (COMPLETE).

## Event order

Order matters. `Block` children interleave `TagChange`, `FullEntity`,
`ShowEntity`, `MetaData`, `HideEntity`, nested `Block`, `SubSpell`, choice
packets. The XML layer must preserve sibling order exactly, and packets must be
emitted in document order.

## Event patterns used by the semantic layer

Verified on this fixture; the extractor relies on exactly these.

- A turn change is a `Block` of type TRIGGER on the game entity containing, in
  order, `CURRENT_PLAYER` changes and then the `TURN` change. The current
  player is therefore already correct when `TURN` changes.
- 30 ATTACK blocks: 26 carry `target`, 4 do not. In 8 blocks the entity whose
  `DEFENDING` tag is set differs from `target` (redirected attacks). The
  semantic `ATTACK` event reports both.
- Damage is `MetaData meta="1" data="<amount>"` with one `Info` per target,
  inside the block of the attacker or effect source. `TagChange DAMAGE` follows.
  Healing is `meta="2"`.
- PLAY blocks reveal the played card via `ShowEntity` inside the block, so the
  card type is only known after the block; hero powers are PLAY blocks whose
  entity has `CARDTYPE` = HERO_POWER.
- Every `Choices` has a matching `ChosenEntities` except one (`id` 12);
  `SendChoices` exists for 8 of 12.
- The game ends with `PLAYSTATE` changes on both players followed by
  `STATE` = COMPLETE on the game entity.
