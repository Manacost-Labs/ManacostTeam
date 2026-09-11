# Chinese Hearthstone Intelligence

## Purpose and boundary

Use this module when Chinese Hearthstone sources are material to a current-patch research question. It ingests public source content into structured, provenance-preserving records; it does not write the final guide, claim that a crawler found the first creator in the world, or treat reposts as independent corroboration.

Built-in ChatGPT Search/Web remains the default discovery and source-inspection layer for interactive research. The local pipeline adds repeatable Chinese-source retrieval through Scrape.do when `SCRAPE_DO_API_TOKEN` is configured. Provider output is still untrusted source material and must pass the normal Claim → Evidence → Source workflow before it supports a conclusion.

## Supported profiles

| Profile | Domains | Role | Default polling interval |
|---|---|---|---:|
| `iyingdi` | `iyingdi.com`, `battle.com`, `mob.battle.com` | primary articles and CN statistics | 3 hours |
| `taptap` | `taptap.cn`, `taptap.com` | community threads, app 213 | 2 hours |
| `nga` | `nga.cn`, `bbs.nga.cn` | community threads and guides | 2 hours |
| `bilibili` | `bilibili.com`, `b23.tv` | videos, subtitles, selected comments | 1 hour |
| `gamersky` | `gamersky.com` | secondary articles and repost discovery | 12 hours |
| `17173` | `17173.com` | compilations and multi-deck articles | 12 hours |

Poll intervals are configuration defaults, not a scheduler. A host application owns queues, clocks, durable state, and concurrency.

## Runtime flow

```text
discover listing or candidate URL
  -> serve a still-fresh validated cache entry when available
  -> reserve local Scrape.do rate capacity
  -> fetch with Scrape.do normal mode
  -> validate status and actual content
  -> render / super / super+render only when needed
  -> clean HTML while retaining original Chinese
  -> extract statistics, deckstrings, provenance, guide evidence
  -> decode deckstrings and create canonical fingerprints
  -> resolve DBF IDs through api.kolodahearthstone.com
  -> classify origin and source lineage
  -> deduplicate source, content, deck, and repost lineage
  -> pass structured evidence to the normal research pipeline
```

The code is in `scripts/chinese_hearthstone.py`. It has no third-party runtime dependency.

## Retrieval and cost control

The Scrape.do client always starts with the cheapest mode and sets `disableRetry=true`; ResearchTeam owns the bounded retry policy. It tests the returned body rather than trusting HTTP 200. CAPTCHA/challenge text, login walls, access blocks, thin pages, malformed JSON, and empty SPA shells remain failures.

Successful public responses are cached privately by profile plus canonical URL. The default TTL is the profile polling interval; `cache_ttl_seconds` can override it, `--refresh` bypasses a fresh entry and replaces it after success, and `--no-cache` disables both reads and writes. Cache files use opaque SHA-256 names, mode `0600`, contain no provider credential or provider request URL, and are revalidated before use. Failed, blocked, authenticated, and rate-limited responses are never cached.

Before every network attempt, a cross-process sliding-window limiter reserves local capacity. The default is 30 requests per minute with at most 30 seconds of waiting. If capacity cannot be obtained in that budget, the operation returns `RATE_LIMITED` with `local_rate_limit` and makes no provider request. These are conservative local budget controls, not a claim about the account's plan-specific concurrency. A host may tune them through the example config while remaining within its Scrape.do plan.

The attempt ledger records:

- mode;
- target status;
- elapsed milliseconds;
- `Retry-After` when present;
- `Scrape.do-Request-Cost` when present;
- `Scrape.do-Remaining-Credits` when present;
- provider status separately from target status;
- time spent waiting for local rate capacity;
- content-validation reasons.

The public fetch envelope includes structured `diagnostics`: cache state and age, actual network-attempt count, reported credits used, latest remaining credits, unattributed-cost attempts, and stable diagnostic codes. A cache hit has zero network attempts and never repeats historical provider cost.

`Scrape.do-Initial-Status-Code` is treated as the target status. Provider `404/410` results stop immediately and never escalate. Authentication and rate-limit failures also stop rather than changing to a more expensive mode. Missing cost attribution is visible in metrics and is never silently counted as free.

Scrape.do API mode requires its token as an authentication query parameter. The client constructs that provider URL only inside the transport boundary, never returns it, never logs it, and replaces network failures with redacted diagnostics. Do not add debug logging for `Request.full_url`.

This behavior follows the current [Scrape.do API parameters](https://scrape.do/documentation/), [status code](https://scrape.do/documentation/api-response/status-codes/), [retry](https://scrape.do/documentation/api-response/retry-settings/), and [response header](https://scrape.do/documentation/api-response/response-output/) contracts. It also adopts the measured provider/target separation and dead-URL cost rules from the MIT-licensed [Manacost Labs ParsesUnix](https://github.com/Manacost-Labs/ParsesUnix) adapter.

## Deck intelligence

Deckstrings are detected and decoded deterministically as base64 plus unsigned varints. The parser validates the header, version, format, hero, card counts, DBF IDs, trailing data, and sideboard block. It never asks an LLM to parse a deck code.

Structural validity and deck-size assessment are separate. A non-30 encoded total is emitted as `SPECIAL_OR_UNVERIFIED` with a `validation_warning`, not treated as corrupt data. Rulebreaker and other client-supported mechanics can embed auxiliary or generated cards. When DBF resolution finds non-collectible entries, the resolved assessment becomes `SPECIAL_ENCODING_DETECTED`; unknown special sizes remain visible for review.

Each valid deck receives a SHA-256 fingerprint over sorted `DBF_ID:count` pairs. Pairwise comparison uses card-copy overlap:

| Shared copies in two 30-card decks | Relationship |
|---:|---|
| 30 | `EXACT` |
| 29 | `NEAR_DUPLICATE` |
| 28 | `VARIANT` |
| 26–27 | `ARCHETYPE_VARIANT` |
| otherwise | `DISTINCT` |

Added and removed DBF IDs remain explicit.

Card names and classes come from the read-only `GET /api/v1/constructed-cards/by-dbf/{dbf}` contract at [api.kolodahearthstone.com](https://github.com/Manacost-Labs/api.kolodahearthstone.com). Public reads work without a token. If `KHS_API_TOKEN` is configured, it is sent only in `Authorization: Bearer` and never appears in output. A missing DBF ID remains a visible validation gap.

For Russian output across constructed and other Hearthstone modes, use `scripts/hearthstone_names.py --dbf DBF_ID --kind KIND`. The resolver supports constructed cards, Battlegrounds cards and heroes, timewarped cards, anomalies, Dark Gifts, quests, Darkmoon Prizes, rewards, and trinkets through their mode-specific public read-only endpoints. A missing Russian name is a localization gap, never permission to invent a translation.

The deck format implementation is compatible with the documented [HearthSim deckstring format](https://hearthsim.info/docs/deckstrings/) and the MIT/ISC-attributed [Manacost Labs deckstring codecs](https://github.com/Manacost-Labs/hearthstone-deckstrings).

## Origin classification

The classifier emits only:

- `CN_ORIGINAL`;
- `CN_VARIANT`;
- `CN_META`;
- `WESTERN_REPOST`;
- `UNKNOWN`.

An explicit `自创`, `原创`, `自己构筑`, or `本人构筑` marker is not enough for `CN_ORIGINAL`. The record must also have a Chinese ladder/result signal and a completed western-match check with no match. `CN_VARIANT` requires a measured deck comparison. `CN_META` requires CN-region statistics. `WESTERN_REPOST` requires attribution/repost signals tied to a known western source.

The crawler stores `earliest_observed_source` with an observation timestamp and the scope `crawler_observation_only`. It never upgrades this into a global authorship claim.

## Structured extraction

The deterministic statistics parser recognizes:

```text
服务器, 总场数, 赢, 输, 胜率, 排名区间,
平均对局时长, 最后更新时间
```

Region mapping is `国服 → CN`, `欧服 → EU`, `美服 → NA`, and `亚服 → ASIA`. The internal terminology dictionary also covers deck, mode, guide, class, ladder, matchup, mulligan, patch, data, author, and source concepts. It assists parsing and classification; it is not UI copy and does not replace translation review.

Schema 1.1 keeps the source-level deduplicated `decks` and first-observed `statistics` fields for compatibility and adds `deck_records`. Each record binds one deck occurrence to its nearest Chinese archetype label, statistics block, stable `record_id`, source locator, and record-level CN classification. Repeated codes remain separate records when their server or sample context differs. Multi-deck reports must use `deck_records`; source-level statistics alone do not establish that every deck on the page shares the first sample.

Page metadata is extracted separately from gameplay data. JSON-LD and explicit HTML metadata take precedence, while visible Yingdi bylines and `YYYYMMDD` title dates are bounded fallbacks. `page_metadata.field_sources` records where author, publisher, publication time, and modification time came from. `published_at` must never be inferred from `最后更新时间`; that field belongs to the individual deck record's statistics. Partial attributions such as `来源：公众号` remain `PARTIAL` rather than being promoted to a verified original URL.

HTML cleaning removes common navigation, footer, ad, login, recommendation, script, style, SVG, and repeated-layout blocks. Original Chinese clean text and its content hash remain available. Raw HTML is only emitted when the operator explicitly requests it; never persist authenticated, private, or restricted content.

## GuideHunter and Bilibili

`guide-queries` produces exact, localized query families across NGA, TapTap, Bilibili, and IYingdi using `留牌`, `对局`, `攻略`, `国服`, `上分`, and `构筑`. The ingestion contract separates gameplan, mulligan, matchups, card choices, replacements, combos, win conditions, mistakes, meta observations, and author claims.

Bilibili JSON normalization preserves metadata, deckstrings in descriptions, subtitle segments with start/end timestamps, and selected strategy-bearing comments. Each guide evidence record keeps original Chinese, optional Russian translation, source URL, lineage, category, stance, collection time, and confidence. Ingestion must not generate the final guide.

## Commands

```text
# Configuration without printing secret values
python3 scripts/chinese_hearthstone.py doctor

# Offline source inspection
python3 scripts/chinese_hearthstone.py inspect \
  --source iyingdi \
  --url https://www.iyingdi.com/example \
  --file tests/fixtures/chinese/iyingdi_cn_meta.html

# One live public fetch through Scrape.do
python3 scripts/chinese_hearthstone.py fetch \
  --source iyingdi \
  --url https://www.iyingdi.com/example \
  --resolve-cards \
  --output /authorized/path/iyingdi.json

# Force a live refresh, replacing the cache only after success
python3 scripts/chinese_hearthstone.py fetch \
  --source iyingdi \
  --url https://www.iyingdi.com/example \
  --refresh

# Deterministic deck decode and DBF resolution
python3 scripts/chinese_hearthstone.py deck DECKSTRING --resolve-cards

# Localized GuideHunter queries
python3 scripts/chinese_hearthstone.py guide-queries --archetype "控制战"
```

The example config is `references/examples/chinese-hearthstone-config.json`. Secrets belong only in environment variables or a secret manager; never put them in that file, command arguments, fixtures, research bundles, or Git.

## Persistence contract

A host that persists output should retain:

```text
source, source_id, source_url, fetched_at, published_at, author, title,
language, clean_text_zh, content_hash, provenance, classification,
deck fingerprint, source-to-deck relationships, lineage_hint,
earliest_observed_source, last successful fetch, last content hash,
last extracted deck fingerprints, parser version
```

Deduplicate content by canonical URL plus content hash, decks by fingerprint, and reposts by lineage. A compilation containing 20 valid codes creates 20 source-to-deck relationships.

## Health and metrics

`pipeline_metrics()` exposes fetched/blocked/rate-limited counts, local rate-limit events and wait time, cache hits/misses, network requests, successes by mode, fallback rate, parser success, valid/invalid/unique/duplicate decks, classifications, provenance rate, average attributed credits, and unattributed-cost attempts. `site_health()` reports the latest state and last-good timestamp for each source profile.

Monitor at least:

- discovery and fetch volume;
- success per escalation mode;
- block, rate-limit, parser-failure, and browser-fallback rates;
- deckstring validity and deduplication;
- CN classification distribution;
- provenance coverage;
- actual and unattributed Scrape.do cost;
- cache effectiveness and avoided network calls;
- local rate-limit events and wait time;
- per-site latest state and last-good time.

## Verification boundary

CI is offline. Fixtures cover valid/invalid/multiple deckstrings, per-deck statistics binding, special-size warnings, non-collectible special encodings, 20-code compilations, Chinese statistics, lineage, 30/29/28/26-card similarity, classifier boundaries, CAPTCHA/SPA/403/429/dead URLs, Scrape.do escalation, cache hit/staleness, local rate limiting, secret-safe diagnostics, Koloda API normalization, Bilibili timestamp evidence, query generation, and score weights.

Live source layouts and provider behavior can drift. A live contract check is operational evidence, not a deterministic CI gate. If a site profile fails content validation, report that source as partial or blocked and cap downstream confidence.
