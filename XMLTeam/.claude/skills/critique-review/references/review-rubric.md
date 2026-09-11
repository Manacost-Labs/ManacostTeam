# Critique Review Rubric

Load this reference when a review needs deeper judgment than a narrow diff read.

## Context Intake

Before judging implementation, reconstruct the review target:
- Intent: PR title/body, issue, task, plan, or user request.
- Diff shape: files changed, generated files, deleted files, migrations, lockfiles, dependencies, config, public APIs.
- Verification story: tests added, tests run, CI state, screenshots, manual checks, rollout notes.
- Blast radius: who can hit this code path, whether it is default-on, and whether rollback is easy.

Review tests before implementation when tests exist. Tests expose intended behavior and often reveal missing edge cases faster than reading production code first.

## High-Risk Areas

Security:
- Authentication and authorization changes, including missing owner checks, role checks, tenant boundaries, and token scope validation.
- User-controlled input reaching SQL, shell commands, filesystem paths, redirects, SSRF-capable fetches, templates, logs, or model prompts.
- Secret handling, OAuth flows, webhook verification, cookie/session settings, CORS, CSRF, and rate limits.

Data integrity:
- Migrations, schema defaults, backfills, unique constraints, cascading deletes, and compatibility with existing rows.
- Writes that are no longer atomic, idempotent, retried safely, or wrapped in the same transaction boundary as their invariants.
- Serialization changes that affect public APIs, queued jobs, persisted events, or cache keys.

Correctness:
- Off-by-one behavior, null or undefined inputs, empty collections, time zones, daylight saving time, locale-sensitive parsing, and stale cache reads.
- Error handling that swallows failures, reports success too early, retries unsafe operations, or changes user-visible status without durable state.
- Async ordering, race conditions, cancellation, cleanup, and resource leaks.

Tests:
- Require tests for new branches in business logic, permission checks, migrations, data transformations, and bug fixes.
- Prefer focused tests that would fail on the old code and pass on the new behavior.
- Missing tests are a finding only when the changed behavior is risky enough that regression is plausible.

AI and agent behavior:
- Prompt changes that weaken tool permissions, leak secrets, bypass confirmation, blur review versus edit mode, or encourage unverified claims.
- Agent workflows that can run destructive commands, mutate production systems, post externally, or resolve review threads without explicit user intent.
- Model output parsed as trusted data without validation, schema enforcement, or fallback handling.

Frontend:
- Broken user flows, incorrect state transitions, hydration hazards, inaccessible controls, keyboard traps, poor error states, and text or layout overflow.
- Performance regressions from unnecessary client components, heavyweight imports, waterfall data fetching, repeated subscriptions, or expensive rerenders.

Dependencies:
- New runtime dependency when an existing package or standard library feature already solves the problem.
- New package without checking maintenance, license compatibility, bundle/server footprint, and audit surface.
- Lockfile-only changes that do not match the package manifest.

Change shape:
- Refactor and behavior change mixed together without a reason.
- Very large diffs that are not mostly generated, deleted, or mechanical.
- Compatibility breaks hidden inside cleanup.
- Dead code left behind after replacement.

## False Positive Filters

Do not file a finding when:
- The issue is purely stylistic and the repository already uses that style.
- The changed code is dead or unreachable and no caller path is introduced.
- The problem depends on impossible input because existing validators or types prevent it.
- A test gap is low-risk and the code is simple enough to inspect directly.
- The fix would be larger or riskier than the issue and the impact is minor.

## Review Tactics

Trace behavior from entry point to side effect. For a route, command, worker, or UI action, follow the input, validation, authorization, state read, state write, response, and async follow-up.

Compare before and after semantics. Ask what users, jobs, API clients, or maintainers could do before this change that they cannot do now, and the reverse.

Search for parallel patterns. If a changed path has siblings, compare validation, error handling, cache invalidation, telemetry, and tests.

Read call sites before judging helpers. A helper can look safe in isolation and fail because of how callers handle nulls, errors, ownership, or concurrency.

Separate findings from questions. If evidence is incomplete but the risk is plausible, ask a focused question. Do not convert uncertainty into a bug report.

Use a second-pass checklist:
- Could this fail for empty/null/boundary input?
- Could another tenant or user access this state?
- Could retry, concurrency, or partial failure duplicate or lose work?
- Would the added tests fail against the previous implementation?
- Does this change require migration, backfill, feature flag, or deployment ordering?
- Did the code introduce a dependency, global state, or long-lived cache that changes operational risk?

For AI-generated code, increase scrutiny. Look for plausible but nonexistent APIs, ungrounded comments, duplicated branches, unused compatibility layers, overbroad catch blocks, and tests that assert mocks rather than behavior.

## GitHub Comment Style

Use comments that are short, local, and actionable:

```markdown
This looks like it drops the tenant filter that the previous query relied on. If a user knows another `projectId`, this path can return that project's runs. Can we keep the `organizationId` predicate here, matching `getProjectForUser`?
```

Avoid:
- "Consider improving..."
- "This might be wrong..." without a concrete failure mode.
- Multi-paragraph architecture advice on a tiny line comment.
- Praise-only comments unless explicitly asked for mentoring feedback.

## Verdict Calibration

Use `Request changes` for P0/P1 findings and unresolved P2 findings that can plausibly ship a regression.

Use `Approve with notes` when findings are optional, already mitigated, or worth tracking but not worth blocking.

Use `No objection` when no actionable issue was found. Still state checks run and residual risk.
