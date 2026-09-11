# Research Operations

## When to use a persistent run

Create a file-backed research run when at least one applies:

- `exhaustive` or `raw-research` output;
- the work will span sessions or needs resumability;
- the user requests an auditable dossier or reusable research database;
- another Skill, writer, editor, or reviewer will consume the result;
- source/evidence volume makes in-chat provenance fragile.

For a bounded chat answer, keep records internally and avoid unnecessary files.

## Lifecycle

Use these run states:

`planned -> discovering -> collecting -> validating -> auditing -> complete`

Use `incomplete` when material gaps remain at delivery and `blocked` only for an actual access or authority blocker. State transitions belong in `manifest.json` with `updated_at`.

## Stable identity

Use stable, unique identifiers:

- `QRY-0001` for queries;
- `SRC-0001` for sources;
- `EVD-0001` for evidence items;
- `CLM-0001` for claims;
- `COM-0001` for community claims;
- `CTR-0001` for contradiction records.

Never reuse an ID for a different object. Correct a material record with an incremented `revision`, `supersedes_id`, or explicit change note rather than silently changing provenance.

## Checkpoints

After every major research pass:

1. append executed queries and outcomes;
2. add or update source access metadata;
3. connect new evidence to claims;
4. update gaps and branch saturation;
5. record any changed preliminary conclusion or confidence;
6. update run status and timestamp.

Do not save secrets, browser session data, private tokens, or unnecessary personal information.

## Resume protocol

When resuming:

1. read `manifest.json` and the most recent checkpoint;
2. validate the bundle at `working` stage;
3. confirm current date/version and identify change events since the last access;
4. re-open only sources whose freshness or availability matters and compare new content with preserved fingerprints when available;
5. continue from unresolved gaps, not from broad discovery;
6. preserve old evidence as historical when a new patch/version supersedes it.

The operational command performs the working-stage integrity check and prints the latest checkpoint gaps and next actions:

```text
python3 scripts/research_ops.py resume /path/to/run
```

Compare claim text, status, and confidence between two valid bundles:

```text
python3 scripts/research_ops.py compare /path/to/older-run /path/to/newer-run
```

## Change control

- Keep source access and query logs append-oriented.
- Record why a claim status or confidence changed.
- Preserve rejected claims when a downstream writer might otherwise revive them.
- Do not overwrite a completed run to represent a materially different scope; start a new run and link the prior `research_id`.
- Migrate legacy bundles with `migrate_research_bundle.py`; preview first, preserve the generated backup, and use explicit rollback if validation fails.
- Keep snapshots inside the bundle. Never fingerprint a path that escapes the bundle or contains private session material.

## Delivery states

- `ready`: final validator passes and audit is `pass`.
- `ready_with_warnings`: final validator passes and audit is `pass_with_warnings`; warnings are visible in the handoff.
- `not_ready`: integrity validation fails, audit is `fail/not_run`, or a decision-critical gap is undisclosed.

A polished report alone is never proof of readiness.

## Deterministic export and release

Export validates a completed bundle before writing a sorted archive with normalized timestamps and a SHA-256 digest:

```text
python3 scripts/research_ops.py export /path/to/run /path/to/run.zip
```

The release command requires `VERSION=1.0.0`, an explicit license, the Search/Web boundary, passing package/tests/benchmark/semantic-gold gates, and then writes deterministic skill and evaluation archives plus `release-manifest.json`:

```text
python3 scripts/research_ops.py release \
  --skill /path/to/deep-research \
  --benchmark /path/to/evaluation/benchmark \
  --output /path/to/release
```

## Handoff

Use the handoff template. Provide main question, as-of context, audit status, decisive claims, unresolved issues, excluded scope, version constraints, files delivered, and what the downstream consumer must not overstate.

The downstream Writer or Editor may improve presentation but must not silently upgrade confidence, remove conditions, invent citations, or revive rejected claims.
