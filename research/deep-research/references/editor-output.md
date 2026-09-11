# Editor-ready Output

## Purpose

Use the `editor-ready` output profile to hand validated research to a human editor in a form that can be understood and developed without opening the research bundle. The default result is a concise Russian Markdown document, not a raw database and not an automatically publication-ready article.

The output router selects this profile by default for article, guide, content, publication, editor, and writer requests. It also applies when the user asks for `editor-ready`, an editorial brief, or an accessible synthesis of completed research. If the user explicitly requests another language, use it instead.

## Deliverables

Produce:

1. the main document using [templates/editor-ready.md](templates/editor-ready.md);
2. for every `deep` or `exhaustive` run, a separate `useful-data.md` using [the useful-data template](templates/useful-data.md);
3. a separate evidence appendix using [templates/evidence-appendix.md](templates/evidence-appendix.md) only when requested or materially useful for fact-checking.

The main document must remain self-contained when the appendix is absent. Do not paste the full evidence matrix, source ledger, or audit log into it.

`useful-data.md` is a reader-facing bank of validated material, not an audit dump. Save it beside the main document for a file-backed run. When files are not available, return it as a separate Markdown artifact with the same name. It must not be merged into the main document merely because both are Markdown.

New persistent `editor-ready` runs use the additive `coverage_contract_version: "1.0"`. The contract applies at every depth, while `useful-data.md` is mandatory only at `deep` and `exhaustive`. Existing schema 1.1 bundles without this feature flag retain their legacy validation behavior.

## Main document contract

The editor should see the answer before the research process. Use a working title and only the sections that help:

- `Коротко` — two to four sentences with the main answer and the relevant as-of, patch, version, season, or other time boundary;
- `Контекст` — scope and definitions the editor needs to interpret the findings;
- `Основной материал` — findings arranged by meaning, with descriptive subheadings where useful;
- `Что важно не исказить` — material conditions, exceptions, wording limits, and editorial traps;
- `Что остаётся неясным` — only unresolved points that could change the story;
- `Ключевые источники` — optional short list when it improves navigation.

Do not print empty sections. Adapt headings to the subject when that improves clarity, but keep the result compact and scan-friendly.

## Clarity Editor boundary

Run the Clarity Editor only after the Research Auditor has finished. It improves presentation without re-researching or silently changing the record.

It may reorder findings, shorten repetition, explain terms, replace internal labels with plain language, use descriptive headings, and consolidate duplicated caveats. It must not change claims, numbers, scope, citations, confidence, limitations, unresolved disagreements, or factual audit status. If clarity requires a factual change, return the issue to research instead of editing around it.

## Conversion rules

- Write in ordinary editorial language. Explain an unfamiliar term on first use.
- Prefer a clear Russian phrase over an unexplained English research or gaming term. Keep an English term only when it is an official name or necessary for source matching, and explain it on first use.
- For Russian Hearthstone material, apply the official naming and terminology gate in [the Hearthstone adapter](domains/hearthstone.md); never translate an entity name from memory.
- Preserve the exact scope of each finding: date, version, population, region, mode, sample, and material conditions.
- Put direct links to inspected original sources next to consequential claims. A bibliography does not replace claim-level citation.
- Keep numbers interpretable: name the metric, timeframe, sample or denominator when available, and the most important bias or limitation.
- Express confidence through calibrated prose such as `данные уверенно показывают`, `доступные данные указывают`, or `пока нельзя надёжно заключить`.
- Separate established facts, source opinions, community observations, and researcher inference.
- Retain useful counterevidence and exceptions. Do not strengthen `may` into `does`, a sample into a universal rule, or correlation into causation.
- Do not expose `QRY`/`SRC`/`EVD`/`CLM`/`COM`/`CTR` IDs, YAML records, tool logs, audit checklists, or bundle lifecycle fields in the main document.
- Do not add a clickbait angle, SEO claims, quotations, or narrative details that the evidence does not support.

Readability orientations are warnings, not permission to delete nuance: investigate sentences over 30 words, paragraphs over 80 words or four sentences, more than three tables, and tables wider than four columns. Split or rephrase when that improves comprehension; retain a longer unit when the evidence genuinely requires it.

## Useful-data bank

For `deep` and `exhaustive` editor-ready work, preserve validated material that is useful downstream but not necessary for the reading flow in `useful-data.md`. Organize it by the planned or final deliverable sections so an editor can move directly from a section to its supporting numbers, comparisons, advice, sequences, examples, mistakes, exceptions, deck codes, X findings, and YouTube segments.

Each item must contain the stable section ID and title, one or more allowed `useful_data_types`, bounded content, visible linked record IDs, direct inspected source links, the as-of and relevant version boundary, conditions or limitations, and an explicit output disposition. Put the useful content in an ordinary substantive Markdown paragraph, not in YAML, a comment, a table-only row, or a code fence; an ID inside fenced or indented code is not visible coverage, and a long link label is not substantive content. The direct clickable link in the same item block must match a source connected to that record through its evidence. Use [the template](templates/useful-data.md) and split independently checkable statements instead of hiding several claims inside one item.

Queries map to deliverable sections but do not receive an output destination. Assign every evidence, claim, and community record exactly one canonical destination: `main`, `useful_data`, `appendix`, or `omit`. `omit` requires a non-empty `output_omit_reason`; `useful_data` requires one or more `useful_data_types` from `number`, `comparison`, `advice`, `sequence`, `example`, `mistake`, `exception`, `deck_code`, `x_insight`, or `youtube_segment`. Every non-rejected critical or material claim routes to `main`, and each section marked `covered` retains at least one `supported`, `supported_with_conditions`, or `contested` `main` claim. An item may be indexed in the bank even when its selected wording also appears in the main report; do not duplicate whole paragraphs. A material warning or condition needed to interpret the answer must remain in the main document even if the bank contains more detail.

The bank is not a quota-filling exercise. Retain items that add a distinct number, comparison, decision rule, practical sequence, example, mistake, exception, verified code, or source-specific insight. Consolidate true duplicates and record a gap when a planned section lacks useful evidence.

## Preservation review

Before editing, freeze the list of material claims and, for each one, its numbers, scope, attached source links, limitations, and unresolved contradiction status. After editing, compare the final document against that list item by item. A material item may move or be phrased more simply, but it may not disappear, become stronger, lose its citation, or lose a condition that changes interpretation.

For a `deep` or `exhaustive` run, also confirm that every non-omitted record appears in its declared destination and that every omitted record has a reason. The clarity pass may shorten the main document by moving supporting detail into the bank, but it may not silently discard the detail.

For a persistent `editor-ready` run, record this review under `audit.json.clarity_review`. Set `status: pass` only when `claims_preserved`, `numbers_preserved`, `scope_preserved`, `citations_preserved`, `limitations_preserved`, and `contradictions_preserved` are all true and `reviewed_at` is recorded. List every reviewed critical/material claim in `reviewed_claim_ids`. Bind the review to the exact checked artifacts with SHA-256 values for `report.md`, `claims.jsonl`, and `sources.jsonl`; any later edit invalidates the review. Every visible citation URL must also resolve to a recorded requested or final source URL after safe fragment/timestamp normalization. Any false, missing, stale, or uncertain item returns the document to the factual workflow and blocks a ready handoff. `scripts/validate_editor_output.py` checks presentation and obvious leakage; it does not replace this semantic comparison.

For a coverage-enabled run, also record `audit.json.coverage_review`. It must enumerate every planned section and every evidence, claim, and community record; confirm that section coverage and dispositions were preserved; and separate reviewed non-omitted IDs from omitted IDs. It always freezes `manifest.json`, `plan.json`, all eight JSONL ledgers (`queries`, `sources`, `evidence`, `claims`, `community`, `contradictions`, `checkpoints`, and `semantic-audit`), and `report.md`. It additionally freezes `useful-data.md` whenever the bank is required, has routed records, or is present even for a `quick` run, and freezes `evidence-appendix.md` whenever any record routes there. Final handoff requires `coverage_preservation: pass`. Changing a frozen artifact invalidates the review and requires it to be repeated.

## Warnings and readiness

Material uncertainty belongs beside the affected statement and, when useful, in `Что важно не исказить`. The appendix may expand a warning but must never be the only place it appears.

- With `pass`, write the normal editor-ready document.
- With `pass_with_warnings`, keep the usable conclusions and state each material warning in plain language.
- With `fail` or a `not_ready` handoff, do not simulate a finished brief. Deliver an explicitly incomplete editorial note that identifies what is established, what failed verification, and which claims must not be published as fact.

## Optional evidence appendix

Add the appendix when the user asks for claim-level provenance, a fact-check dossier, or a handoff that another person must audit. It can also be useful for contested findings or substantial methodological limitations.

For each consequential claim, show the bounded wording, status, confidence, decisive source links, relevant counterevidence, and limitations. Internal claim/evidence/source IDs may appear there when a persistent bundle exists, but plain-language source names and direct links remain required.

## Final check

Before delivery, confirm that:

- the main answer is visible in the opening section;
- the document states the time or version boundary when it affects the answer;
- every consequential external claim has an adjacent inspected source;
- internal research mechanics are absent from the main document;
- uncertainty and exceptions survived the rewrite;
- every `deep` or `exhaustive` editor-ready run includes a section-organized `useful-data.md`;
- every query maps to one or more `SEC-0001`-style sections and every evidence, claim, and community record has an explicit canonical output disposition;
- every non-rejected critical/material claim routes to `main`, and every covered section has at least one `supported`, `supported_with_conditions`, or `contested` `main` claim;
- every validated useful item reaches its declared destination, while `omit` records retain their reasons;
- each bank/appendix record shows its ID, substantive ordinary text, and a direct visible link matching its linked evidence source;
- any evidence appendix is separate and optional;
- a present `quick` bank is validated and hashed even when it was not required;
- a file-backed main document passes `scripts/validate_editor_output.py`;
- a coverage-enabled final bundle has a passing frozen `coverage_review` and handoff `coverage_preservation: pass`.
