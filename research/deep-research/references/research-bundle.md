# Persistent Research Bundle

## Purpose

The bundle is an optional, portable evidence database for long-running or writer-facing work. It preserves provenance and makes structural errors detectable. It does not replace semantic verification or the Research Auditor.

## Initialize and validate

```text
python3 scripts/init_research_run.py RUN_DIRECTORY \
  --question "MAIN QUESTION" \
  --depth exhaustive \
  --output-profile raw-research \
  --domain hearthstone \
  --modifier current-patch-only

python3 scripts/validate_research_run.py RUN_DIRECTORY --stage working
python3 scripts/validate_research_run.py RUN_DIRECTORY --stage final

python3 scripts/fingerprint_research_sources.py RUN_DIRECTORY --apply
python3 scripts/migrate_research_bundle.py LEGACY_RUN --apply

python3 scripts/registry_seed.py RUN_DIRECTORY --apply
python3 scripts/plan_queries.py RUN_DIRECTORY --language en --language ru --apply
python3 scripts/fetch_source.py RUN_DIRECTORY URL --source-type official --query-id QRY-0001 --apply
python3 scripts/search_coverage.py RUN_DIRECTORY --strict
python3 scripts/freshness_check.py RUN_DIRECTORY --strict
```

The initializer refuses to overwrite a non-empty directory.

## Directory contract

```text
research-run/
├── manifest.json
├── plan.json               # new editor-ready coverage contract only
├── snapshots/              # optional preserved inspected content
├── migration-backups/      # created only by applied migrations
├── query-plan.jsonl        # optional planned query matrix from plan_queries.py
├── candidates.jsonl        # optional ledger of seen search results and decisions
├── queries.jsonl
├── sources.jsonl
├── evidence.jsonl
├── claims.jsonl
├── community.jsonl
├── contradictions.jsonl
├── checkpoints.jsonl
├── semantic-audit.jsonl
├── audit.json
├── report.md
├── useful-data.md          # required for deep/exhaustive editor-ready
├── evidence-appendix.md    # required when any record routes to appendix
└── handoff.md
```

JSON Lines ledgers contain one JSON object per line. This keeps large runs append-friendly and reviewable.

## Manifest contract

Newly initialized bundles include:

```json
{
  "schema_version": "1.2",
  "research_id": "RES-...",
  "main_question": "...",
  "created_at": "ISO-8601 UTC",
  "updated_at": "ISO-8601 UTC",
  "as_of": "YYYY-MM-DD",
  "depth": "quick | deep | exhaustive",
  "output_profile": "editor-ready | research-report | raw-research",
  "modifiers": [],
  "domain_adapters": [],
  "status": "planned | discovering | collecting | validating | auditing | complete | incomplete | blocked",
  "current_context": {},
  "prior_research_ids": [],
  "provenance": {
    "fingerprint_policy": "required | when-permitted | off",
    "snapshot_policy": "local-only",
    "hash_algorithm": "sha256"
  }
}
```

`output_profile` records the intended presentation separately from research-scope modifiers. The default for newly initialized runs is `research-report`; use `editor-ready` for the editor-facing synthesis or `raw-research` for an explicitly requested dossier. Schema `1.1` requires this field. Legacy schema `1.0` manifests without it remain readable: the validator infers `raw-research` only from the old `raw-research` modifier and otherwise assumes `research-report`, with a compatibility warning. An early schema `1.1` bundle without this field remains resumable at the working stage with the same explicit warning, but cannot pass the final gate until `migrate_research_bundle.py` backfills the matching profile in both `manifest.json` and `handoff.md`. In schema `1.1`, `raw-research` is not a modifier.

Every newly initialized `editor-ready` manifest also contains `"coverage_contract_version": "1.0"`. This feature flag adds a section-to-output preservation contract while leaving the bundle on schema 1.1. Existing schema 1.1 bundles without the flag remain valid under the legacy contract; the validator does not force an automatic migration.

The coverage-enabled bundle adds `plan.json`:

```json
{
  "coverage_contract_version": "1.0",
  "research_id": "RES-...",
  "updated_at": "ISO-8601 UTC",
  "deliverable_outline": [
    {
      "section_id": "SEC-0001",
      "working_title": "...",
      "reader_question": "...",
      "readiness_condition": "...",
      "status": "planned | researching | covered | excluded | unresolved",
      "coverage_note": ""
    }
  ]
}
```

Section IDs are stable and must not be renumbered when prose headings change. At final validation, every section is `covered`, `excluded`, or `unresolved`; `excluded` and `unresolved` require a meaningful `coverage_note`.

For `editor-ready`, `audit.json` also records a post-edit `clarity_review`. Its status can become `pass` only after an item-by-item comparison confirms that material claims, numbers, scope, citations, limitations, and contradictions survived the Clarity Editor pass. Record `reviewed_at` as an ISO-8601 timestamp, list all reviewed critical/material claims in `reviewed_claim_ids`, and store exact SHA-256 values for `report.md`, `claims.jsonl`, and `sources.jsonl`. This freezes the reviewed artifacts: editing any of them invalidates the final gate. This is a semantic review record, not a claim that the deterministic readability checker can understand meaning.

Schema `1.0` remains readable for legacy validation. Schema `1.1` bundles remain valid. New runs use `1.2`, which keeps the whole 1.1 provenance contract and adds search integrity:

- every query uses a canonical `pass` and `family` (an error, not a warning) and should record a `language`;
- an `exact_excerpt` on evidence must contain at least four words and, when the source has a verified snapshot, must be found in that snapshot after whitespace, case, quote, and dash normalization;
- at final stage, every supporting evidence item of a critical or material claim whose source has a verified snapshot needs a verified `exact_excerpt`;
- at final stage, every non-rejected critical claim needs `challenging_evidence_ids` or a `challenge_search` record whose `query_ids` exist and whose `result` is `none_found`, `found_weak`, or `found`; material claims receive a warning;
- `output_profile` is mandatory.

Upgrade a 1.1 bundle with `migrate_research_bundle.py RUN --to 1.2 --family-map MAP.json --apply`. The map translates free-text families and passes to canonical values and the migration refuses to guess; legacy values are preserved in `legacy_family` and `legacy_pass`. The backup includes `queries.jsonl` and `--rollback` restores it. The migration tool upgrades schema `1.0` and can also backfill a matching `output_profile` in the manifest and handoff of an early schema `1.1` bundle. It refuses conflicting or duplicate handoff values. Run it without `--apply` first; applying creates a timestamped backup of `manifest.json`, `sources.jsonl`, and `handoff.md` under `migration-backups/`, and `--rollback BACKUP_DIRECTORY` restores the protected files.

## Minimum ledger contracts

### Query

`query_id`, `pass`, `family`, `query`, `executed_at`, `status`, and optional `result_source_ids`. Under the editor-ready coverage contract, also include a non-empty `deliverable_section_ids` list.

Use canonical values so search coverage can be measured. `pass` is one of `discovery`, `collection`, `gap`, `contradiction`, `freshness`, or `audit`. `family` is one of `general`, `primary`, `statistics`, `experts`, `reddit`, `x`, `youtube`, `mistakes`, `synergies`, `counterargument`, `freshness`, or `localized`. Record `language` as an ISO code. The validator warns on non-canonical values, and `search_coverage.py` cannot count such a query toward any branch. `plan_queries.py` emits records that already follow this contract.

### Query plan

`query-plan.jsonl` is written by `plan_queries.py` and `registry_seed.py` and holds planned records with `status: planned` and `planned_at`. It is not an executed ledger. When a planned query runs, copy it into `queries.jsonl` with `executed_at`, the real `status`, and `result_source_ids`. `search_coverage.py` reports planned queries that were never executed.

### Candidate

`candidates.jsonl` makes rejected search results visible. Each record has `candidate_id` (`CAN-0001`), `query_id`, `url`, `decision` (`opened`, `rejected`, or `deferred`), optional `rank`, `title`, and `snippet_sha256`. A `rejected` record needs a canonical `reason`: `duplicate_lineage`, `off_topic`, `stale_version`, `low_authority`, `snippet_only`, `paywalled`, `login_required`, `unavailable`, `wrong_mode`, `wrong_language`, `already_saturated`, or `other`. An `opened` record must reference the resulting `source_id`. The validator checks these references when the file exists. `fetch_source.py --query-id` writes the `opened` record itself; `candidates.py record` and `candidates.py bulk` record rejections and deferrals, keyed by query and canonical URL so a deferred result later opened keeps one row.

### Challenge search

A critical or material claim without `challenging_evidence_ids` should carry `challenge_search: {"query_ids": [...], "result": "none_found"}` naming the contradiction-pass queries that looked for disconfirming evidence. `search_coverage.py` treats a critical claim with neither as a blocking finding.

### Source

Schema `1.1` requires `source_id`, `title`, `requested_url`, `final_url`, `accessed_at`, `access_integrity`, `source_type`, `lineage_id`, `mutable`, and `fingerprint_status`.

For `verified`, also record `snapshot_path`, `content_sha256`, `content_bytes`, and `fingerprinted_at`. The validator recalculates the hash. `fetch_source.py` produces a verified record, the snapshot, an optional `canonical_url`, and a derived `lineage_id` in one step; pass `--lineage` when the page reposts a known upstream origin, `--file` to ingest a page already saved by the host tool, and `--refresh SRC-0001` to replace an existing source's snapshot and fingerprint from its recorded URL. Pages that return too little readable text are refused rather than recorded as full access. For `unavailable` or `exempt`, record `fingerprint_reason`. Never preserve authenticated pages, private session data, paywalled content without permission, or copyrighted material beyond what the research task permits.

### Lineage suggestions

`lineage_suggest.py RUN_DIRECTORY` compares snapshot texts with word-shingle Jaccard similarity and lists pairs above the threshold whose sources still carry different `lineage_id` values; `--apply` makes the later-accessed source adopt the earlier lineage and records `previous_lineage_id`, `lineage_similarity`, and `lineage_matched_source_id`. Textual overlap is the only signal: paraphrases of one press release or slices of one dataset still need a hand-recorded lineage.

### Evidence

`evidence_id`, `source_id`, `claim_ids`, `relationship`, `locator`, `evidence_type`, and either a faithful paraphrase or a compliant excerpt. Under the coverage contract, add `deliverable_section_ids` and `output_disposition`.

### Claim

`claim_id`, `claim`, `importance`, `status`, `confidence`, `supporting_evidence_ids`, `challenging_evidence_ids`, plus scope and impact fields when relevant. Under the coverage contract, add `deliverable_section_ids` and `output_disposition`.

### Community and contradiction records

Use `community_claim_id` or `contradiction_id` and the corresponding template fields. Keep source/evidence IDs rather than copying unsupported prose. Coverage-enabled community records also use `deliverable_section_ids` and `output_disposition`; contradiction records keep their existing contract.

For coverage-enabled evidence, claim, and community records, `output_disposition` is exactly one of `main`, `useful_data`, `appendix`, or `omit`. Query records have section links but no output disposition. `omit` requires a non-empty `output_omit_reason`. `useful_data` requires a non-empty `useful_data_types` list containing only `number`, `comparison`, `advice`, `sequence`, `example`, `mistake`, `exception`, `deck_code`, `x_insight`, or `youtube_segment`. Every non-rejected critical or material claim must route to `main`.

### Checkpoint

`checkpoint_id`, `pass`, `created_at`, the five gap-detection lists, saturated/unsaturated branches, and next actions.

### Semantic audit

Schema `1.1` uses `semantic_audit_id`, `claim_id`, `evidence_id`, `source_id`, `semantic_support`, the four match booleans, `reviewer_status`, `reviewer_basis`, and `audited_at`. Use the [semantic audit template](templates/semantic-audit.md). Critical claims require an exact passing record at final validation; material claims may use a scoped partial warning.

## Validator guarantees

The deterministic validator checks:

- required files and parseable JSON/JSONL;
- required manifest values, allowed lifecycle states, and a required valid `output_profile` for schema `1.1`;
- ID uniqueness;
- evidence-to-source and evidence-to-claim references;
- claim-to-evidence references;
- basic required fields;
- execution/access timestamps and checkpoint gap-list shapes;
- schema 1.1 provenance policy, snapshot containment, SHA-256 shape, and actual snapshot hash;
- semantic-audit references, verdict values, match fields, and final critical/material coverage;
- editor-ready section links on query/evidence/claim/community records, plus allowed dispositions, omission reasons, and useful-data types on evidence/claim/community records when the feature flag is enabled;
- final audit/readiness conditions.

At final stage, the handoff must repeat the manifest output profile and audit status, declare a valid delivery status, and record `bundle_validation: pass`. An incomplete run must use `delivery_status: not_ready`; `pass_with_warnings` cannot claim plain `ready`.

An `editor-ready` bundle additionally requires non-empty source and claim ledgers, at least one critical/material reviewed claim, a structurally valid `report.md`, source links bound to `sources.jsonl`, and a passing `clarity_review` with all six preservation checks, reviewed claim IDs, and matching report/claim/source hashes. Style warnings remain visible but do not by themselves fail an otherwise faithful document.

A coverage-enabled `editor-ready` final additionally requires a completed `plan.json`, complete section links and dispositions in the relevant ledgers, a passing `audit.json.coverage_review`, and handoff `coverage_preservation: pass`. The review accounts for every evidence, claim, and community record and always freezes `manifest.json`, `plan.json`, all eight JSONL ledgers (`queries`, `sources`, `evidence`, `claims`, `community`, `contradictions`, `checkpoints`, and `semantic-audit`), and `report.md`. It also freezes `useful-data.md` when the bank is required, contains routed records, or merely exists, including in a `quick` run; it freezes `evidence-appendix.md` when any record uses `appendix`. Every `deep` or `exhaustive` editor-ready run requires a non-placeholder `useful-data.md` even when no evidence appendix is requested.

Every record routed to `useful_data` or `appendix` must be explicitly accounted for by visible ID in a Markdown block with substantive ordinary text and a direct clickable URL matching a source connected through that record's evidence. A shared block is allowed only when it shows every included ID and a matching evidence-linked source for each record. An ID or URL hidden in code, a link destination, HTML attributes, comments, or explicitly hidden HTML does not satisfy this rule.

It cannot prove that a source is authoritative, an excerpt is faithful, a claim is true, or a conclusion is well reasoned. Those remain evidence-protocol and Auditor responsibilities.

## Final-stage requirements

At `final` stage:

- manifest status is `complete` or `incomplete`;
- audit status is `pass` or `pass_with_warnings`;
- every critical/material non-rejected claim has linked evidence;
- unsupported critical claims are absent;
- unresolved critical claims state their impact on the main answer;
- `report.md` and `handoff.md` contain non-placeholder content.

For a coverage-enabled `editor-ready` final stage:

- every deliverable section has a final status, with an explanatory note for `excluded` or `unresolved`;
- every query, evidence, claim, and community record links to a known section;
- every evidence, claim, and community record is accounted for by its declared output disposition;
- every non-rejected critical or material claim uses `main`, and every covered section has at least one `supported`, `supported_with_conditions`, or `contested` claim routed to `main`;
- every `useful_data` record appears in `useful-data.md`, and every `appendix` record appears in `evidence-appendix.md`;
- every routed bank/appendix record has its ID in ordinary reader-visible text rather than code, link destinations, HTML attributes, comments, or hidden HTML; substantive prose beyond the link label or inline-code example; and a visible direct source link matching its linked evidence;
- `coverage_review` records the reviewed non-omitted IDs, omitted IDs, section results, review timestamp, SHA-256 for the manifest, plan, all eight JSONL ledgers, and report, plus SHA-256 for every required, routed, or present bank and applicable appendix;
- the handoff records `coverage_preservation: pass`.

An incomplete but honest run can validate structurally; its handoff must remain `not_ready` for strong downstream claims.

When `fingerprint_policy` is `required`, an unverified mutable source blocks final validation. `when-permitted` emits a warning. Use `off` only when persistence is explicitly unnecessary or prohibited; it cannot satisfy the 1.0 release benchmark for mutable sources.
