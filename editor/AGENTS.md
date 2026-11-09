# EditorTeam Agent Instructions

These instructions apply to the EditorTeam module in any checkout. Use the
repository's own instructions, skills, and verification commands on the current
machine. Skill selection is described in `.agents/README.md` and
`.agents/profile.yaml`, relative to this file.

## Authority and precedence

This file governs skill discovery and maintenance only. It never overrides
system, platform, developer, security, repository, or user instructions.

When several instructions apply, use this order:

1. system and platform instructions;
2. developer and security instructions;
3. user instructions;
4. the repository root `AGENTS.md` and the nearest module `AGENTS.md`;
5. the selected project profile;
6. the smallest set of skill files needed for the task.

More specific project rules remain authoritative for that project. A skill is
guidance, not permission to access secrets, production data, authentication
flows, or unrelated repositories.

## Mandatory execution contract

This policy applies to coding, review, debugging, design, infrastructure,
and documentation tasks in EditorTeam. Editorial workflows retain their own
content review requirements. This file adds no mandatory sub-agent stages or
fixed model requirement; delegation follows the user request and the selected
workflow.

"Always use" means: always evaluate every applicable skill, linter, quality
tool, and MCP listed below, and actually invoke the applicable ones. It does
not mean loading every unrelated skill into every prompt or starting every
MCP server for a task that cannot use it. A tool may be skipped only with a
short reason recorded in the handoff (for example: "not applicable",
"project has no Go code", or "MCP is not configured in this client"). Never
claim that a tool was used when it was only installed or mentioned.

### 0. Reason first, then code

Before implementation, the agent must make its reasoning inspectable and
honest:

- state material assumptions explicitly;
- ask a question when the requirement or context is ambiguous;
- present viable solution options when more than one approach is reasonable;
- explain important trade-offs, including cost, risk, complexity, and
  reversibility;
- say clearly when it does not understand something or lacks evidence.

Do not hide uncertainty behind confident wording or silently choose an
interpretation that can materially change the result.

### 0.1. Simplicity first

Prefer the smallest solution that satisfies the verified acceptance criteria:

- avoid unnecessary functions, abstractions, flexibility, and configuration;
- do not increase architectural complexity without a concrete requirement;
- prefer a clear 50-line solution over a speculative 200-line framework;
- remove complexity only when its behavior and ownership are understood.

### 0.2. Surgical changes

Change only what belongs to the task:

- do not perform opportunistic refactors or unrelated cleanup;
- do not modify neighboring code without a demonstrated need;
- preserve the project's existing style and conventions;
- do not delete old or apparently unused code without explicit permission;
- remove imports or functions only when they became unnecessary because of
  the current change.

### 0.3. Verifiable goals

Every task must have a concrete, testable success criterion:

- bug fix: first add a test that reproduces the failure;
- validation change: test invalid, boundary, and accepted input;
- refactor: prove behavior with tests before and after the change;
- multi-step task: write a plan and verify each stage before continuing.

The required outcome is not merely a plausible explanation or a code diff; it
is a result that can be checked with evidence.

### 1. Mandatory preflight for every task

Before searching code or proposing a patch, the agent must:

1. read the repository root `AGENTS.md`, README, and the nearest module
   `AGENTS.md`;
2. identify the checkout root and select applicable skills from
   `editor/.agents/profile.yaml`; read their local `SKILL.md` files using
   `editor/.agents/README.md`;
3. use `using-agent-skills` to decide applicability and
   `planning-and-task-breakdown` for every non-trivial task. The plan must
   state scope, files, dependencies, acceptance criteria, verification, and
   safe parallel/sequential boundaries;
4. run `git status --short`, `git diff --name-only`, and `git worktree list`
   before any edit. Record the starting changed paths and treat them as
   protected work owned by the user or another session;
5. if the project has `.codegraph/`, run `codegraph explore "<question>"`
   before broad text search. Use Serena for symbol-aware navigation when its
   MCP is available and the task involves a non-trivial code relationship;
6. state the MCP decision before implementation: which applicable MCPs will
   be used, what each will verify, and why an applicable MCP is unavailable if
   it cannot be called.

For a behavior change, canonical skill `data/test-driven-development`
(`test-driven-development`) is mandatory: add or update the smallest failing
test first, make it pass, then refactor. For delivery or
CI changes, `ci-cd-and-automation` is mandatory. For code changes,
`git-workflow-and-versioning` is mandatory. For a large context, long-running
task, or context handoff, also load the relevant context-engineering skill.

### 2. Parallel-session safety protocol

Several agent sessions may work in the same checkout. A clean checkout is not a
prerequisite when another session is active, but ownership must be explicit:

- before **each** patch, repeat `git status --short` and compare
  `git diff --name-only` with the recorded baseline;
- after each atomic slice, repeat `git status --short` and
  `git diff --name-only`;
- if a path changed after the baseline, or another session owns an overlapping
  path, stop before applying a patch, inspect the new diff read-only, and
  coordinate through the available Codex task/thread or dev-team mechanism;
- use `dev-team` for broad parallel work: preflight, disjoint claims and
  worktrees, read-only review, dry-run conflict checks, verification, and only
  explicitly authorized integration. Never create blind workers or integrate
  an unreviewed patch;
- keep database migrations, OpenAPI/Protobuf contracts, generated files, and
  shared configuration changes sequential unless the plan explicitly assigns
  ownership and a contract checkpoint;
- do not use `git reset`, `git checkout`, `git stash`, destructive cleanup, or
  mass formatting to hide or overwrite another session's work;
- do not modify authentication/sign-in files, secrets, `.env` files, or
  unrelated task documents while working on another feature;
- if coordination cannot establish ownership, leave the files untouched and
  report the exact conflicting paths.

### 3. Skill activation matrix

The following skills are execution requirements, not a passive catalog:

| Work phase | Required skills to load and apply |
| --- | --- |
| Understand and plan | `using-agent-skills`, `planning-and-task-breakdown`, relevant `context-engineering` |
| Architecture and implementation | `codebase-design`, `domain-modeling`, `clean-architecture`, `incremental-implementation`, and the relevant frontend/API/backend skill |
| UI and frontend | `frontend-ui-engineering`, `ui-design`/design-system skills, `react-patterns`, `performance-optimization`, and browser-testing skills when UI behavior changes |
| Tests and verification | `test-driven-development`, the project test skill, `browser-testing-with-devtools` or Playwright skills for browser behavior, and the API testing skill for API behavior |
| Bugs and regressions | `diagnosing-bugs`, `debugging-and-error-recovery`, focused regression tests, then the full project gate |
| Security and dependencies | `security-and-hardening`, `code-review-and-quality`, `dependency-updater`, and the relevant security scanners |
| CI, releases, and hooks | `ci-cd-and-automation`, `git-workflow-and-versioning`, `documentation-and-adrs` when policy changes |
| Multiple agents/sessions | `dev-team`, `multi-agent-patterns`, `resolving-merge-conflicts`, and `git-workflow-and-versioning` |
| SEO/content | the SEO skill selected for the project; keep `codex-seo` and `claude-seo` as separate vendor options and do not silently mix their rules |

When two skills overlap, choose one canonical rule as the authority, note the
choice, and use the other only for additional checks. Do not make the agent
load the whole engineering profile if a smaller set is sufficient; do make
the selected skills visible in the plan and final handoff.

### 4. Installed tool and MCP routing

Use the installed executable or configured MCP when the task matches its
scope. Start by checking availability with `command -v <tool>` or the MCP
client. If an expected tool is missing, stop the affected check and report
it; do not silently substitute a weaker check.

#### Frontend and TypeScript

- TypeScript: `pnpm tsc --noEmit` (or the project's equivalent script).
- ESLint: `pnpm eslint .`; Next.js projects must use their project
  `eslint-config-next`, not the removed `next lint` command.
- Biome: `pnpm biome check .`.
- Knip: `pnpm knip` for unused files, exports, and dependencies.
- Vitest: `pnpm vitest run` for unit/component tests.
- Playwright: `AI_E2E=1 pnpm exec playwright test` when browser flows,
  accessibility, mobile keyboard, streaming, or responsive behavior changed.
  Use the installed browsers and cover the project's supported viewport
  profiles; do not make E2E silently replace unit tests.
- Dependency Cruiser: `depcruise --validate <project-config>` when an import
  graph or architecture boundary is affected.

#### Go, API, and data

- Go: `gofmt` (check-only unless formatting was explicitly requested),
  `go vet ./...`, `staticcheck ./...`, `golangci-lint run`,
  `go test ./...`, `go test -race ./...`, and `govulncheck ./...` as applicable.
- Go fuzzing is built in: run a scoped, time-bounded
  `go test ./... -fuzz=Fuzz -fuzztime=30s` only where fuzz targets exist and
  the package is safe to execute.
- Go performance diagnostics are built in: use `go tool pprof` and
  `go tool trace` only with a real captured profile/trace and a stated
  hypothesis; do not infer performance from static inspection alone.
- OpenAPI: use Spectral for linting, Schemathesis for safe non-production API
  testing, and `oapi-codegen` when generated Go clients/servers are part of
  the project contract. Keep schemas, config, and generated output consistent.
- Protobuf/gRPC: use Buf when the project contains Buf configuration.
- SQL: use `sqlc` with the project's config and verify generated code plus
  database tests; never regenerate another session's owned files.

#### Security, CI, and maintenance

- Run the relevant repository checks from the checkout root:
  `python3 tools/check.py editor` for Python changes and
  `python3 tools/check.py editor-go` for Go changes, with their dependencies
  installed. See `CONTRIBUTING.md` for other scopes and focused checks.
- Review the staged diff for secrets and use applicable security scanners
  available in the current environment. Never print secret values or scan
  production dumps into the task output.
- Use Gitleaks, OSV-Scanner, Trivy, Semgrep, and CodeQL for the languages and
  risk areas they cover. CodeQL requires a project database and build; do not
  report CodeQL coverage without creating/analyzing that database.
- Use `actionlint` for GitHub Actions and the available ShellCheck, shfmt,
  yamllint, and Hadolint checks when those file types or workflows change.
- Use either `pre-commit` **or** `lefthook` per project, never both as active
  hook managers. Hooks complement, but do not replace, the final project gate.
- Use Renovate only for configuration validation, dependency discovery, or a
  user-approved update; do not apply dependency upgrades implicitly.
- Use OpenTelemetry SDK/Collector only with an explicit project config and
  reviewed destination. The server collector is not an automatic listener and
  must not open ports or export data by assumption.

#### Configured MCP servers

When the Codex client exposes them, use the applicable MCP directly:

| MCP | Mandatory use case |
| --- | --- |
| `serena` | symbol-aware project navigation, references, and safe semantic refactors |
| `codegraph` | relationship exploration in repositories with `.codegraph/` |
| `context7` | current official documentation for libraries, frameworks, or APIs whose behavior/version matters |
| `chrome-devtools` | browser runtime, console, network, layout, performance, and interaction verification |
| `github` | repository issues, PRs, Actions, and source context when the task includes GitHub; respect its read-only/lockdown setup |
| `openaiDeveloperDocs` | current official OpenAI product/API documentation |
| `sentry` | diagnosis of authorized application errors and regressions; do not expose secrets or unrelated user data |
| `open-design` and `miro` | design-system, visual-flow, or board work when the connected resource is in scope |
| `ovhcloud` and `ovhcloud-api` | authorized OVH infrastructure operations only; read first and require explicit scope for mutations |

MCP use must be evidence-producing: capture the relevant result in the
  reasoning or handoff and distinguish source facts from inference. If an MCP
  is unavailable in the current client, use the safest local fallback and say
  so. Never manufacture an MCP result.

### 5. Definition of done and quality gates

Every implementation handoff must include:

1. the selected profile and skills actually applied;
2. the preflight worktree baseline and confirmation that protected paths were
   not changed;
3. focused tests for the changed behavior, with RED/GREEN evidence when code
   behavior changed;
4. the relevant repository check selected from `CONTRIBUTING.md` and
   `python3 tools/check.py --list`;
5. conditional browser, API, performance, dependency, CI, and security
   checks from the routing matrix;
6. a final `git status --short` and `git diff --name-only` comparison against
   the baseline;
7. failures, baseline debt, skipped tools with reasons, residual risks, and
   the exact next action.

Do not disable a failing check, weaken a rule, or label a partial scan as a
“pass” to make the result green. If an existing baseline is not clean,
document it and add the narrowest new gate that prevents regression.

### 6. Response contract

Agent communication must be concise, direct, and outcome-first. Use the
user's language unless they ask otherwise. Progress updates should mention
only a material result, blocker, or decision; do not stream routine command
output.

The default final response is short enough to scan in a few seconds and uses
this order:

1. `Done:` one sentence stating what was actually completed;
2. `Checks:` only the relevant checks and their result;
3. `Git:` explicit `Commit: yes/no` and `Push: yes/no`. If pushed, include
   branch and commit; if not, say `Push: not performed` and the real reason;
4. `Next:` up to three concrete next-step options, with the recommended one
   first when there is a meaningful choice.

For a trivial task, compress this to one or two sentences. For an incomplete
task, replace `Done` with `Status` and state one blocker plus the required
user action. Never claim a commit, push, deployment, test, MCP call, or skill
use that did not actually happen. Do not paste raw logs, repeat the full
plan, list every inspected file, or add generic advice. Expand only when the
user asks for detail or a failure requires it.

Check the response against the actual changes and verification results before
sending it.

Prefer one canonical skill over copies in `.agents/skills`, `.claude/skills`,
and `.codex/skills`. Those directories are migration sources until their
project is explicitly switched to this catalog. Do not delete or replace them
as part of a skill import.

## Skill contract

When maintaining the upstream skill catalog, every canonical skill must:

- live below `skills/<namespace>/<skill-id>/`;
- contain a `SKILL.md` with frontmatter `name` and `description`;
- contain a `skill.yaml` with its canonical id and namespace;
- avoid secrets, credentials, cookies, private keys, and production dumps;
- state when it applies and what verification it requires;
- use repository-relative references or clearly mark external references;
- be small enough to load for one task.

For this checkout, use `editor/.agents/profile.yaml` and the local skills in
`editor/.agents/skills/`. Their upstream source and revision are recorded in
`editor/.agents/README.md`; external catalog tooling is not a prerequisite
for EditorTeam tasks.

## Safe migration

Import is additive. A skill moves through these states:

`discovered` → `reviewed` → `canonical` → `project-enabled` → `legacy-copy-removed`

Only the last state permits removing a project-local copy, and only in a
separate change after the project has passed its own checks. Conflicting files
keep explicit namespaces until a human chooses the winning version.

Select the relevant engineering skills from the EditorTeam profile at
preflight and apply them. Loading remains task-scoped so unrelated guidance
does not dilute the active task's context.

## External catalogs

Vendor and platform catalogs remain dependencies, not copied source. They are
identified by their source metadata and must not be silently edited or vendored
into this repository. Local project skills are the first candidates for
canonicalization.
