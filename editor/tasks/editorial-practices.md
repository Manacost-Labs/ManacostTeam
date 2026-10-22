# Contextual editorial review: implementation plan

User request: implement all practices from the Russian Wikipedia essay without
word bans, preserving facts, conditions and author voice.

- [x] Map all 26 subsections to contextual questions, legitimate uses and verification.
- [x] Add evidence-bound review contracts for substance, logic, sources and preservation.
- [x] Enforce the contract in new publication runs, CLI and Go critic; preserve old receipts.
- [x] Make marker counts advisory; update writer/reviewer instructions and portable resources.
- [x] Test missing/forged evidence, repairs, benign style and legacy compatibility.
- [x] Independent Luna review; resolve findings and run relevant full gates.
- [x] Build versioned packages and verify portability; final Git receipts record commit/push.

Evidence boundary: schema and fixture tests verify enforcement, not the truth of
a reviewer's judgment or measured improvement in prose. No AI authorship score.
Source: https://ru.wikipedia.org/w/index.php?oldid=155487940 (examined 2026-10-22).

Review fixes: standalone CLI now validates the complete handoff, snapshot
provenance/content hashes and claim attestations. Malformed reports fail closed.
URL grounding normalizes only host/scheme casing and an empty root path; path
slashes, queries and fragments stay distinct. Tests pin the exact oldid/26 IDs.
Go critic receives its explicit output contract and evidence scope. Ordinary
constructs remain valid; issue evidence flows into local repair.

Tooling: temporary official Go 1.26.10 windows-amd64, SHA256
7ecd2d7260e82c59bcbd7f1077a07cee2dea607295b858df67195a1e4e09629b,
downloaded from go.dev and checked against its release metadata. No global install.
Server-specific /srv skillctl/ai-check tooling is unavailable on this Windows
checkout; project Python/Go/package gates are used instead.

Verification: full EditorTeam pytest suite 924 passed / 36 skipped; final
additional negative-verdict regression plus contextual suite 49 passed.
Repository unittest suite 230 run / 1 skipped, including unpacked Python -S
smokes for both skills. Ruff and configuration validation passed. Selftest
on 49 author guides passed, with 0 rewrite-gate rejections. Go test/vet/build
passed after final prompt/scope fixes. Reproducible release 1.17.0 packages
and catalog parity checked. These are implementation checks, not a measured
quality improvement or live model/source-verification experiment.
