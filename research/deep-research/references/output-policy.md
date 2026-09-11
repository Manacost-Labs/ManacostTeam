# Output Policy

## Boundary

The Skill produces a research report, a raw evidence database, or an `editor-ready` brief. In `editor-ready` mode it turns validated findings into a clear document for a human editor; it does not automatically produce an SEO article, guide, news story, or publication-ready draft. Preserve material findings that a downstream Writer Skill may need.

## Normal research report

Use the sections that improve the answer:

1. Executive Summary
2. Scope and Current Context
3. Findings and Analysis
4. Contradictions and Exceptions
5. Unknowns and Limitations
6. Confidence
7. Sources

Do not print empty sections. Lead with the answer and as-of context. Organize findings around the reader's questions, using descriptive subheadings where useful. Integrate decisive evidence, statistics, expert interpretation, community signals, and counterevidence into the finding they qualify instead of creating a separate technical section for each evidence type.

Keep citations adjacent to significant claims and link directly to original inspected sources. Include methodology, the full evidence matrix, and technical provenance only when the user requests them or they materially affect interpretation; put lengthy detail in a separate appendix.

## Raw research mode

Use the raw template only when the user explicitly requests a raw dossier, full evidence matrix, audit trail, claim-level provenance, or a machine-oriented evidence database as the main deliverable. If the main deliverable is an article, guide, or editor-facing document and the user also wants fact-check material, keep `editor-ready` and add a separate evidence appendix. `exhaustive` describes research depth and never selects a profile by itself. Preserve each finding's claim, significance, primary and supporting evidence, community evidence, counterarguments, patch/version relevance, confidence, limitations, and notes for the downstream user. Include useful negative findings and unresolved gaps.

For a persistent run, deliver the validated bundle plus the [handoff template](templates/handoff.md). The handoff must state `ready`, `ready_with_warnings`, or `not_ready`; do not infer readiness from prose quality.

## Editor-ready output profile

Use this profile when the output router selects `editor-ready`. It is the default for article, guide, content, publication, editor, or writer requests unless the user explicitly asks for a raw dossier or analytical research report. Follow the [editor output contract](editor-output.md) and the [editor-ready template](templates/editor-ready.md).

The main document must be readable without the research bundle or internal evidence IDs. Lead with the answer, keep material dates, versions, conditions, and uncertainty, and cite inspected original sources next to consequential claims. Translate confidence into calibrated ordinary language instead of exposing internal labels or audit mechanics.

After factual audit, apply the separate Clarity Editor pass defined in the contract. It may simplify presentation but cannot change validated claims or evidence boundaries.

Keep the claim-level audit trail in a separate, optional [evidence appendix](templates/evidence-appendix.md). Do not make the main document depend on that appendix, and do not hide a material warning only in the appendix.

For every `deep` or `exhaustive` editor-ready run, also produce a separate `useful-data.md` using [the useful-data template](templates/useful-data.md). This bank preserves validated numbers, comparisons, advice, sequences, examples, mistakes, exceptions, deck codes, X findings, and YouTube segments by deliverable section. It is mandatory at these depths even when the user did not request an evidence appendix.

Keep the main report concise and self-contained. Put supporting detail in the bank when it improves editorial reuse, but retain the decisive answer, material conditions, limitations, and adjacent citations in the main report. The bank is not a substitute for the evidence appendix: it optimizes for useful content, while the appendix exposes claim-level fact-check provenance.

New persistent `editor-ready` bundles enable `coverage_contract_version: "1.0"` without changing schema 1.1. Their stable sections live in `plan.json`. Every query maps to one or more sections through `deliverable_section_ids`; only evidence, claim, and community records additionally receive `output_disposition: main | useful_data | appendix | omit`. `omit` requires `output_omit_reason`. `useful_data` requires one or more values from `number`, `comparison`, `advice`, `sequence`, `example`, `mistake`, `exception`, `deck_code`, `x_insight`, and `youtube_segment` in `useful_data_types`. Every non-rejected critical or material claim must use `main`, and each covered section must include at least one `supported`, `supported_with_conditions`, or `contested` `main` claim. Existing 1.1 bundles without the coverage feature flag remain compatible.

Do not silently discard an item during editorial compression. A bank or appendix item is valid only when its record ID is present in ordinary reader-visible text rather than code, a link destination, an HTML attribute, a comment, or hidden HTML; its Markdown block contains substantive ordinary prose beyond a link label or inline-code example; and it includes a direct clickable link matching a source connected through that record's evidence. Final coverage review must account for all records; freeze the manifest, plan, all eight JSONL ledgers, and report; freeze every required, routed, or merely present useful-data bank and every required appendix; and set handoff `coverage_preservation: pass` before the bundle can claim readiness.

## Evidence visibility

The full evidence matrix is internal by default. Show it when the user requests raw research, an audit trail, a fact-check dossier, or claim-level provenance. The requested main deliverable decides the profile: a dossier/database request uses `raw-research`, while an article/guide/editorial request keeps `editor-ready` and puts this detail in a separate evidence appendix. In a concise answer, surface only evidence necessary to verify key findings and explain uncertainty.

## Citation behavior

- Cite every significant externally verifiable claim.
- Prefer the original page, dataset, official document, or actual post/video.
- Do not cite a ChatGPT Search result page, snippet, or AI summary as evidence.
- Never cite a source that was not opened and checked for the attached claim.
- Preserve directness: one citation should not appear to support a paragraph of unrelated assertions.

## Bounded completeness language

Avoid “I researched everything,” “complete consensus,” or similar unprovable claims. Prefer:

- “Among the sources reviewed...”
- “Across the accessible sources...”
- “Several independent discussions...”
- “Available current-patch data indicates...”

## Uncertainty

Put limitations next to affected findings when possible, then summarize them in `Unknowns`. State what is unknown, why, and whether it could change the answer.

## Failure output

If the audit remains `fail`, deliver an incomplete research note rather than a confident answer. Identify the failed claims, missing evidence, attempted coverage, and the safest bounded conclusion, if any.

For a file-backed run, a failed final bundle validator also blocks `ready` status. Structural integrity does not prove factual truth, but broken provenance makes professional handoff unsafe.
