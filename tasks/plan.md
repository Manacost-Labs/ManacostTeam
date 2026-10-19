# Research and editor improvements — 2026-10-19

## Scope and baseline

Implement the owner's `manacostteam-research-editor-codex.md` (discussion 2026-10-18).
Starting HEAD: `4ebfd16d848615f59db7711777eae81c0ecb9568`; main, one worktree,
clean status/diff. Preserve legacy valid inputs, factual guards, source identity,
and module independence. No production deployment or release publication.

## Ownership and dependencies

- Research worker: successful study/progress/novelty, adaptive questions, RU/EN
  queries, freshness policy and their tests/docs; no handoff compiler edits.
- Editor worker: scoped corrections, Python/Go rule parity, diagnostic voice
  metrics, function-aware style retrieval and corresponding CLI/tests/docs.
- Main agent: handoff compiler, Python publication review/run, Go pipeline,
  role instructions, integration tests and final checks.
- Evaluation worker: existing benchmark/Promptfoo metrics, frozen comparison
  materials and pilot preparation. Human annotations must remain pending.
- Independent read-only review after integration, with corrections by owners.

Contract checkpoint: keep schema_version=1 for additive optional metadata and
cards; retain legacy exact-string examples. Rich evidence must survive JSON
decode/re-encode, prompt construction and saved publication artifacts. No
automatic semantic approval is inferred from IDs, hashes or exact strings.

## Ordered verification slices

1. Freeze baseline and comparison inputs; reproduce audit findings with focused
   tests. Record each of the twelve observations as confirmed/already fixed/
   inconclusive in the implementation report.
2. Fix search progress and scoped editorial rules; failing regression first.
3. Carry evidence provenance, inference basis, sample/time restrictions and
   grounded decision cards across research → Python → Go → writer/reviewer.
4. Improve question planning/freshness and bounded followups; retain visible
   unknowns and budget exhaustion. Assess semantic retrieval before any new
   dependency; reranking is conditional on a measured gap.
5. Improve writer/literary role instructions, strengths/keep_spans and reader
   review; preserve good source text and allow unchanged output.
6. Run focused and module checks, prepared comparison and independent review;
   fix regressions, inspect staged diff, commit scoped changes and push origin.

## Acceptance and evidence

- Failed access cannot count as inspected coverage or saturation; new conditions,
  exceptions and counterevidence reset content-based saturation.
- Actual language-specific queries and explicit official-registry verification
  dates, historical/current scope and unresolved freshness.
- Provenance and grounded decision-card fields reach all consumers without
  silent loss; unsupported additions and certainty drift still fail.
- Contextual corrections and voice diagnostics agree before/after generation.
- Calm strong style examples, self-exclusion, deduplication and context limits.
- Meaningful tests for changed contracts; no literal-prompt mirror tests.
- Before/after behavior evidence and honest pilot status. Synthetic fixtures,
  model evaluations and human preferences are reported separately.

## Tools and boundaries

Use local Python virtualenv, unittest/pytest/Ruff, Go test/vet/build and Node eval
tests. Existing dependencies only. Go was initially absent from PATH; locate or
install a local official toolchain before claiming Go validation. Serena and
codegraph unavailable/not configured; no .codegraph present. No current-game
fact claims required for code changes. GitHub checks use available CLI/MCP.

Applied skills: manacost-monorepo-gate; EditorTeam using-agent-skills,
planning-and-task-breakdown, test-driven-development,
verification-before-completion, git-workflow-and-versioning,
context-engineering and api-and-interface-design; Go service-boundaries;
skill-package-manager for versioned portable outputs.
Server-only skillctl/ai-check paths are unavailable in this Windows checkout;
use the imported `.agents/profile.yaml` and its actual module gates.

Context gate: exact `5.6 Luna` rejected by tool; initial read-only fallback ran
on gpt-5.6-sol. Owner subsequently requested gpt-6-luna for context; the context
gate was restarted on that model. Preserve this preference for context work.

Risks: over-tight schemas breaking old fixtures; evidence dropped by Go typed
models; new counters mistaken for truth; style examples leaking facts; synthetic
test success mistaken for measured editorial quality. Address each with bounded
validation and clearly separated verification evidence.
