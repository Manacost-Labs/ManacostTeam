# Changelog

## Unreleased

- Added `scripts/model_trial.py`: `start` prepares a schema 1.2 bundle from a recall case with registry opens, a query plan, and a self-contained `TASK.md` for any agent host (Codex, Claude Code, Gemini CLI, ChatGPT); `score` runs every deterministic gate and writes a transparent 0-100 scorecard; `compare` tabulates several trials side by side.

- Added a search-recall benchmark (`evaluation/recall`) with ten Hearthstone cases whose gold sources are official pages, first-party statistics hosts, and mode-specific community venues, plus `scripts/validate_recall.py`, which scores linked bundles on recall, snippet-only admissions, and queries-to-first-authoritative-source.
- `fetch_source.py --refresh SOURCE_ID` re-fetches an existing source in place, replacing the snapshot and fingerprint while keeping the researcher's descriptive fields; pages with too little readable text or JavaScript-shell markers are refused instead of recorded as full access.
- Added a GitHub Actions workflow running the unit suite, skill audit, release benchmark, semantic gold, recall case validation, a coverage smoke test, and a tracked-secret check on Python 3.12 and 3.13.

- Added `scripts/candidates.py` for recording rejected and deferred search results with canonical reasons, keyed by query and canonical URL; `fetch_source.py --query-id` now records the `opened` candidate automatically.
- Added `scripts/lineage_suggest.py`, which detects near-duplicate snapshots by word-shingle similarity and, with `--apply`, makes the later source adopt the earlier lineage with an audit trail.
- The search coverage report now attributes claims to the earliest query that found their support, reports yield per query and trailing zero-yield runs per branch, and marks a branch saturated only after three consecutive zero-yield queries.

- Added a Hearthstone source registry (`references/domains/hearthstone-sources.json`) with official, statistics, structured-data, community, creator, and Chinese venues, plus `scripts/registry_seed.py`, which plans direct opens by game mode before any search-engine query; the search coverage report now shows the share of sources from known venues and warns when fewer than two official or statistics hosts were used or when sources fall outside the registry.
- Added a machine-readable Hearthstone patch timeline (`references/domains/hearthstone-patches.json`) and `scripts/freshness_check.py`, which verifies the declared client patch against the latest entry for the run's mode, rejects unknown patch versions, and flags sources that predate the latest patch without a stale, historical, or version-compatible label.
- `plan_queries.py` now defaults to English and Russian templates for Hearthstone runs and reads `client_patch` and balance-patch keys from `current_context`; `exact_excerpt` may elide words with `...` when every fragment appears in order.

- Added bundle schema 1.2 (search integrity): canonical query `pass`/`family` values become errors, queries carry a `language`, an `exact_excerpt` is verified against the source snapshot, final validation requires verified excerpt anchors for critical/material evidence with snapshots and a `challenge_search` or challenging evidence for every critical claim, and `output_profile` is mandatory. New bundles initialize at 1.2; 1.1 bundles stay valid and upgrade through `migrate_research_bundle.py --to 1.2 --family-map`, which refuses to guess unmapped families and is reversible.
- The search coverage report now measures anchor coverage: evidence with a snapshot whose excerpt was found in it.

- Added measurable search coverage: canonical query `pass`/`family`/`language` values, an optional `candidates.jsonl` ledger of seen-and-rejected results with canonical reasons, a `challenge_search` claim field, and `scripts/search_coverage.py`, which reports families per branch, unexecuted planned queries, candidate open rate, host and lineage concentration, challenge coverage, and fingerprint coverage with a `--strict` gate.
- Added `scripts/plan_queries.py`, a deterministic query-matrix generator that expands plan sections or topics across families, English and Russian templates, entities, and version markers into `query-plan.jsonl` without duplicating executed queries.
- Added `scripts/fetch_source.py`, which fetches a public page without credentials, extracts readable text, stores the snapshot, verifies the SHA-256 fingerprint, derives a canonical URL and lineage hint, refuses duplicates, and links the source to the query that found it; `--file` ingests a page saved by the host tool.
- The bundle validator now warns on non-canonical query families and passes and validates `candidates.jsonl` references when present.

- Added additive editor-ready coverage contract `1.0`: stable `plan.json` sections; section links on queries, evidence, claims, and community records; output destinations only on evidence, claims, and community records; mandatory section-organized `useful-data.md` banks for `deep` and `exhaustive` runs; reader-visible IDs that cannot be satisfied through code, link destinations, HTML attributes, comments, or hidden HTML; substantive prose beyond link labels and inline code; evidence-matched visible-source checks; critical/material-main and covered-section support invariants; full manifest/plan/all-ledger/report/applicable-artifact hashing; present quick-bank validation; and backward compatibility for existing schema 1.1 bundles.
- Added outline-first guide planning: the Skill now shows a concise search structure before research, maps every future section to evidence requirements, and continues without an unnecessary approval pause.
- Added `creator-heavy` routing and high-emphasis, section-level X and YouTube passes for strategy guides, with independent-creator comparison, timestamps, freshness checks, and saturation limits.
- Added a constructed Hearthstone deck-guide map covering current relevance, comparable builds and codes, best-build criteria, card choices, starting hand, game plan, opposing decks, mistakes, and practical handoff in plain Russian.
- Added an `editor-ready` output profile for article, guide, and editorial research requests; raw evidence output now requires an explicit dossier or audit request.
- Added a separate Clarity Editor gate and persistent six-part preservation review so plain-language synthesis cannot weaken factual audit, citations, uncertainty, or provenance.
- Added editor-facing templates, a separate evidence appendix, and deterministic Markdown clarity validation.
- Added official Russian Hearthstone entity-name resolution through mode-specific `api.kolodahearthstone.com` endpoints, with DBF identity, safe token handling, and explicit localization gaps instead of improvised translations.
- Added a Russian Hearthstone terminology gate that replaces unexplained research and gaming anglicisms with plain language.
- Added a dependency-free Chinese Hearthstone ingestion pipeline for IYingdi, TapTap, NGA, Bilibili, GamerSky, and 17173.
- Added content-aware Scrape.do escalation with bounded retries, target/provider status separation, dead-URL stop rules, cost headers, redacted diagnostics, and browser-fallback state.
- Added deterministic Hearthstone deckstring decoding, validation, fingerprints, 30/29/28/26-card similarity, source-to-deck relationships, and added/removed DBF IDs.
- Added read-only DBF enrichment through `api.kolodahearthstone.com` with optional Bearer authorization from `KHS_API_TOKEN`.
- Added CN statistics, terminology, provenance, origin/repost classification, earliest-observed scope, GuideHunter queries, structured guide evidence, Bilibili timestamp normalization, scoring, health, and metrics contracts.
- Added offline Chinese HTML/JSON fixtures and regression coverage for multi-deck compilations, CAPTCHA/SPA/status failures, secret safety, lineage, classifiers, and card API normalization.
- Added optional read-only RedditAPI, GetXAPI, and TinyFish adapters with normalized JSON output and no stored credentials.
- Added TranscriptAPI YouTube discovery/transcript support and an explicitly labeled credential-free public-caption reserve route using the optional `youtube-transcript-api` package.
- Recorded live YouTube validation findings: transcript UI blocks do not prove captions are absent, automatic captions require domain-term verification, and upload date does not prove gameplay patch freshness.
- Added fail-fast local TinyFish limits for 30 searches and 150 fetched URLs per rolling minute.
- Added provider routing, platform-separation, cost/rate, incomplete-coverage, and third-party provenance rules.
- Documented the Google Research assessment: adopt AIS-style attribution methodology, but do not add BLEURT or ScaNN runtime dependencies without a measured need.
- Added offline regression tests for normalization, comment-tree completeness, risk flags, secret-safe diagnostics, and rate limiting.

## 1.0.0 — 2026-08-28

- Validated 22 release-oracle cases: 20 live ChatGPT Search/Web runs across five domains plus two adversarial fixtures.
- Added schema 1.1 source provenance, local snapshots, SHA-256 fingerprint verification, and reversible schema 1.0 migration.
- Added claim-level semantic/citation auditing and a scored adversarial gold set.
- Added derived benchmark results: release validation recomputes metrics from linked bundles and rejects self-reported metric tampering.
- Added operational `resume`, `compare`, deterministic `export`, and gated `release` commands.
- Added deterministic skill and evaluation archives with SHA-256 release manifests.
- Added explicit proprietary licensing and expanded regression coverage.

## 0.2.0 — 2026-08-28

- Added three live Search/Web evaluation runs for factual, strategic, and exhaustive research.
- Added an evidence-availability gate for missing statistics, experts, and primary evidence.
- Added mandatory disambiguation of overloaded research terms.
- Added Hearthstone-specific separation of offer, shared-copy, generation, and active-content pools.
- Added baseline-plus-patch-overlay freshness rules.
- Hardened bundle validation for execution/access timestamps and checkpoint gap lists.
- Added a regression test for missing query timestamps.

## 0.1.0 — 2026-08-28

- Initial evidence-first research protocol.
- Built-in ChatGPT Search/Web contract.
- Persistent research bundles with stable Claim → Evidence → Source links.
- Research Auditor, contradiction search, freshness, confidence, and domain adapters.
