# Search Recall Benchmark

The release benchmark under `../benchmark` proves that a finished bundle is traceable. This benchmark asks a different question: did the search look where a competent researcher had to look?

## Files

- `cases.jsonl`: ten Hearthstone cases, oracle version `1.0`. Each case lists gold sources: exact official pages by canonical URL, or venues by host and path prefix, each with a `why` and a `source_class`.
- `results.jsonl`: links from cases to local bundles. Bundles under `work/` are not tracked, so scoring runs locally; CI validates only the case definitions.

## Validate and score

```text
python3 ../../deep-research/scripts/validate_recall.py . --stage plan
python3 ../../deep-research/scripts/validate_recall.py . --stage score
python3 ../../deep-research/scripts/validate_recall.py . --stage score --json
```

A scored case passes when recall against its gold set is at least 0.9 and no source was admitted as snippet-only. The report also shows how many queries the run needed before the first official or statistics source. Cases without a linked bundle are `not_run` and do not fail the gate unless `--require-all` is given.

Each case can also be run as a model trial: `model_trial.py start DIR --case RECALL-006 --host codex --model NAME` prepares the bundle and task, and `model_trial.py score DIR` scores it against this gold set together with the other gates.

Gold sets are defined from the domain, not copied from a bundle: patch notes and developer posts that governed the question on the as-of date, the first-party statistics host, and the community venue for the mode. Add a case only with real URLs that were inspected.
