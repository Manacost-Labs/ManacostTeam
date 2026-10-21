# Long strategic guide: runtime and evidence repair

Status: v56 three-run cohort completed without manual article edits. One of three
requests passed both the API and blind factual/literary review. Runtime fixes are
verified, but reliable automatic acceptance of every long guide is not achieved.

## Scope

Same historical Manacost guide, published 2020-08-12, patch 18.0; the complete
original has 28,609 characters. All 61 claim Meaning/Action/Condition/Exception/
Confidence fields are unchanged. Three requests start with an empty draft and
no prepared candidate. Source text, articles and raw traces remain in ignored
`build/`; none belong in Git.

## Repairs

- Claude CLI transport assembles all main-assistant text blocks, including
  automatic continuations. It requires a successful terminal event and matching
  final suffix; malformed, incomplete, error and tool streams fail closed.
  System text stays in a temporary UTF-8 file and user data in stdin.
- Hunspell defaults to 30 seconds, with explicit timeout and cancellation
  preserved. Retrieval defaults to 15 seconds and analyzes voice only for the
  selected examples. Ordinary Manacost API calls load the actual house rules.
- Writer, repair and fact review receive an explicit condition ledger. Repeated
  advice, sufficient versus necessary conditions, and player perspective are
  reviewed throughout the article. A grounded negative review may omit the very
  qualifier that needs restoring; acceptance still needs a fresh, complete,
  positive review with literal quotes for every required field.
  A sanitized `repair_only` projection may omit faulty supported rows to guide
  repair; that projection never attests or accepts the candidate.
- In v54, reconstruction repairs longer than 2,000 runes return bounded literal
  patches. Each patch names a current finding index and overlaps its quoted
  evidence where available. All unique original anchors, Unicode size limits,
  nonoverlap and the aggregate one-third replacement limit are checked before
  applying anything. Untouched bytes and paragraphs remain exact. Invalid
  patches leave the candidate unchanged. Shorter candidates keep the previous
  full-text protocol. Neither path bypasses full review or the two-repair limit.
- Optional source snapshots restore bounded adjacent quotation context using
  exact unique anchors and UTF-8 SHA-256. They do not expand allowed references
  or import raw numeric facts. Context cannot be injected independently.
- Structured referenced card localization supplies canonical spelling hints.
  Known grammatical name forms and a strictly parsed historical patch/date no
  longer cause false entity refusals. Unrelated numbers and invented names still
  fail the guard.
- Certainty checks no longer apply a word from another chapter to every claim
  that cannot be located. Unresolved scope remains a review warning; independent
  factual review of all 61 claims is still required.
- Empty-draft authoring does not require before/after editing proof against a
  working fact ledger. Existing-draft editing retains that requirement; both
  paths still need complete factual review and a valid positive critic verdict.
  The critic separates optional minor polishing from material defects instead
  of requesting another repair for every equally good wording.
- Reconstruction permits bounded noun-case suffixes on complete known Russian
  names and sentence capitalization of exact adjacent source phrases. It never
  recombines separate names, replaces roots or imports source-only numbers/URLs.
  The exact declared calendar date can appear in prose without authorizing its
  day number elsewhere. All lexical allowances still require full fact review.
- A lowercase dictionary phrase without an explicit card cue is an ambiguity
  warning, not proof that the article must mention that card. A final Gate B
  correction also excludes sentence-initial capitalization as the sole cue;
  quotation and explicit card/action cues retain hard preservation checks.
- A closed list of grammatical sentence/heading prefixes no longer turns
  phrases such as “Текст Сферы” or “Ранний Полкелт” into new compound names.
  The entire remainder must be a verified complete name form. Lowercase common
  phrases and partial-word matches cannot establish a name. This lexical
  allowance leaves timing and modality in the full factual review.
- A complete declared-positive factual review with a missing or nonliteral
  required quotation gets one grounding correction, sharing the existing
  format-retry budget. It rechecks the unchanged candidate: absent meaning must
  become `insufficient`. Negative, incomplete, duplicate/foreign-claim and
  unsupported-claim reviews cannot use this retry. The returned review must
  pass the same strict validator; no quote or condition requirement is waived.

## Source preparation

The original complete article was fetched again through Manacost MCP, including
both chunks. Text SHA-256 is
`02400f59af40af120a787cfee183de511ef3c4c6f86297323061ede63beabd6e`.
The initial 92 quotations are intact. One narrow official Blizzard quotation on
Freeze was added with explicit conditional inference steps; this is source
evidence preparation, not a written article. Historical card exports are client
data from HearthstoneJSON, not an official Blizzard API.

## Verification

- Python: 704 unit tests passed, including the sentence-start regression;
  CLI transport regressions include completed
  continuations, incomplete/error/malformed streams and actual child-process
  system-file cleanup. Real CLI smoke recovers the exact 1..900 array across an
  automatic continuation.
- All Go packages pass, and `go vet ./...` passes. Focused regressions cover
  timeout precedence/cancellation, input bounds and hashes, condition restoration
  followed by another negative review, canonical spelling, false name prefixes,
  historical-frame numeric injection, atomic local repair and fresh factual veto
  after patch application. The near-threshold budget also preserves two-thirds.
- Ruff, editor config validation and published-corpus selftest pass. The final
  selftest rejects 0/49 published guides.
- Real Hunspell on long articles: 15.06 and 12.36 seconds, both complete within
  the new default. Three long retrieval requests: 3.52, 3.25 and 3.53 seconds,
  with the same three examples. Health confirms all seven analyzers available.
- Go race mode was unavailable because this Windows toolchain has no configured
  cgo compiler. Staticcheck, golangci-lint and govulncheck were not installed.
  No race/static-security pass is claimed.

## Cohort accounting

Previous completed v50 cohort: 0/3 accepted. During this repair, v51 and v52
were explicitly aborted diagnostic cohorts after exposing source-context,
certainty-scope and canonical-name/guard defects. They are retained with abort
records and are not counted as completed three-run evidence. The unused first
v53 preflight snapshot made zero model calls; it was retained before rebuilding
with the final historical-scope injection fix.

The diagnostic v53 cohort uses Claude Sonnet 5.5 with actual CLI effort `high`,
64,000 requested output tokens, 900-second per-call and 3,600-second whole-job
budgets. Health also displays a gateway `xhigh` setting; the actual CLI transport
record, not that unused OpenAI setting, establishes the effort used.

Its first case was correctly rejected after a full repair rewrote an unrelated
intro into an unconditional requirement; a blind reader additionally found
repeated-condition losses. This prompted the bounded-patch repair above.
All three v53 cases were rejected; the complete reviews and API decisions remain
authoritative. These outcomes are retained separately, not final-setup successes.

The v54 Codex diagnostic and the v55/v56 cohorts use configured model
`gpt-6.1-sol`, explicit effort `high`, 900-second calls and 3,600-second jobs.
Codex output tokens use the model default; no 64,000-token override is claimed
for that backend. Terminal `turn.completed`, one final agent message, agreement
with the last-message file and absence of tool calls are required. Shell,
subagents, web search and configured MCP servers are disabled for these calls.

A separate v54 transport diagnostic was aborted after one request: pre-existing
CLI configuration warnings use `item.type=error` despite successful turns. The
final harness records those exact known warning messages separately and still
rejects fatal errors, failed turns and tool execution. User configuration was
not modified. The diagnostic is not counted as a completed three-run cohort.

Changing both repair implementation and CLI/model means this is evidence for
the tested setup, not a controlled estimate of the code-only improvement.
The v55 cohort keeps the same configured Codex model/effort as v54. Its first
v54 candidate passed a blind native reader's factual and literary checks
(61/61 claims and 11 questions), but false lexical guards, the ledger-editing
proof requirement and repeated minor critic requests blocked API acceptance.
That discrepancy prompted the authoring/lexical decision fixes above.

The first v55 case was accepted by the API and blind native reader: all 61
claims and 11 questions, 2,554 words, two automatic repairs, 84 paragraphs
preserved. The reader recorded one informational typography finding (two
hyphenated forms), not a factual or literary rejection. The delivery file is
byte-identical to both the API response and the reviewed blind snapshot.

Windows suspended during the second case. System events confirm Kernel-Power
42 at 02:52:49 local and Power-Troubleshooter 1 at 07:54:27 on 2026-10-21.
That request lost its HTTP connection and is retained as an infrastructure
interruption, not a successful completed article. Its late CLI completion has
wall time above the configured budget because the machine was suspended; no
uninterrupted wall-clock deadline claim is made for that attempt.
The same second request was repeated from an empty draft in a separate folder
with the identical frozen binary/handoff. No text from the interrupted request
is reused. A temporary system execution request prevents idle sleep only while
the owned benchmark processes run; it does not change the power scheme or
require the display to stay on, and it releases automatically on their exit.

Two lexical corrections postdate the frozen v55 source snapshot: excluding
sentence-initial capitalization as sole card evidence, and requiring a whole
lowercase word before an exact source name (so a capitalized word suffix cannot
become a fabricated name). Focused regressions cover both. Actual old/current
Go guard reports and complete Python coverage findings/warnings/metrics are
were compared on the then-available live candidates. Raw classifications may differ;
equivalent factual coverage outcomes, not identical internal classifications,
are the relevant invariant. The frozen experiment files are not modified.

The completed v55 r3 and recovered r2 passed blind factual and literary review,
61/61 claims and 11 questions each (2,644 and 2,639 words). The API still rejected
them: r3 had five false compound-name findings despite a positive final factual
review and critic; r2 had a nonliteral CLM-04 attestation quotation in a declared
positive review. Thus the completed v55 requests have API acceptance 1/3 and
native-reader acceptance 3/3; the power interruption is an additional attempt.
These are diagnostics, not a successful stable final cohort.

The v56 cohort freezes both lexical corrections, the closed grammatical-prefix
rule and the one positive-attestation correction. All three original requests
run from empty drafts in three isolated processes with distinct gateways,
analyzers and CLI contexts. This is not a controlled latency comparison.
Each uses the same frozen binary, source, 61-claim handoff and original brief.
No article edits or selective rerolls were made. The first jointly API and
independent factual/literary accepted case in r1/r2/r3 order is the deterministic
delivery candidate.

| Case | Final candidate words | API | Blind factual/literary review | Calls |
| --- | ---: | --- | --- | ---: |
| r1 | 2,713 | Accept; facts and checks complete; critic accept | 61/61 claims, 11 questions; both accept | 9 |
| r2 | 2,628 | Reject; facts/checks complete and critic accept, remaining name guards | 61/61 claims, 11 questions; facts accept, literary reject | 9 |
| r3 | 2,724 | Reject before critic; unusable factual attestation and hard findings | 58/61 claims, 11 questions; both reject | 2 |

The r1 guide is 19,652 characters with SHA-256
`2e808d3613630c9c0ef69b114d2b0e4b84d2345f4d1e5ddd8e6b3818db9771a0`.
Its LF UTF-8 export matches the API text and the independently reviewed snapshot
byte for byte. The reader recorded two nonblocking findings: a local repetition
and a hyphenated form. They were not manually polished after approval.

All 20 CLI calls completed successfully. The same original empty request,
binary, 61-row condition ledger, 5,051 characters of actual house rules and
three actual style examples were verified across all three runs. Retrieval
took 4.15, 4.13 and 4.09 seconds. Health passed all seven analyzers; r1 and r2
also completed their full checks without skipped analyzers. This does not turn
the aborted r3 factual review into a completed check. The temporary idle-sleep
lease was released after all three owned runners exited.

The r1 repairs changed 2.17% then 7.25% of candidate runes; r2 changed 10.12%
then 1.81%. Literal replay matches every subsequent whole-text review exactly.
All unpatched bytes are preserved; paragraph counts remain 78 and 79 respectively.
Snapshot/current source comparison permits only CRLF/LF conversion and excludes
the evaluation documentation updated with these final outcomes. No production
logic changed after the frozen v56 build.

Remaining limits are explicit. The r2 name guard still falsely groups “Сам
Полкелт”, “До Полкелта Сфера” and “Механики Полкелта” as novel compound names.
Its blind reader separately found the grammatical form “2 копию”, so that
candidate is not a publishable alternative. In r3, a nonliteral positive-row
quote and a negative row without any literal anchor made repair-only feedback
unusable; the positive-attestation retry correctly did not revote a negative
review. The blind reader also found a missing count of random hits and disputed
two additional source interpretations. No API refusal was overridden to improve
the acceptance score. These three runs establish 1/3 joint acceptance, not
universal reliability or a controlled improvement in writing quality.

## Evidence paths

- `build/long-guide-runtime-fix-2026-10-21/`: tests, source verification,
  source-handoff preparation, measured tool smokes and diagnostic abort records.
- `build/live-long-strategic-v53-three-runs-2026-10-21/`: frozen code, settings,
  requests and all diagnostic outcomes, including the rejected first case.
- `build/live-long-strategic-v54-codex-final-three-runs-2026-10-21/`: Codex
  diagnostic cohort, full requests, CLI streams, responses, results and texts.
- `build/live-long-strategic-v55-three-runs-2026-10-21/`: diagnostic three-run
  cohort, frozen code/settings, all requests, responses, results and blind packs.
- `build/live-long-strategic-v55-r2-power-retry-2026-10-21/`: explicit recovery of
  the power-interrupted second request, same frozen binary and empty input.
- `build/live-long-strategic-v56-three-runs-2026-10-21/`: frozen final setup and
  isolated `r1/`, `r2/`, `r3/` live requests, all responses, results and blind packs.

Read-only GPT-6 Luna Gate A and Gate B were used under the user's model override
of the older 5.6 Luna repository preference. Gate B closed the final scope-parser
finding with no required issues remaining. Serena/codegraph were unavailable;
symbol searches used rg. Official Claude documentation, installed CLI help and
Context7 confirmed the headless streaming interface. No production publication
or live-current-meta claim is made by this historical-guide experiment.
