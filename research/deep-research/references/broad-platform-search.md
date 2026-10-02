# Broad platform search

For deep or exhaustive research, use four distinct lanes: X, Reddit, YouTube and the general web. The goal is useful independent evidence for every important section, not an arbitrary count of links. A narrow official fact can use a smaller scope; record deliberate exclusions.

Start with a section outline and short topic labels. Expand each section through names/aliases, EN and RU queries, current patch/version, creators, practical examples, mistakes and contrary opinions. If a subject has substantial Chinese material, use the existing Chinese source profiles and native aliases; do not add Chinese evidence merely to fill a quota.

| Lane | Discovery passes | Inspection |
| --- | --- | --- |
| X | Current/recent and influential posts; creator/player aliases; patch reactions; disagreements. Use site:x.com and site:twitter.com indexing plus GetXAPI when available. | Inspect direct post, author, date, thread, reply context and any upstream source. Indexing is incomplete. |
| Reddit | Relevant subreddits; New plus Top for the appropriate week/month; exact card/archetype names, experiences, mistakes and disputes. | Open post and useful comment branches; preserve rank/expertise when stated, deleted context and listing truncation. Votes do not measure prevalence. |
| YouTube | Topic search and searches within identified creator channels; guides, gameplay/VODs, mistakes and independent analyses. | Check upload date/patch, inspect video/transcript and quote only supported sections with timestamps. A title/description does not prove video content. |
| Web | Official announcements/hotfixes, developer forums, data providers, specialist guides/wikis, tournament reports, interviews and regional forums. | Inspect original pages and methods; distinguish documentation, statistics, observation and interpretation. |

Use the optional adapters in [source-providers.md](source-providers.md). Existing read-only commands include reddit-posts/reddit-search/reddit-comments, x-search, youtube-search/youtube-channel-search/youtube-transcript and tinyfish-search/tinyfish-fetch. Public indexed search is the reserve route when a credential or provider is missing. Do not buy access or require the user to configure keys just to start.

First collect query-plan.jsonl with `scripts/plan_queries.py`; log actual queries in queries.jsonl with executed_at/status/result_source_ids only after executing them. Log inspected sources with source_id, direct URL, date, version and access_integrity. A planned query and a search snippet are never counted as source inspection.

Run `python scripts/platform_coverage.py RUN_DIRECTORY --language en --language ru --section SEC-0001 --section SEC-0002`, using the actual section IDs. The default command without flags infers all non-excluded sections from plan.json and languages from query-plan.jsonl, including unexecuted branches. Flags override inferred scopes; omit sections only for a sectionless task. Sources count only when linked through result_source_ids or found_by_query_ids to a successful executed query on the same platform; unlinked inspection, snippets and duplicate URLs do not fill coverage gaps. It reports executed searches, failed attempts and inspected sources separately. `--require x --require reddit --strict` can enforce platforms the user explicitly requires. It is an access coverage check, not a consensus or quality score. Missing/blocked lanes remain partial and must be disclosed beside affected conclusions. Do not fabricate successful coverage to pass it.

After an initial pass, search each section's gaps and strongest counterargument. Follow useful references upstream and remove duplicate/reposted lineage. Stop a branch when additional good sources no longer change its claims, examples or confidence. Keep useful details, timings, deck codes, exceptions and disagreements in the normal useful-data bank, even if they do not fit the main article. Apply the existing semantic, freshness, lineage and final research gates before synthesis.

The access audit counts one YouTube video, X post or Reddit thread once across
recognized share URLs, timestamp links and platform aliases. Other URL forms
keep their full query string. `duplicate_source_ids` lists additional inspected
records of the same original; they remain linked inspections, not unlinked gaps.
This deduplication does not prove independent authorship or corroboration.
`no_results` means an executed search found no sources: either forward or reverse
source links make that ledger record invalid. Correct its status or linkage from
the actual tool result before using the report; never change the log to force a pass.
