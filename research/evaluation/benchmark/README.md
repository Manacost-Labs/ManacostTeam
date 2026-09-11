# Deep Research 1.0 Benchmark

This benchmark is the release oracle for `deep-research` 1.0. It contains 20 live Search/Web cases across five domains plus two controlled adversarial cases.

## Files

- `cases.jsonl`: immutable case definitions for oracle version `1.0`.
- `results.jsonl`: derived evaluations linked to the completed bundles under `runs/`.
- `runs/`: schema 1.1 bundles with snapshots, source fingerprints, claim links, and semantic audits.
- `fixtures/`: local adversarial content for cases that must not depend on a hostile public page.

## Validate

```text
python3 ../../deep-research/scripts/validate_benchmark.py . --stage plan
python3 ../../deep-research/scripts/generate_benchmark_results.py . --apply
python3 ../../deep-research/scripts/validate_benchmark.py . --stage release
```

`release` validates every linked bundle and recomputes its metrics; edited self-reported counts are rejected. It enforces at least 20 live cases, five domains, full critical-claim traceability, no invented sources, no snippet evidence, no false-ready decisions, no web-safety violations, complete mutable-source fingerprinting, and at least 95% material semantic support.
