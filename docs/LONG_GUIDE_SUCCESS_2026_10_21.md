# Long guide: name context, factual feedback and grammar

Status: **v60 achieved 3/3 joint API and independent factual/literary acceptance**
on the same original historical guide, with empty drafts and no manual article
edits. Earlier failed whole cohorts remain preserved. This small acceptance
sample does not establish universal long-guide reliability.

## Scope and baseline

The same historical Mozaki OTK Freeze Mage guide, source snapshot, original brief
and 61-claim handoff are reused. Every original request is identical to v56 and
starts with an empty draft and no candidate. The baseline v56 result was 1/3
joint acceptance. All old outcomes remain in their original ignored folders.
No published article, corpus example, raw source or generated guide is staged.

## Changes

- Name recognition separates closed grammatical wrappers from complete known
  name forms. A prepositional clause may contain two separate verified names,
  as in “До Полкелта Сфера”; arbitrary composition without that boundary, a
  third name, unknown roots, numbers and URLs still fail the guard. Closed
  pronouns, caption heads and neutral participles do not authorize card effects
  or replace full factual review.
- A complete checked review may report a wholly absent required claim as
  `insufficient`, with all four quotation keys explicitly present and empty.
  It produces a separate `repair_only` / `handoff_missing_claim` target using
  that claim and its permitted evidence. There is no fabricated candidate quote
  and no insertion tied to an unrelated passage. Missing/null quote keys,
  ungrounded contradictions, false nonempty negative quotes, foreign refs,
  duplicate/missing rows and fabricated unsupported quotations remain blocked.
- Faulty supported quotations can be omitted only from repair feedback. They
  never attest the article. The full positive factual validator and the limit
  of two author repairs are unchanged; every applied repair requires a fresh
  whole-text review of all required meanings, conditions and exceptions.
- Reconstruction checks lexical term presence without requiring the source
  repetition count. Whole-term, case-insensitive matching still rejects total
  omission and partial-word substitutes. Ordinary editing retains occurrence
  counts; numeric, stat and deck-code protections retain their contracts.
- Fact-review requirements expose Meaning, Action, Condition, Exception and
  Confidence independently. A shared writer/reviewer instruction preserves
  Action details beyond Meaning, including before-turn versus before-combo
  timing. No semantic reviewer override or re-vote was added.
- Codex transport retries only the exact failed capacity stream, with no
  assistant output or nonempty last-message file: at most three identical
  attempts and 5/10-second pauses within the original 900-second deadline.
  Completed factual/literary content, partial responses, timeouts, login, quota
  and malformed failures are never re-voted. Every live attempt is retained.
  Runtime and live harness share the retry helper and strict parser: one
  completed assistant message must agree with the last-message file, the
  terminal must be last, and tools or unexpected events are rejected.
- A closed native grammatical dictionary rejects eight whole-word erroneous
  forms of the indeclinable verified SCH_400 name “Мозаки”. It applies only
  within the existing Russian/Hearthstone gate, emits a literal repair target
  and does not change the article itself. The writer must preserve the action
  and condition even when a handoff contains a grammatical error. This is not
  a suffix rule granting inflections to unknown names; the initial entry is
  limited to that verified personal-name component.
- A native grammar check reports invalid number agreement such as “2 копию”.
  It does not choose between an ordinal and a quantity or change the article.
  The author must recover the intended meaning from the source. Valid counts,
  explicit ordinal endings and word boundaries remain supported; adjacent
  errors receive separate exact anchors.

## Verification

Focused regressions failed before their respective fixes, then passed:

| Requirement | Evidence |
| --- | --- |
| Known names and clause boundaries | `TestKnownNamesInGrammaticalClausesDoNotBecomeCompoundCards` |
| Whole missing fact repaired, fresh review mandatory | `TestWholeMissingFactReachesRepairButStillNeedsFreshCompleteReview` |
| No fabricated omission anchor | `TestMissingFactProjectionDoesNotInventCandidateAnchor` |
| Invalid negative/schema/evidence feedback blocked | `TestMissingFactFeedbackRejectsUnreliableNegativeRows` |
| Mixed feedback and duplicate safety | `TestMissingFactAndFaultyPositiveQuoteKeepSeparateRepairTargets` |
| Grammar finds errors and preserves valid forms | `TestCardCopyGrammarDistinguishesCountFromOrdinal`, `TestCopyGrammarReportsAdjacentErrorsAndKeepsWordBoundaries` |
| Grammar repair followed by factual revalidation | `TestWritingRepairsCopyGrammarThenRechecksFacts` |
| Term presence in reconstruction; default edit counts | `test_reconstruction_preserves_term_presence_without_copying_mention_count`, `test_reconstruct_api_checks_term_presence_but_editing_keeps_its_contract` |
| Numeric/stat/deck-code safeguards retained | `test_term_presence_does_not_relax_numeric_stat_or_deck_code_guards` |
| Capacity-only retry; fixed total deadline and bounded attempts | `test_capacity_retry_reuses_identical_input_and_keeps_total_deadline`, `test_capacity_retries_are_bounded_and_timeouts_are_not_retried`, `test_capacity_retry_respects_short_deadline_and_known_config_warnings` |
| No content re-vote; strict completed transport and real HTTP path | `test_capacity_retry_never_revotes_content_or_retries_other_failures`, `test_codex_backend_uses_shared_retry_and_returns_completed_negative_review`, `test_codex_backend_rejects_unfinished_or_disagreeing_transport` |
| Indeclinable name, exact boundaries and game/language scope | `TestIndeclinableCardNameGrammarUsesExactWordsAndLanguageScope` |
| Bad source grammar repaired without changing the handoff; fresh facts | `TestWritingRepairsNameGrammarEvenWhenHandoffContainsIt` |
| Independent Action timing and fresh positive review | `TestActionTimingIsExplicitAndStillRequiresFreshPositiveReview`, `TestFactReviewerReceivesEachRequiredQuoteFieldAndItsOwnSources` |

All Go packages and `go vet ./...` pass. Actual replay of all three old v56
candidates passes the current name guard, catches the r2 grammar error and
turns the r3 negative review into two repair findings while leaving strict
acceptance rejected. This replay is diagnostic evidence, not a new model run.
The three new Python regressions failed before the fix, then passed; changed
Python files pass Ruff. The fresh full Python suite passes 723 tests (237.39 seconds), including 16 new
capacity/transport cases. The 49-guide corpus self-test passes, including zero
reconstruction rejections; it was not repeated after transport-only changes.
Go race mode lacks a configured cgo compiler (`CGO_ENABLED=0`); staticcheck,
golangci-lint and govulncheck are not installed. No such passes are claimed.

## Live protocol

The three v60 requests ran concurrently in isolated processes, with the same
frozen binary and original empty request, separate CLI contexts and gateways.
The configured Codex CLI model is `gpt-6.1-sol`, effort `high`, model-default
output budget, 900-second call and 3,600-second job limits. Model provenance
comes from the CLI arguments; the stream does not attest an API model ID.
No latency comparison is claimed. A temporary execution-state lease prevents
idle system sleep while the owned runners exist, without changing the display
or power plan. It must be released before final delivery.

All outcomes, calls, frozen source hashes, blind reviews, quote/hash integrity
and local-patch replay belong in
`build/live-long-strategic-v57-three-runs-2026-10-21/` and
`build/long-guide-success-2026-10-21/`. Further complete cohorts are preserved
in `build/live-long-strategic-v58-three-runs-2026-10-21/` and
`build/live-long-strategic-v59-three-runs-2026-10-21/` and the final
`build/live-long-strategic-v60-three-runs-2026-10-21/`, with diagnostics in
`build/long-guide-v58-2026-10-21/` and `build/long-guide-v59-2026-10-21/`, plus `build/long-guide-v60-2026-10-21/`.

Diagnostic v57 outcomes: API 1/3, independent factual/literary acceptance 3/3,
joint acceptance 1/3. All 26 CLI calls completed and all six automatic patches
replayed exactly, preserving unaffected text and paragraph breaks. Run 1 was
blocked by a lexical repetition-count false veto despite twelve OTK mentions;
run 2 retained an ambiguous Action timing and was blocked by its factual review;
run 3 passed both gates. No negative review was overridden. The whole v57
cohort remains frozen; none of its candidates is a v58 starting draft.

Diagnostic v58 outcomes: API 2/3, independent factual/literary acceptance 3/3,
joint acceptance 2/3. Run 1 stopped after the exact CLI error “Selected model is
at capacity. Please try a different model.” before any response to its fresh
factual-review request. Runs 2 and 3 passed both gates. All three reviews and
outputs remain frozen. A 4,620-file source-match checkpoint was saved before
workspace v59 development; the still-running v58 processes used separate
frozen copies throughout. No v58 candidate was used as a new draft.

Diagnostic v59 outcomes: API 3/3, independent factual/literary acceptance 2/3,
joint acceptance 2/3. All 21 CLI calls completed; no capacity retry was needed.
All three preserved the 61 required facts. The first text failed literary
review for “на собственной Мозаке”; that erroneous form was already present
in the unchanged CLM-66 condition and was therefore known to the name guard.
The negative independent review remains unchanged. All 270 files remain
frozen, with current-source matching checked before v60 development. The
native v60 rule catches the one erroneous name in that full text and reports
none in the other two. This replay is not a live generation.

Final v60 outcomes: **API 3/3, independent factual/literary review 3/3,
joint acceptance 3/3**. All 21 logical CLI calls and 21 physical attempts
completed; the capacity retry branch was not needed in this cohort. Its tests
and replay of the retained real capacity failure verify that separate boundary.

| Run | Words | Required facts | Reader questions | API | Independent facts/style |
| --- | ---: | ---: | ---: | --- | --- |
| r1 | 2525 | 61/61 | 11/11 | accept | accept / accept |
| r2 | 2716 | 61/61 | 11/11 | accept | accept / accept |
| r3 | 2664 | 61/61 | 11/11 | accept | accept / accept |

The four automatically applied patches replay exactly into the next whole-text
reviews. Every unaffected byte is preserved, and paragraph counts remain
77, 85 and 84. Final factual quotation/source checks and all three independent
SHA/literal-quote audits pass. The original requests, 61-row ledgers, source
snapshot, frozen binary, 5,051 characters of style rules and three actual
style examples match across the triple. All seven analyzers report ready.

The final frozen manifest retains 271 files. Runtime source matched the frozen
build at final assembly. After assembly only a non-directive provenance comment
and one synthetic test fixture label were corrected to the verified SCH_400
localization, “Великая дуэлянтка Мозаки”. `postrun-source-audit.json` proves that
all other runtime/test bytes still match after line-ending normalization;
no executable statement, request or generated article changed. All Go tests
and vet were rerun after that fixture correction. Python files remain unchanged
from the fresh 723-test run.

By the predeclared selection rule, delivery is r1 in
`r1/writing/write-mozaki-strategy-r1.accepted.utf8.md`, SHA-256
`1a59e69b42eeab0024a11b4b83b8944228076886e0612a85592dd44c5c5225c0`.
All three accepted UTF-8/LF files are byte-identical to the final reviewed
candidates. The owned idle-sleep lease is released. No published text, corpus
example, raw source or generated article is committed.

Nonblocking reader notes remain visible: r1 gives a true but less specific
“более дешевые” description for Devolving Missiles instead of the historical
one-mana step; r1/r2 also retain some game-word hyphens. r3 has no findings.
These notes were not silently edited away or promoted into factual support.
The guide is historical (12 August 2020, patch 18.0), not current-meta advice.

Read-only Gate A and Gate B use GPT-6 Luna under the owner's model override.
Gate B found one required mismatch in the live runner parser; it was resolved
before launch by using the shared strict parser. The final code and harness
reviews had zero required issues. Serena/codegraph and a
named test-engineer capability are not exposed; navigation used rg and tests
were implemented directly. External documentation is not needed for these
standard-library string/schema changes. Other sessions' root/research/teams
changes remain protected and excluded from the task commit.
