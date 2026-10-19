# Reader questions, useful progress and bounded followups

This additive contract preserves schema 1.1/1.2 bundles. Old source-language query plans still load; translated queries need explicit phrases. Existing query status names keep their meanings. Do not relabel a failed attempt as success.

## Plan from the reader's decision

An optional `plan.json` can be used with any output profile. Define `reader` (audience, knowledge level and practical task), the central question, and only subquestions that could change the answer. Quick factual lookups need no mandatory question tree. Deep guides benefit from conditions, alternatives, resource costs, exceptions and grounded cases.

```json
{
  "reader": {"audience": "returning player", "knowledge_level": "intermediate", "task": "decide when to change composition"},
  "reader_questions": [{
    "question_id": "RQ-1",
    "question": "What conditions justify changing composition?",
    "section_id": "SEC-0001",
    "priority": "critical",
    "status": "partial",
    "gap": "The missing-resource exception remains unclear",
    "claim_ids": ["CLM-0001"],
    "search_phrases": {"en": "composition switch conditions", "ru": "условия смены сборки"}
  }],
  "research_budget": {"max_queries": 30},
  "query_localization": {
    "topics": {"SEC-0001": {"en": "changing composition", "ru": "смена сборки"}},
    "entities": [{"entity_id": "ENTITY-1", "names": {"en": ["English name"], "ru": ["Русское название"]}}]
  }
}
```

Reader-question statuses: `open`, `partial`, `answered`, `excluded`; priority: `critical`, `material`, `contextual`. `answered` requires supported/supported_with_conditions `claim_ids`. `excluded` requires `gap` explaining why it does not affect the scope. Followups support the same statuses and stay open by default. Open questions stay visible even after search exhausts available directions. These statuses describe decisions, not the existing deliverable-section status enum.

Localization uses section IDs, or `__all__` for the main topic. For a one-topic CLI run, `--search-phrase 'ru=условия смены сборки'` supplies a phrase. A requested language without a phrase fails visibly. The legacy adapter uses an existing Cyrillic topic in RU or a Latin topic in EN only. The planner cannot verify fluent translation. Verify official entity localization separately; a shared `entity_id` keeps spelling variants linked. `--entity` is for explicitly language-neutral names such as a creator handle; game terms belong in localized `entities`.

## Record what changed after reading

Executed queries may carry `observations`:

```json
{
  "summary": "The inspected source limits the earlier recommendation",
  "novelty": [{"kind": "exception", "summary": "The recommendation has a resource constraint", "evidence_ids": ["EVD-0002"]}],
  "followup_questions": [{"question": "Does the advice hold without the second resource?", "parent_question_id": "RQ-1", "why_it_matters": "This may reverse the recommendation", "priority": "critical", "search_phrases": {"en": "switch missing second resource", "ru": "переход без второго ресурса"}}]
}
```

These examples illustrate the contract, not game advice. Valid novelty kinds are `fact`, `condition`, `exception`, `counterevidence`, `confidence_change`, `contradiction_resolved`. Every item needs evidence from an inspected result source. Semantic support remains the independent auditor's responsibility. A model discussion is never a source. New counterevidence linked by a claim also counts as useful progress without adding a new claim ID.

`plan_queries.py RUN --question-gaps --json` queues open questions and source-grounded followups with priority, parent question, origin query/source IDs and rationale. It deduplicates normalized questions and queries, reuses pending IDs, and counts attempted plus outstanding queries against `research_budget.max_queries` or `--max-queries`. Adaptive defaults are 10/30/60 total attempts for quick/deep/exhaustive; ceilings, not quotas. Budget exhaustion leaves gaps visible. Failed attempts are not automatically retried: record a new direction when access conditions or the question change. `--coverage-gaps` remains a separate platform/section queue.

## Honest progress and stopping

`search_coverage.py` reports planned queries separately from attempts, successful searches, queries with inspected sources and queries yielding useful evidence. `skipped` is not attempted. Failed/blocked attempts cannot cover a family or count as a challenge search. A successful `no_results` search can document a search family or challenge attempt, but never a studied source or saturation.

Saturation needs three consecutive distinct inspected materials with no useful content; repeated URLs, share links, snippets, empty results and failures do not advance that count. Useful conditions, exceptions, counterevidence and evidenced confidence changes reset it. Pending directions prevent saturation. A saturated branch can still have an unresolved question, so `completion_status` stays `incomplete`; `search_exhausted` means only the bounded search condition was met, never factual approval or publication readiness. Preserve unresolved questions, their effect on advice and the reason for stopping.

## Source context

Retain author/publisher/type, publication/update/content/access dates, period/patch/season, evidence locators and timestamps, `lineage_id`, `upstream_sources`, limitations, expertise and conflicts. Statistics can additionally use `statistical_context` with `sample_size`, `population`, `rank`, `time_window`, `filters`, `methodology`; unknown values stay unknown. A community lead is not a population statistic. Copies of one upstream source do not establish independent corroboration.

The planner and report validate structure and links. They do not translate, search the web, inspect sources or prove conclusions on behalf of the researcher. Current freshness uses the separate [freshness contract](freshness-policy.md).
