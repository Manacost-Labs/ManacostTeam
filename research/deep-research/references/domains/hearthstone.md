# Hearthstone Domain Adapter

For Chinese server, deck, guide, or community intelligence, also load [Chinese Hearthstone intelligence](../chinese-hearthstone.md). Its classifications and deck comparisons are ingestion signals, not substitutes for current-patch authority, independent evidence, or the normal claim audit.

Load with the gaming adapter for Hearthstone research. This file adds Hearthstone-specific routing only.

## Context record

Before evidence collection, determine:

- mode: Standard, Wild, Twist, Arena, Battlegrounds, or another explicit mode;
- current patch and effective hotfixes;
- season and expansion/set context;
- region and rank/MMR bracket when statistics or strategy matter;
- entity identity: card, minion, hero, hero power, tribe/minion type, Tavern Tier, Dark Gift, Trinket/accessory, quest, anomaly, spell, or interaction;
- whether the question concerns rules, pool generation, economy, combat, scaling, leveling, synergy, meta, or player behavior.

Never move evidence between constructed and Battlegrounds, or between patches, without an explicit compatibility argument.

## Russian publication contract

Apply this contract to Russian `editor-ready` copy for Standard, Wild, Twist, Arena, Battlegrounds, and every other Hearthstone mode. A name seen in a source, search result, transcript, deck export, screenshot, or community post is a discovery label, not publishable Russian copy.

### KHS identity and name gate

Resolve cards, heroes, hero powers, companions, mechanics, minion types, and named seasonal objects through the public read-only data at `https://api.kolodahearthstone.com` before using their names in reader-facing text. Prefer exact DBF ID resolution, then exact `card_id`; a fuzzy `q` result alone does not establish identity.

The bundled `scripts/hearthstone_names.py` helper is intentionally DBF-only. When only `card_id` or a metadata slug is available, inspect the corresponding exact KHS API route directly and preserve that route in the evidence record; do not pretend the helper performed that lookup. Hero resolution makes additional exact DBF calls for nested hero powers and buddies through the Battlegrounds card collection. If the separate record is absent or lacks an explicitly labeled Russian field, the nested entity remains unresolved even when the parent payload contains a plausible display string.

| Entity scope | KHS resolution route |
|---|---|
| Standard, Wild, Twist, Arena, and other constructed cards | `/api/v1/constructed-cards/by-dbf/{dbf}` or the exact `card_id` route |
| Battlegrounds minions and spells | `/api/v1/cards/by-dbf/{dbf}` or the exact `card_id` route |
| Battlegrounds heroes | `/api/v1/heroes/by-dbf/{dbf}` or the exact `card_id` route; then resolve each nested hero-power and companion DBF through `/api/v1/cards/by-dbf/{dbf}` |
| Anomalies, Dark Gifts, quests, Darkmoon Prizes, rewards, and Trinkets | `/api/v1/libraries/{library}/by-dbf/{dbf}` or the corresponding exact library route |
| Timewarped/Chronomal cards | `/api/v1/timewarped-cards/by-dbf/{dbf}` or the exact `card_id` route |
| Mechanics, card types, minion types, formats, and library labels | inspect localized `name_ru` values directly from `/api/v1/meta` or from the exact resolved entity; this is a metadata evidence step, not a `hearthstone_names.py` capability |
| Any mode or entity not listed above | select the matching collection from `/api/v1` or the current KHS API index; if there is no exact localized record, keep it unresolved |

A reader-facing entity name passes the gate only when the returned identity matches the expected entity and mode namespace and the KHS record contains a non-empty Russian value such as `name.ru` or `name_ru`. An English field, internal slug, machine transliteration, approximate text match, or a model-generated translation never passes the gate. Preserve the KHS spelling, punctuation, capitalization, and official localized mechanic wording; do not “improve” it editorially.

Name resolution and mode legality are separate claims. For example, resolving a card in the constructed catalog does not prove that it is currently legal in Twist or Arena, and resolving a Battlegrounds entity does not prove that it is in the active pool. Establish legality, pool status, patch, and season independently.

For every attempted resolution, retain at least these fields in the evidence base:

```text
mode, entity_type, source_name_original, source_language,
dbf_id, card_id, khs_endpoint, khs_name_ru, khs_updated_at,
resolved_at, resolution_status, unresolved_reason
```

Use `resolution_status: resolved` only after the gate passes. Otherwise use `resolution_status: unresolved` with a concrete reason such as `not_found`, `missing_ru_name`, `ambiguous_identity`, `mode_conflict`, `api_unavailable`, or `schema_invalid`. Keep the original source form and DBF/card ID when available; never invent a missing ID. Mechanics without a DBF ID retain the original term or slug plus the matching KHS metadata record.

An unresolved name may remain in the evidence appendix as `<original> [unresolved]`. In the main Russian copy, say that the Russian name was not confirmed through KHS and use a plain descriptive phrase only when it cannot be mistaken for an official name. Do not guess, translate by eye, or silently publish the English/Chinese name as Russian. DBF IDs, internal slugs, and API paths stay out of normal reader copy unless they are necessary to disambiguate an entity.

### Plain Russian for editor-ready copy

This is a contextual replacement dictionary, not a blind string substitution. It never changes an exact KHS-resolved entity name, a quotation, or the preserved original in the evidence base.

| Avoid in reader copy | Prefer in Russian |
|---|---|
| `Standard`, `Wild`, `Twist`, `Battlegrounds` | `стандартный формат`, `вольный формат`, `формат «Твист»`, `Поля сражений` |
| `deck`, `decklist`, `build`, `deck code` | `колода`, `список карт`, `вариант колоды`, `код колоды` |
| `minion`, `spell`, `Hero Power`, `buddy` | `существо`, `заклинание`, `сила героя`, `напарник` |
| `tribe`, `minion type`, `Tavern` | `тип существа`, `тип существа`, `таверна` |
| `Discover`, `Battlecry`, `Deathrattle`, `Taunt` | exact KHS terms: `Раскопка`, `Боевой клич`, `Предсмертный хрип`, `Провокация` |
| `meta` | `игровая среда` or `популярные и сильные стратегии` |
| `matchup` | `противостояние`; state which side has the advantage |
| `mulligan` | `выбор стартовой руки`; say which cards to keep or replace |
| `win rate`, `play rate`, `pick rate` | `доля побед`, `частота использования`, `частота выбора` |
| `tier`, `tier list` | `уровень силы`, `список по силе`; use `уровень таверны` for Tavern Tier |
| `Trinket`, `Dark Gift` | `аксессуар`, `темный дар` |
| `tempo`, `value` | `текущее преимущество на поле`, `долгосрочная выгода` or the exact resource gained |
| `curve` | `распределение карт по стоимости` or `последовательность ходов`, according to context |
| `high-roll`, `low-roll`, `RNG` | `крайне удачный исход`, `неудачный исход`, `случайность` |
| `scaling`, `power spike` | `рост силы к поздним ходам`, `резкий прирост силы` |
| `board`, card/minion `stats`, `body` | `игровое поле`, `характеристики`, `существо`; use `статистика` for measured results |
| `lobby`, `composition` | `партия` or `состав участников`, `состав существ` or `стратегия` |
| `pivot` | `смена стратегии` |
| `tech card`, `counter`, `counterplay` | `карта против конкретной стратегии`, `эффективный ответ`, `способ противодействия` |
| `win condition`, `lethal` | `условие победы`, `достаточный для победы урон` |
| `buff`, `nerf` | `усиление`, `ослабление` |
| `trigger`, `proc` | `срабатывание эффекта` |
| `roll`, `reroll`, `freeze` in Battlegrounds | `обновление таверны`, `повторное обновление`, `заморозка предложений в таверне` |
| `economy`, `econ` | `управление золотом` or name the relevant resource |
| `token` | `созданная карта`, `призванное существо`, or the exact entity type |
| `draw`, `removal`, `AoE` | `добор карт`, `устранение угрозы`, `массовый урон` or `эффект по нескольким целям` |
| bare `pool` | name the exact meaning: `доступные предложения`, `общий запас копий`, `набор создаваемых сущностей`, or `активный набор контента` |

Official Russian names of mechanics and properties from KHS remain unchanged. At their first use in a document, immediately add a brief plain-Russian explanation; later occurrences may use the official term alone. Apply the same rule to any genuinely useful common player term, for example: `Раскопка — выбор одной из трех предложенных карт`, `Предсмертный хрип — эффект после гибели существа`, `мета — самые распространенные и сильные стратегии`, `архетип — устойчивый тип колоды с общим планом`, `агро-колода — колода для быстрой победы`, `контроль-колода — колода для сдерживания соперника и победы за счет поздних ресурсов`, or `MMR — внутренний рейтинг подбора соперников`. Prefer the plain explanation alone when the term adds no value.

Before delivery, scan Russian reader-facing copy for unexplained English words and transliterated jargon. Proper names resolved by KHS, URLs, source titles, and explicitly marked unresolved originals in the evidence appendix are the only routine exceptions.

In particular, call a change from one game plan or composition to another `смена стратегии`; never use `пивот` in reader-facing Russian. Use `выбор стартовой руки`, not `муллиган`, and explain which cards to keep or replace.

### Disambiguate “pool”

In Hearthstone, “pool” is overloaded. Before searching, split the applicable meanings, for example:

- offer-eligibility pool: which entities can be offered under turn, tier, tribe, text, hero, lobby, and prior-action constraints;
- finite shared-copy pool: whether obtaining an entity consumes one of the Tavern's limited copies;
- generation pool: which entities may be created outside the Tavern;
- active content pool: which cards, heroes, tribes, or systems are enabled in the current patch.

Evidence about one pool does not establish another. If official rules document eligibility but not copy depletion, keep the latter unresolved or validate it with a current controlled test.

## Constructed deck guide map

When the user requests a guide to a constructed archetype, first show a concise `Структура поиска` and then continue automatically. Adapt the following map to the archetype and omit only sections that are genuinely irrelevant:

1. **Why the deck matters now** — current format, patch, expansion, recent changes, popularity, strength, and the audience/rank range for the guide.
2. **Current builds and deck codes** — collect several current lists, preserve their dates, rank/region/sample filters, validate each code, and resolve every publishable Russian card name through KHS.
3. **Which build is stronger and for whom** — compare candidates under matching filters; define “stronger” before choosing, and distinguish overall results from a small high-rank sample or one creator's preference.
4. **Why each card is included** — core cards, flexible slots, substitutions, interactions, resource roles, and choices that distinguish one build from another.
5. **Choice of starting hand** — general keeps, conditional keeps, matchup-specific keeps, and cards to replace; combine comparable statistics with current expert reasoning.
6. **Game plan** — early, middle, and late stages; resource use, sequencing, conditions for aggression or restraint, and when a `смена стратегии` is justified.
7. **Key opposing decks** — measured matchup results where available, the reason each side has an advantage, tactical adjustments, and evidence against oversimplified advice.
8. **Common mistakes and advanced decisions** — recurring errors, difficult turns, counterexamples, and advice that changes by rank or build.
9. **Practical handoff** — recommended list and code, alternatives, patch/date boundary, unresolved questions, and concise source links.

Treat this outline as the search map, not a decorative final table of contents. Every section must map to answerable research leaves and a readiness condition. The introduction needs official/current context and statistics; build comparison needs comparable list-level data; starting-hand and matchup advice needs decision-level statistics when available; play sequencing and difficult decisions benefit from timestamped expert demonstrations.

For sections 3–8, give X and YouTube `high` emphasis when access is available and no tighter cost limit was requested. Search X for current build choices, direct expert statements, matchup adaptations, corrections, and disagreement. Search YouTube for current-patch guides, coaching, tournament or ladder demonstrations, and mistakes; attach only relevant timestamped segments. Compare independent creators instead of counting repeated reactions to one list or one dataset.

## Known venues and patch chronology

Two machine-readable files back the routing below. [hearthstone-sources.json](hearthstone-sources.json) lists official, statistical, community, creator, and Chinese venues with the query family each serves; `scripts/registry_seed.py RUN_DIRECTORY --apply` turns the entries for the run's mode into planned direct opens before any search-engine query, and `scripts/search_coverage.py` reports how many sources came from known venues. [hearthstone-patches.json](hearthstone-patches.json) is the patch timeline; `scripts/freshness_check.py RUN_DIRECTORY --strict` verifies that the declared client patch is the latest for the mode as of the run date, that every cited patch exists, and that a source predating the latest balance patch for the mode carries a stale, partially stale, historical, or version-compatible label; a timeline entry's `balance_modes` says which modes a patch actually changed, so a Battlegrounds source stays current across a constructed-only patch. Add a timeline entry the day a patch or hotfix ships, citing the official page. Registry presence is a routing aid, never evidence of authority for a specific claim, and creator qualification stays as observed until rank evidence is attached.

## Research flow

```text
Question
  -> mode
  -> patch and season
  -> mechanic/entity identity
  -> official data
  -> current statistics
  -> high-MMR/expert analysis
  -> community patterns
  -> synergies and counterexamples
  -> evidence matrix and conclusion
```

## Source routing

### Mechanics and rules

1. Blizzard official pages, patch notes, support/rules text, or first-party game data;
2. reliable datamining and reproducible current-patch testing;
3. qualified expert demonstrations;
4. community testing.

### Meta

Use large current statistics plus current high-MMR interpretation. Candidate services may include HSGuru, HSReplay, Firestone, or other transparent current datasets. Their presence in this list is not an endorsement: inspect methodology, filters, sample, access limits, and patch window for each claim.

### Edge interactions

Seek official wording plus reproducible testing or video evidence. Record exact board state, entity text, order of operations, patch, and whether the result may be a bug.

### Strategy

Combine current statistics, elite players, and bounded community consensus. Useful discovery venues may include Blizzard, `/r/BobsTavern`, Hearthstone subreddits, YouTube, X, tournament/VOD material, and specialist communities. Open and inspect the actual material.

If public decision-level statistics are unavailable, say so and cap the result at a conditional heuristic unless strong independent expert evidence supports more. Do not treat end-board composition, popularity, or isolated high-roll screenshots as evidence for the optimal decision path.

## Battlegrounds and Dark Gifts tree

For Dark Gifts research, consider applicable branches:

- official mechanic and pool generation;
- charges, timing, discover/pool rules, and Tavern Tier dependency;
- first, second, and later use separately;
- immediate tempo versus holding value;
- economy, combat survival, leveling curves, scaling, and cap/floor effects;
- heroes, tribes/minion types, cards/minions, spells, synergies, Trinkets/accessories, quests/anomalies when active;
- high-MMR practices and rank dependence;
- statistical evidence and selection bias;
- common mistakes, failure modes, and counterexamples;
- patch/season changes that alter any branch.

Do not assume every branch is active in the current season; verify terminology and availability first.

## Frequent failure modes

- mixing Standard cards with Battlegrounds entities of the same name;
- using current-looking pages whose embedded stats cross a balance patch;
- treating top-lobby practice as universal ladder advice;
- interpreting end-board composition data as a successful build path without survivorship caveats;
- using a creator's old video after a pool, armor, damage, cost, tier, or text change;
- treating localization differences as separate mechanics;
- assuming a community term maps exactly to Blizzard's official term.

## Current-patch-only modifier

Exclude stale strategy and statistics. Older official mechanics may be `VERSION-COMPATIBLE` only after checking every relevant rule, tier, cost, pool, and timing dependency against the current patch.
