# Architecture Self-Audit

## Status

`pass`

## Audit scope

- activation and default-mode behavior;
- progressive-disclosure routing;
- ChatGPT Search/Web boundary;
- claim-to-evidence traceability;
- source independence and freshness;
- statistics and community handling;
- contradiction search and confidence;
- completion, saturation, and failure behavior;
- deliverable routing between editor-ready and explicitly requested raw research;
- factual-audit and Clarity Editor role separation;
- plain-Russian editorial quality and evidence-appendix boundaries;
- official Russian Hearthstone entity names and terminology across modes;
- untrusted web-content handling and data minimization;
- persistent-run reproducibility and referential integrity;
- package links, metadata, and scaffold residue.

## Issues found and resolved

| Issue | Risk | Resolution |
|---|---|---|
| Flat requested tree conflicted with current Skill progressive disclosure | unnecessary context loading | moved methods under `references/`, kept a concise orchestration entrypoint, documented the choice in architecture |
| Built-in web capability was implicit | the runtime might treat search snippets as evidence | explicitly named ChatGPT Search/Web in the entrypoint, architecture, search strategy, README, examples, and tests; required opening original sources |
| Default deep mode could conflict with narrow factual research | URL padding and wasted work | made source ranges non-binding and allowed one decisive primary source for a narrow fact; saturation controls stopping |
| Fixed source orientations could become completion quotas | fake completeness | made per-branch novelty and quality gates the completion test |
| Strategy claims and official facts have different burdens | over- or under-verification | added claim-dependent authority and verification rules |
| Multiple URLs could hide one evidence origin | false corroboration | added `lineage_id`, upstream-source fields, and independence checks |
| Old sources can be either valid or stale | date-only freshness errors | added current/source version comparison and six freshness statuses |
| Community repetition could be presented as consensus | prevalence overclaim | added independent-mention, platform, expertise, counterargument, and bounded-language requirements |
| “Auditor” could imply a required separate agent | runtime incompatibility | defined it as an adversarial role contract, not a deployment dependency |
| Editorial requests were automatically routed to raw research | “для статьи”, “для редактора”, and “подготовь материалы” could return an evidence dump instead of usable editorial material | these cues now select `editor-ready`; `raw-research` requires an explicit request for a raw dossier, evidence matrix, source dump, or equivalent artifact |
| Factual review and prose cleanup could be conflated | readability edits could strengthen claims, erase conditions, or introduce unsupported statements | added a separate Clarity Editor pass that runs only after the Research Auditor's factual pass has fixed claim status and limitations |
| Technically correct output could remain difficult for a Russian editor to use | academic, bureaucratic, or machine-like prose would shift rewriting work downstream | editor-ready acceptance now requires plain natural Russian, direct sentences, and explained specialist terms |
| Evidence detail could overwhelm the editorial narrative | claim ledgers and audit records could make the main material unreadable | editor-ready output now separates a clean main section from a labeled Evidence Appendix while retaining Claim → Evidence → Source linkage |
| Clarity editing could drop citations and caveats | polished text could become less auditable or more certain than the evidence | source links, patch/sample boundaries, uncertainty, contradictions, limitations, and unresolved gaps are immutable through the clarity pass; persistent editor-ready bundles require a recorded six-part preservation review |
| Hearthstone names could be translated from English, Chinese, or memory | wrong localized names and same-name entities from another mode could reach publication | require exact mode plus DBF/card identity, use the matching KHS Russian field, and keep missing or conflicting names unresolved |
| Russian Hearthstone copy could remain full of unexplained anglicisms | editors and general readers would still need to decode the report | added a contextual plain-Russian terminology map and first-use explanations without changing official KHS names |
| A failed audit lacked safe output behavior | confident unsupported conclusion | `fail` now blocks confident synthesis and requires targeted search, claim reduction, or incomplete-report labeling |
| Web pages could contain instructions aimed at the researcher | prompt injection, secret disclosure, or unauthorized action | added an explicit untrusted-content boundary, safe-tool rules, secret minimization, and a Quality Gate check |
| Large research could not be resumed or handed off reproducibly | lost provenance and repeated discovery | added a persistent bundle with manifest, ledgers, checkpoints, stable IDs, lifecycle states, and handoff contract |
| A polished report could hide broken Claim → Evidence links | false professional readiness | added a deterministic final-stage validator and made its failure block `ready` status |
| Bundle initialization could overwrite user work | data loss | initializer refuses every non-empty target; integration test confirms preservation |
| “Pool” was treated as one Hearthstone mechanic | evidence for offer eligibility could be misapplied to finite-copy depletion | split offer, shared-copy, generation, and active-content pools before research |
| Statistics-heavy mode assumed public decision data would be found | community heuristics could be mislabeled as an optimum | added a bounded evidence-availability gate and mandatory confidence downgrade |
| Launch documentation could hide later partial patches | stale row values in a current guide | added chronological baseline-plus-overlay reconstruction and row-level provenance |
| Bundle timestamps were documented but not fully enforced | incomplete provenance could still validate | validator now checks query/source/checkpoint timestamps and checkpoint gap-list shapes |
| Release metrics could be self-reported | a polished result file could hide false traceability or missing fingerprints | release validation now recomputes metrics from each linked final bundle and rejects tampering |
| Long-running bundles lacked operator commands | resume/export behavior depended on memory and ad hoc packaging | added validated `resume`, `compare`, deterministic `export`, and gated `release` operations |

## Residual warnings

- The Skill cannot guarantee access to X, Reddit, YouTube, paywalled sources, deleted posts, or private datasets. Runtime must disclose missing coverage.
- Source-count orientations remain inherently topic-dependent; the text repeatedly marks them non-binding.
- Live sources remain mutable after the recorded access date; current claims must be re-run after relevant change events.
- Deterministic validation and semantic audit reduce but cannot mathematically prove source truth; human review remains appropriate for high-stakes release use.
- Deterministic clarity checks cannot by themselves prove that Russian prose is natural or that simplification preserved meaning; semantic review remains part of the editor-ready acceptance contract.
- KHS availability and localization coverage can change; a missing or stale response must remain a visible gap and does not establish current mode legality or pool membership.

## Verification evidence

- The package audit checks required artifacts, internal Markdown targets, matching Skill name, invocation metadata, and unfinished markers.
- The official Skill validator checks frontmatter and packaging.
- Twenty live ChatGPT Search/Web cases across five domains plus two adversarial fixtures exercise all seven required benchmark categories.
- Four routing simulations distinguish ordinary synthesis, editor-ready article materials, and explicitly requested raw dossiers; the editor-ready case checks factual-audit-before-clarity ordering, plain Russian, appendix separation, and preservation of links and limitations.
- Offline resolver tests cover constructed and Battlegrounds names, automatic mode fallback, missing localization, bounded retries, invalid DBF IDs, and secret-safe Bearer authentication; live smoke checks confirmed current Russian names for a constructed card, Battlegrounds minion, hero, and trinket.
- The full regression suite covers initialization, working/final validation, migration, fingerprints, semantic gold, benchmark tampering, deterministic export, timestamps, overwrite protection, source adapters, Russian Hearthstone names, and editor-output clarity.
- Release results are derived from linked schema 1.1 bundles; every mutable benchmark source is fingerprinted and every critical claim is traceable.

No critical contradiction remains between the source-count guidance and saturation rule, the one-primary-source rule and strategy corroboration rule, the default deep mode and narrow factual execution, editor-ready routing and explicit raw-only routing, or factual audit and the later clarity pass.
