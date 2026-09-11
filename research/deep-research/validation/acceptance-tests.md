# Simulated Acceptance Tests

These are routing and invariant simulations, not live factual Hearthstone research. No source, game fact, or conclusion is claimed from the simulations.

## Chinese Hearthstone ingestion

- A valid IYingdi fixture with `服务器：国服`, games, win rate, rank window, and one 30-card deck must validate and classify as `CN_META`.
- `本人构筑` plus a CN ladder result may classify as `CN_ORIGINAL` only after a completed western-match check finds no match.
- A 28/30 overlap with a western deck must classify as `CN_VARIANT` and preserve added/removed DBF IDs.
- A GamerSky repost with western attribution must preserve the original lineage and classify as `WESTERN_REPOST`, not independent evidence.
- A 17173 compilation containing twenty valid codes must return twenty source-to-deck relationships.
- CAPTCHA, login, SPA shell, 403, 429, dead URL, and provider-account failures must never be recorded as successful content.
- A Bilibili payload must preserve subtitle timestamps and produce structured evidence only for strategy-bearing segments.
- Configuration reports and all error/result envelopes must omit Scrape.do and Koloda API secret values.

## Test 1 — narrow factual research

### Prompt

`What exactly determines Dark Gift pool?`

### Activated configuration

- Mode: `deep` because no explicit depth was supplied; execution remains compact because the question has one factual mechanics branch.
- Type: fact-check + explanatory.
- Adapters: gaming + Hearthstone.
- Current context: Battlegrounds mode, current patch and season must be established before accepting rule evidence.
- Modules: research protocol, Search/Web strategy, source policy, evidence protocol, verification, freshness, confidence, quality gate, output policy.
- Community analysis: not required unless official rules are incomplete and community testing becomes evidence.

### Pipeline

1. Interpret “pool” and split candidate dimensions such as Tavern Tier, charge/timing, exclusions, and season-specific systems.
2. Use ChatGPT Search/Web to discover and open current Blizzard rules/patch notes and relevant first-party data.
3. If official text is incomplete, seek reproducible current-patch tests or datamining without promoting them to official fact.
4. Build atomic mechanics claims and verify version compatibility.
5. Challenge the preliminary rule with edge-case and changed-patch queries.
6. Audit semantic support, current patch, and any undocumented inference.

### Weakness discovered and correction

Risk: the default `deep` source orientation could be mistaken for a quota and inflate a narrow official fact. The protocol now states that depth does not change truth standards, source ranges are non-binding, and one decisive current primary source may establish a narrow fact. Saturation stops the branch once new quality sources add nothing material.

### Simulated result

`pass_with_warnings`: the route is correct; actual confidence depends on whether current official pool rules are explicit. The workflow must return an unresolved narrow point rather than infer it if primary and reproducible evidence are absent.

## Test 2 — strategic research

### Prompt

`When should the first Dark Gift be used?`

### Activated configuration

- Mode: default `deep`.
- Type: strategic + statistical + community intelligence.
- Adapters: gaming + Hearthstone.
- Conditional modules: freshness, contradiction search, community intelligence, confidence.
- Required context: current patch/season, MMR range, and the outcome behind “should” such as survival, average placement, top-four rate, or win rate.

### Pipeline

1. Split immediate use, intermediate-tier use, and holding for later; add economy, tempo, leveling, health, hero, lobby, and synergy conditions.
2. Discover current mechanics, datasets, high-MMR analyses, Reddit/forum discussions, YouTube explanations, and X statements with ChatGPT Search/Web.
3. Open sources and collect claim-sized statistics, expert reasoning, and bounded community patterns.
4. Check sample, timeframe, patch, MMR/rank, filters, decision-point availability, and survivorship/selection bias.
5. Search specifically for why the leading timing is bad or why another tier is better.
6. Build the evidence matrix and write only a conditional recommendation that survives audit.

### Weakness discovered and correction

Risk: “best timing” is undefined and could let the system optimize the wrong outcome. The research plan now requires operational definitions and success criteria before search. The Hearthstone adapter also separates tempo/survival, economy, leveling, placement metrics, and lobby/MMR conditions.

Risk: multiple creator posts may repeat one dataset. Source records now include `lineage_id`, and verification separates independent measurement from independent interpretation.

### Simulated result

`pass`: all required evidence streams, contradiction search, version controls, and conditional wording are routed. A universal answer would fail the superlative/strategy gates unless comparative evidence justified it.

## Test 3 — exhaustive editor-ready article materials

### Prompt

`Подготовь материалы для редактора к полной статье о Dark Gifts.`

### Activated configuration

- Mode: inferred `exhaustive` because the request demands complete article materials.
- Deliverable: inferred `editor-ready` because “для редактора”, “для статьи”, and “подготовь материалы” are editorial-intent cues.
- Modifier: `raw-research` is not activated because the user did not explicitly request a raw dossier, evidence matrix, source dump, or equivalent unprocessed research artifact.
- Operations: persistent research bundle with stable IDs, pass checkpoints, final integrity validation, the Research Auditor's factual pass, a separate Clarity Editor, and editor handoff.
- Type: factual mechanics + statistical + strategic + expert + community intelligence + fact-check.
- Adapters: gaming + Hearthstone.
- Modules: all core and conditional protocols.

### Pipeline

1. Build a recursive tree covering mechanics, pool generation, charges/timing, economy, combat, scaling, leveling curves, heroes, tribes/minion types, cards/minions, synergies, season systems, mistakes, community positions, statistics, counterexamples, and patch history. Persist the future document outline in `plan.json` with stable `SEC-0001`-style IDs.
2. Execute discovery, deep collection, gap, contradiction, freshness, and audit passes; add more targeted passes only for named gaps.
3. Maintain branch coverage, source lineage, claim/evidence records, community position maps, and contradiction reports.
4. Test saturation separately for every major branch. Source count cannot compensate for an untouched branch.
5. Run the Research Auditor's factual pass, freeze claim status and limitations, and remove or qualify unsupported statements before any prose-simplification pass.
6. Run a separate Clarity Editor after the factual audit. It may simplify structure and Russian wording, but must not change facts, numbers, conditions, confidence, links, or limitations.
7. Produce an editor-ready main section in plain Russian, a section-organized `useful-data.md`, and a clearly separated Evidence Appendix with Claim → Evidence → Source traceability.
8. Run `coverage_review` across every planned section and every evidence, claim, and community record; freeze the manifest, plan, all eight JSONL ledgers, report, useful-data bank, and applicable appendix, then require handoff `coverage_preservation: pass`.
9. Validate the completed bundle and mark the handoff `ready`, `ready_with_warnings`, or `not_ready` from audit and integrity results.

### Weakness discovered and correction

Risk: “complete” could cause endless searching or false completeness. The protocol now uses per-branch saturation plus bounded language and forbids “I studied everything.”

Risk: a fixed 50–150 target could reward URL padding. The range is explicitly orientation only; evidence quality, independence, branch coverage, and material novelty control completion.

Risk: the auditor could be interpreted as requiring a separate subagent. Architecture now defines it as a role contract usable in a single-agent environment.

Risk: an editorial request could be misrouted to a raw research dump and force the editor to reconstruct the useful narrative. Output routing now treats article/editor/material-preparation intent as `editor-ready`; raw mode requires an explicit request for an unprocessed dossier or evidence matrix.

Risk: clarity editing could silently strengthen, flatten, or drop audited claims. The Clarity Editor is a distinct pass after the Research Auditor's factual pass and must preserve citations, uncertainty, scope conditions, and known gaps while simplifying the Russian prose.

### Simulated result

`pass`: the exhaustive route covers recursive planning, multi-pass research, gaps, community, statistics, contradictions, freshness, saturation, factual audit, and a separate clarity pass. The main deliverable is editor-ready, written in plain Russian, and separated from its Evidence Appendix without losing source links or limitations.

## Test 4 — explicitly requested raw research

### Prompt

`Собери сырое исследовательское досье по Dark Gifts: нужна evidence matrix, без редакционной обработки.`

### Activated configuration

- Mode: `deep` unless the requested coverage independently requires `exhaustive`.
- Output profile: explicit `raw-research` because the user directly requested a raw dossier and evidence matrix.
- Deliverable: structured claims, evidence, sources, contradictions, rejected claims, limitations, and unresolved gaps; no editor-ready narrative is implied.
- Operations: persistent research bundle, the Research Auditor's factual pass, referential-integrity validation, and raw handoff.

### Pipeline

1. Plan and collect evidence at the requested depth.
2. Preserve atomic claims, evidence records, source lineage, contradictions, gaps, and limitations without converting them into editorial prose.
3. Run the Research Auditor's factual pass and retain rejected, contested, and unresolved records with their statuses.
4. Validate every Claim → Evidence → Source link and export the requested evidence matrix or dossier.

### Simulated result

`pass`: explicit raw intent selects `raw-research`. The output remains structured and traceable; it is not silently converted into an article or passed through the editor-ready Clarity Editor.

## Test 5 — current constructed deck guide

### Prompt

`Подготовь подробный гайд на Пират-воина для текущего патча.`

### Activated configuration

- Mode: `deep`; use `exhaustive` only when the user explicitly asks for a complete, global, or reusable evidence base.
- Output profile: `editor-ready`.
- Type: current meta + comparative statistics + strategic + expert/community intelligence.
- Modifiers: `current-patch-only`, `statistics-heavy`, and `creator-heavy`.
- Adapters: gaming + Hearthstone.
- Source emphasis: X `high`, YouTube `high` when the providers are available and the user has not set a tighter cost limit.

### First visible action

Before any web search, show the user a concise `Структура поиска` and continue automatically:

1. почему колода важна в текущей игровой среде;
2. актуальные варианты и проверенные коды колод;
3. сравнение вариантов и критерии выбора сильнейшего;
4. назначение карт, гибкие места и замены;
5. выбор стартовой руки, включая условия для разных противостояний;
6. план игры по этапам и условия для смены стратегии;
7. ключевые противостояния и тактические изменения;
8. частые ошибки и сложные решения;
9. рекомендуемый список, альтернативы, граница актуальности и нерешённые вопросы.

### Pipeline

1. Establish current format, patch, expansion, rank/region window, and the criterion behind “strongest.”
2. Map every outline section to answerable leaves, required evidence classes, X/YouTube relevance, and a readiness condition; do not begin with one generic `Пират-воин guide` query.
3. Use built-in ChatGPT Search/Web for official context and original-source inspection, then collect comparable current lists and statistics. Preserve filters, samples, dates, and source lineage.
4. Validate deck codes and resolve reader-facing Russian card names through the correct KHS records. Name resolution does not by itself prove current legality or strength.
5. When GetXAPI is available, run separate query families for builds, card choices, starting-hand decisions, opposing decks, mistakes, named experts, corrections, and counterpositions. Inspect direct posts and thread context. If it is unavailable, use Search/Web where possible, record X coverage as `PARTIAL` or `BLOCKED`, and lower confidence for claims that depended on it.
6. When TranscriptAPI is available, run separate YouTube query families for current guides, coaching, ladder or tournament demonstrations, opposing decks, and mistakes. Verify creator identity and gameplay patch, then attach relevant timestamped segments to the sections they inform. If it is unavailable, use the documented public-caption/Search/Web reserve routes, preserve the fallback label, and mark remaining YouTube coverage `PARTIAL` or `BLOCKED`.
7. Seek at least two independent qualified creator perspectives across X and YouTube for central strategic advice when accessible. Repetition from one list or dataset remains one lineage.
8. Compare creator reasoning with statistics and official/current data, search for contradictions, and stop each section at saturation rather than consuming provider allowance for volume.
9. Run the factual audit, then produce plain Russian reader copy. Use `выбор стартовой руки` and `смена стратегии`; do not expose `муллиган`, `пивот`, internal IDs, or provider diagnostics in the main guide.

### Simulated result

`pass`: the route gives the user an understandable plan before searching, allocates additional X and YouTube effort to the sections where it adds value, and still requires current comparable data and audited evidence before recommending a build.

## Editor-ready acceptance criteria

An editorial-intent run passes only when all of the following are true:

1. Requests containing intent such as “для статьи”, “для редактора”, or “подготовь материалы” select `editor-ready` unless the user explicitly asks for a raw dossier, evidence matrix, source dump, or equivalent raw artifact.
2. The Research Auditor's factual pass completes before the Clarity Editor. A failing factual audit blocks a polished `ready` result.
3. The Clarity Editor is a separate role/pass. It simplifies wording, ordering, and sentence structure, but cannot introduce, remove, strengthen, or generalize factual claims.
4. The main editorial section uses plain, natural Russian: short direct sentences, explained specialist terms, and no avoidable bureaucratic, academic, or machine-like phrasing.
5. Detailed evidence records live in a clearly labeled Evidence Appendix rather than interrupting the main reading flow. The appendix remains linked to the claims it supports.
6. Source links survive the clarity pass and remain attached to the relevant claims or appendix records; link preservation is not satisfied by an unreferenced bibliography alone.
7. Limitations, uncertainty, current-patch boundaries, sample constraints, contradictions, and unresolved gaps remain visible and are not softened for readability.
8. The final handoff keeps the editor-ready main section and Evidence Appendix distinguishable without breaking Claim → Evidence → Source traceability.
9. A persistent run cannot pass final validation until `clarity_review` records that claims, numbers, scope, citations, limitations, and contradictions survived the rewrite.
10. Every newly initialized persistent `editor-ready` run enables `coverage_contract_version: "1.0"`, keeps stable `SEC-0001`-style sections in `plan.json`, and maps each query, evidence, claim, and community record to at least one known section.
11. Only evidence, claim, and community records receive `output_disposition: main | useful_data | appendix | omit`; query records receive section links but no output destination. `omit` requires `output_omit_reason`; `useful_data` requires at least one allowed `useful_data_types` value.
12. Every non-rejected critical or material claim uses `output_disposition: main`. A section cannot finish as `covered` unless it has a linked query, retained records, and at least one `supported`, `supported_with_conditions`, or `contested` claim routed to `main`.
13. A `deep` or `exhaustive` editor-ready run includes a non-placeholder `useful-data.md`; any record routed to `appendix` requires a non-placeholder `evidence-appendix.md`. A bank that merely exists in a `quick` run is also validated and hashed.
14. Every `useful_data` or `appendix` record is explicitly accounted for by visible ID in a Markdown block, contains substantive ordinary text, and includes a direct clickable source URL matching evidence linked to that record. A shared block must show every included ID and the matching source for each record. IDs or URLs hidden in comments, code, link destinations, HTML attributes, or explicitly hidden HTML do not pass.
15. Final `coverage_review` accounts for non-omitted and omitted record IDs, covers every plan section, and freezes `manifest.json`, `plan.json`, all eight JSONL ledgers, `report.md`, every required/routed/present useful-data bank, and every applicable appendix. The handoff states `coverage_preservation: pass` only after those checks pass.
16. Existing schema 1.1 bundles without `coverage_contract_version` remain valid under the legacy contract and are not silently migrated.

## Russian Hearthstone publication acceptance

A Russian `editor-ready` Hearthstone document passes only when:

1. Each named card, hero, hero power, Battlegrounds entity, or seasonal object is matched to the correct mode and a stable DBF or exact card identity before publication.
2. The displayed Russian name comes from the matching `api.kolodahearthstone.com` record. A transcript spelling, English source name, fuzzy text match, or model translation does not replace exact resolution.
3. Missing entities, missing Russian localization, mode conflicts, and API failures remain explicit unresolved gaps; the system never invents a Russian name.
4. Mode legality, active-pool status, patch relevance, and statistical strength are verified separately from name resolution.
5. Unexplained research and gaming anglicisms are replaced with plain Russian. Official or genuinely useful player terms receive a short explanation on first use.
6. DBF IDs, API paths, internal fields, and preserved original names stay in the evidence base or appendix unless the reader needs them for disambiguation.

## Acceptance summary

| Requirement | Test 1 | Test 2 | Test 3 | Test 4 | Test 5 |
|---|---:|---:|---:|---:|---:|
| primary mechanics | yes | yes | yes | yes | as needed |
| current version/patch | yes | yes | yes | yes | yes |
| statistics context | conditional | yes | yes | as requested | yes |
| experts/community | fallback only | yes | yes | as requested | X + YouTube high |
| contradiction search | yes | yes | yes | yes | yes |
| recursive tree | bounded | yes | all major branches | requested scope | future sections |
| gap detection | yes | yes | yes | yes | yes |
| saturation | branch | branch | all major branches | requested scope | each guide section |
| factual audit | yes | yes | before clarity | yes | before clarity |
| editor-ready main section | no | optional | yes | no | yes |
| separate Clarity Editor | no | optional | yes | no | yes |
| separate Evidence Appendix | no | optional | yes | evidence matrix itself | yes |
| section-organized useful-data bank | no | optional | yes | no | yes |
| frozen coverage review | no | optional | yes | no | yes |
| explicit raw-research route | no | no | no | yes | no |

All five simulations preserve the invariant that Search/Web discovery precedes inspected evidence, and validated evidence precedes strong synthesis. Editorial polish never precedes factual audit, and it never removes source links or limitations.
