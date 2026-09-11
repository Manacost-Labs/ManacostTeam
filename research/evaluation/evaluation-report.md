# Deep Research 1.0 Release Evaluation

Evaluation date: `2026-08-28`  
Skill version: `1.0.0`  
Internet capability: **built-in ChatGPT Search/Web**

## Outcome

The release oracle passes. It contains 20 live research runs across general research, software, Hearthstone, World of Warcraft, and consumer decisions, plus two controlled adversarial cases for prompt injection and duplicate source lineage.

| Gate | Result |
|---|---:|
| Cases | 22 |
| Live cases | 20 |
| Domains | 5 |
| Required categories | 7 / 7 |
| Critical claim traceability | 48 / 48 |
| Material semantic support | 7 / 7 |
| Mutable source fingerprints | 64 / 64 |
| Snippet evidence | 0 |
| False-ready decisions | 0 |
| Web-safety violations | 0 |
| Semantic gold field accuracy | 100% |
| Semantic gold verdict accuracy | 100% |
| Semantic gold P0 failures | 0 |
| Automated tests | 16 passing |

## Delivery behavior

Four cases correctly return `not_ready`: two Hearthstone requests with decision-critical evidence gaps and two adversarial fixtures. These are successful safety outcomes, not failed executions.

The release validator does not trust the reported metric file. It opens every linked schema 1.1 bundle, runs final validation, recomputes traceability, semantic support, fingerprints, snippet usage, false-ready decisions, and web-safety counts, then rejects mismatches.

## Reproducibility

- Every mutable source used by the benchmark has a preserved local snapshot and verified SHA-256 fingerprint.
- Release archives use sorted paths and normalized timestamps.
- Two independent release builds produced byte-identical archives.
- The packaged Skill and evaluation archives were extracted and revalidated outside the source tree.
- Official Skill package validation passed on the extracted artifact.

## Readiness decision

Version `1.0.0` is ready for local distribution and ChatGPT Work installation. It remains evidence-first: an individual investigation may still return `ready_with_warnings` or `not_ready` when current evidence is insufficient.
