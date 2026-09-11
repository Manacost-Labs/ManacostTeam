# Source Policy

## Claim-dependent authority

There is no universally best source. Rank a source for the specific claim it is being used to support.

### Mechanics, rules, and first-party facts

1. official documentation, database, or rules text;
2. developer or responsible institution statement;
3. official patch notes, release notes, or changelog;
4. reliable datamining or primary artifact inspection;
5. reproducible community testing;
6. secondary explanation.

### Statistics

1. raw dataset with definitions and method;
2. trusted statistical service with usable methodology;
3. large-sample analysis with transparent filters;
4. expert observation;
5. community anecdote.

### Strategy and recommendations

1. current, relevant statistics;
2. demonstrated expert or elite practitioner analysis;
3. multiple independent experts;
4. cross-platform community pattern;
5. individual anecdote.

The strongest practical case often combines statistics with expert interpretation. Statistics without context can mislead, and expertise without evidence can be idiosyncratic.

### Community prevalence or sentiment

1. representative measurement with disclosed sampling;
2. systematic cross-platform collection;
3. repeated independent discussions with bounded language;
4. individual thread or post.

Do not infer population prevalence from engagement or a convenience sample.

## Source assessment

Score 0–5 for triage, not as a mechanical truth formula:

- `authority_score`: competence and proximity for this claim type;
- `relevance_score`: directness and scope match;
- `freshness_score`: current-version compatibility;
- `transparency_score`: evidence, method, and conflicts disclosed;
- `access_integrity`: full source inspected versus partial/archived/quoted elsewhere.

Always preserve the reasons behind important scores. A high total cannot rescue a semantic mismatch.

## Evidence types

- `fact`: directly checkable statement;
- `statistic`: quantitative result tied to a metric and sample;
- `observation`: reported or witnessed behavior without population inference;
- `opinion`: attributed judgment or recommendation;
- `speculation`: unverified explanation or prediction.

Do not silently promote observation to statistic, opinion to fact, or speculation to explanation.

## Independence and lineage

Two pages are not independent when:

- one rewrites, embeds, or quotes the other;
- both rely on the same dataset, press release, leak, datamine, thread, or expert;
- several outlets syndicate one article;
- many posts react to one unverified claim;
- separate charts are slices of the same underlying sample.

Record the upstream source or dataset as `lineage_id`. Count corroboration by independent origin, not URL count. Shared data can still provide useful independent interpretation, but it is not independent measurement.

## Discovery-only material

Treat search snippets, AI answers, unattributed summaries, aggregators, reposts, screenshots without provenance, and citation lists as leads. Open and cite the original whenever possible.

If the original cannot be inspected:

1. do not invent its content;
2. search for an official mirror or archive;
3. look for independent evidence of the same claim;
4. mark the indirect chain;
5. reduce confidence or exclude the claim.

## Selection discipline

Include sources because they reduce uncertainty, cover a required branch, establish provenance, or seriously challenge the leading view. Do not cherry-pick only convenient evidence. Record material exclusions such as incompatible version, wrong population, opaque method, or inaccessible content.

## Citation discipline

Attach citations near consequential claims. Use direct original URLs, not search result pages. Cite only sources actually opened and inspected. A source list without claim linkage does not prove support.
