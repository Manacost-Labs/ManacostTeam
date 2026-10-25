# Search Recall Benchmark

The release benchmark under `../benchmark` proves that a finished bundle is traceable. This benchmark asks a different question: did the search look where a competent researcher had to look? Recall against a gold set is measurable; "everything was found" is not, so the benchmark measures recall per source class and the coverage map records where a run did not look.

## Files

- `cases.jsonl`: Hearthstone cases, oracle version `1.1`, across meta reports, deck guides, Battlegrounds, Arena, patches, news and esports. Each gold source is an exact page (canonical URL, optional `aliases`) or a venue (host and path prefix with a `probe_url` inside it), with a `why`, a `source_class` and the date and route it was opened (`verified_at`, `verified_via`: `direct`, `tinyfish` or `browser`). Blizzard articles match across `hearthstone.blizzard.com`, `playhearthstone.com` and `news.blizzard.com` by article id; the Chinese mirror on `hs.blizzard.cn` is a separate `chinese` gold.
- Source classes: `official`, `statistics`, `reddit`, `x`, `youtube`, `chinese`, `podcast`, `web` (from `deep-research/scripts/source_classes.py`).
- `results.jsonl`: links from cases to local research bundles. Bundles under `work/` are not tracked, so bundle scoring runs locally; CI validates only the case definitions.
- `history.jsonl`: every recorded run with its label, mode, planner, git commit, overall and per-class recall, and per-case results.

## One command

```text
python3 ../../deep-research/scripts/run_recall.py score --record LABEL         # linked bundles
python3 ../../deep-research/scripts/run_recall.py search --planner both --record --label LABEL
python3 ../../deep-research/scripts/run_recall.py history
python3 ../../deep-research/scripts/run_recall.py check-gold
```

`score` reports recall and discovery recall per case and per source class. `search` runs a live discovery search for every case with `search_setup` (topic phrases in en/ru/zh, version markers, entity DBF ids): the `baseline` planner executes the previous en/ru `plan_queries.py` matrix verbatim in plan order; the `waves` planner runs `search_waves.py` waves with one executor per source class, en/ru/zh queries and localized card names, link following from opened pages, a refutation pass and the saturation stop. Both use the TinyFish adapter in `community_sources.py`, the same budget (search queries plus page opens) and a shared response cache under `build/recall/cache`, so repeated runs compare planners on identical results; `--offline` uses the cache only. Live recall is discovery-level: `discovery_recall` counts gold that surfaced in results, `recall` counts gold the run opened. Neither replaces a researched bundle's inspected recall. `check-gold` re-opens every gold URL or probe directly, with TinyFish for bot-protected pages.

The structural validator remains available:

```text
python3 ../../deep-research/scripts/validate_recall.py . --stage plan
python3 ../../deep-research/scripts/validate_recall.py . --stage score --json
```

A scored case passes when recall against its gold set is at least 0.9 and no source was admitted as snippet-only. Cases without a linked bundle are `not_run` and do not fail the gate unless `--require-all` is given.

Each case can also be run as a model trial: `model_trial.py start DIR --case RECALL-006 --host codex --model NAME` prepares the bundle and task, and `model_trial.py score DIR` scores it against this gold set together with the other gates.

## Adding cases

Gold sets are defined from the domain, not copied from a bundle: patch notes and developer posts that governed the question on the as-of date, the first-party statistics routes, the community venue for the mode, and the Chinese and podcast venues where they carry the topic. Add a gold source only after opening it; a page found only as a search snippet, or one behind a login or a bot check (NGA threads, HSGuru pages), is not verified and does not go in. Venue gold for X and YouTube is deliberate: both return a page for any path, so an exact post or video cannot be verified by opening it.
