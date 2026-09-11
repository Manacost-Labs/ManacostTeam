# Search Strategy

## Tool contract

Use the built-in ChatGPT Search/Web capability as the default for internet research. Use Search to discover candidates and Web/open-page access to inspect sources. When a branch requires direct Reddit/X access, TranscriptAPI YouTube search/transcripts, or TinyFish extraction, apply [optional source providers](source-providers.md) without changing this evidence boundary. Search-result text, snippets, answer cards, provider search results, and AI summaries are discovery metadata, not verified evidence.

Prefer opening the original URL. If the original is unavailable, try its official mirror or archive, then seek independent confirmation. Record unresolved access limitations and lower confidence when the missing source matters.

## Search from research-tree leaves

For every material leaf, create a query set from the applicable families:

| Family | Purpose | Query patterns |
|---|---|---|
| general | map terminology and candidate sources | `[topic] strategy`, `[topic] explained` |
| primary | locate original rules or statements | `[topic] official`, `[topic] documentation`, `[topic] patch notes` |
| statistics | locate datasets and measurements | `[topic] statistics`, `[topic] winrate`, `[topic] data`, `[metric] methodology` |
| experts | find attributable analysis | `[topic] expert`, `[topic] high rank`, `[topic] guide`, `[expert name] [topic]` |
| Reddit/forums | sample community reasoning | `site:reddit.com [topic]`, `[topic] forum discussion` |
| X/social | find current statements and debate | `[topic] [author]`, `[topic] discussion`, `site:x.com [topic]` |
| YouTube | locate demonstrations and long-form analysis | `[game] [patch] [topic] guide`, `[verified player] [topic]`, `[topic] tournament VOD`, `[topic] coaching`, `[topic] mistakes` |
| mistakes | expose failure modes | `[topic] mistakes`, `[topic] avoid`, `[topic] common error` |
| synergies | find interaction effects | `[topic] synergy`, `[topic] interaction`, `[A] [B] interaction` |
| counterargument | challenge the leading hypothesis | `[topic] overrated`, `[topic] weak`, `why not [claim]`, `[claim] wrong` |
| freshness | anchor version and date | `[topic] [current year]`, `[topic] [patch]`, `[topic] [season/version]` |

Patterns are prompts for expansion, not literal mandatory queries.

## Search from the deliverable outline

For guides and articles, map every decision-relevant future section to research-tree leaves before generating queries. A section is not covered merely because the topic appears in a broad search result. Record the question the section must answer, its minimum evidence classes, its X/YouTube relevance, and the evidence that could reverse the preliminary advice.

Show the user a compact `Структура поиска` before the first search, using ordinary content labels rather than internal IDs. Continue immediately unless the user explicitly requested a planning checkpoint. Change the map when the evidence reveals a missing section or shows that two planned sections answer the same question.

## High-emphasis X and YouTube passes

For strategy guides, use `high` emphasis for X and YouTube when access is available and no tighter cost limit was requested. This means more useful query angles and independent creators, not a fixed result quota.

- X: search the topic plus the current patch/version, named experts, concrete choices, alternatives, matchups, failure cases, and disagreement. Inspect the direct post and relevant reply/thread context; separate original analysis from reactions to the same upstream claim.
- YouTube: search the topic plus the current patch/version, qualified player or coach, guide, coaching/VOD, matchup, and mistakes. Inspect the video page and extract only the relevant timestamped transcript segments. Verify the gameplay patch separately from upload date.
- For central strategic advice, seek at least two independent qualified creator perspectives across X and YouTube when accessible. If the advice depends on an action sequence, aim to include a timestamped demonstration or explanation rather than relying only on short posts.
- Stop a section when additional qualified sources add no new reasoning, condition, counterexample, or confidence change. Report access gaps instead of compensating with unrelated volume.

## Evidence-availability gate

Before spending most of the search budget, test whether each required evidence class is actually accessible:

1. run at least two materially different targeted queries for the class when it is decision-critical;
2. try the likely primary owner or named database directly;
3. record `AVAILABLE`, `PARTIAL`, `BLOCKED`, or `NOT FOUND`, including paywalls, login requirements, missing filters, and version mismatch;
4. state how the result changes the research claim.

If decision-level statistics are not found, do not infer an optimum from popularity, final-board data, or community repetition. Deliver a conditional heuristic, a narrower descriptive conclusion, or an unresolved gap. Continue searching only when a new source family, vocabulary, access route, or version marker makes the next query materially different.

## Query expansion

Expand the user's words into:

- synonyms and antonyms;
- official and community terminology;
- alternative, previous, and localized names;
- English-language equivalents when the user asks in another language;
- mechanics, entities, authors, datasets, and products connected to the concept;
- current year, version, patch, season, expansion, jurisdiction, or population;
- pro and con formulations.

Example question: `When should I use the first Dark Gift?`

Possible expansions:

- `Dark Gift first use`
- `best timing Dark Gift`
- `should I save Dark Gift`
- `Dark Gift Tavern Tier`
- `Dark Gift early game`
- `Dark Gift high MMR`
- `Dark Gift strategy Reddit`
- `Dark Gift first charge guide`
- `why save Dark Gift`
- `Dark Gift mistakes`

## Pass discipline

1. Broad discovery identifies vocabulary, primary owners, datasets, experts, and disagreement.
2. Targeted collection opens the strongest candidates per branch.
3. Gap search uses only the latest gap list.
4. Contradiction search negates or reframes preliminary claims.
5. Freshness search tests change events and current applicability.
6. Audit search resolves only failed gates.

Do not repeat equivalent queries unless a new date/version, source family, language, or disconfirming frame makes them materially different.

## Generated query matrix

Do not hand-write one query per branch. In a persistent run, first seed the known venues of the domain with `scripts/registry_seed.py RUN_DIRECTORY --apply` so official pages, datasets, communities, and known creators are opened directly rather than rediscovered; then generate the matrix with `scripts/plan_queries.py RUN_DIRECTORY --language en --language ru --entity NAME --apply` after the sections and version markers are known. It expands every branch across the canonical families for the run depth, skips queries already in `queries.jsonl`, and writes `query-plan.jsonl`. Execute planned queries in priority order, record each in `queries.jsonl` with the canonical `pass`, `family`, and `language`, and log every seen result in `candidates.jsonl` with an `opened` or `rejected` decision and a canonical reason. Open pages with `scripts/fetch_source.py` so the snapshot, fingerprint, canonical URL, and query link are recorded automatically.

## Coverage log

Run `scripts/search_coverage.py RUN_DIRECTORY` after every pass and `--strict` before the final audit. It reports families per branch, planned-but-unexecuted queries, candidate open rate, host and lineage concentration, challenge coverage for critical and material claims, and fingerprint coverage. A missing required family on a material branch or a critical claim without a challenge search is a blocking finding.

The report also attributes every claim to the earliest query whose results supported it and counts trailing zero-yield queries per branch; a branch counts as saturated after three consecutive queries that produced no new claim, and the report warns until then. Run `scripts/lineage_suggest.py` before counting corroboration so near-duplicate snapshots share one lineage.

For deep or exhaustive research, the report replaces a hand-kept log of each material branch:

- query families attempted;
- useful and rejected source IDs;
- source classes still missing;
- access failures;
- last new claim or counterargument;
- saturation status.

The log prevents high-volume searching in one easy branch from hiding untouched branches.

## Special media handling

- For X, Reddit, and forums, open the actual post or thread where possible and preserve author, timestamp, thread context, and edit/deletion risk.
- For YouTube, verify the page date and author/channel identity, inspect the relevant transcript/video segment, and record a timestamp; a title, thumbnail, view count, or search position is not evidence.
- For PDFs, inspect the exact page or table and verify surrounding definitions.
- For live pages, record access date and version markers because content may change.
