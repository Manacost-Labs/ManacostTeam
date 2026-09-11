# Evidence Protocol

## Units

Keep three distinct units:

- a **source** is a document, dataset, page, post, thread, or media item;
- an **evidence item** is the exact passage, table, result, or observation relevant to a claim;
- a **claim** is one independently falsifiable assertion.

One source can yield several evidence items. One evidence item may bear on several claims, but the support relationship must be explicit.

## Collection procedure

For every material evidence item:

1. assign `evidence_id` and `source_id`;
2. record a page, section, table, paragraph, post, or media timestamp;
3. preserve a short exact excerpt when allowed, otherwise a faithful paraphrase;
4. record whether it supports, challenges, contextualizes, or only mentions the claim;
5. capture date, data window, version, population, metric, and method when applicable;
6. note limitations and alternative readings;
7. link it to atomic claim IDs.

“Mentions the topic” is not evidence that a claim is true.

## Atomic claim extraction

Split compound prose. For example:

`X is the best strategy because it has the highest win rate and experts prefer it.`

Becomes:

- X has the highest win rate in population P, period T, and version V.
- Expert group E recommends X under conditions C.
- The win-rate metric is suitable for judging “best” under the user's criterion.
- Therefore X is the best strategy under those conditions.

The final inference cannot inherit high confidence from only one subclaim.

## Claim classes and burdens

- `official_fact`: one decisive current primary source may be sufficient.
- `statistical`: requires metric definition, denominator, sample, window, filters, version, and bias review.
- `strategy`: normally requires at least two independent confirmations; prefer statistics plus expert reasoning.
- `causal`: requires a design or evidence capable of distinguishing causation from association.
- `prevalence`: requires a sampling basis; anecdotes show existence, not frequency.
- `superlative`: requires comparison against the relevant alternatives and a defined metric.
- `forecast`: requires assumptions, horizon, and uncertainty.

## Evidence matrix

Before synthesis, map each consequential claim across:

`Primary | Statistics | Expert | Community | Counter Evidence | Confidence`

Not every column must be populated for every claim. Empty expected columns are gaps; irrelevant columns are `N/A` with a reason. The matrix prevents a large general bibliography from concealing unsupported conclusions.

## Numerical evidence

For a statistic, preserve:

- exact metric and unit;
- numerator and denominator when available;
- sample size and time window;
- geography, rank/MMR, platform, mode, or population;
- patch/version and filters;
- uncertainty interval or variance when reported;
- missing data and selection/survivorship bias;
- distinction between raw value, model estimate, and author's interpretation.

Recalculate simple derived values when feasible. Do not combine incompatible denominators, windows, populations, or versions.

## Quotes and paraphrases

Use exact quotes sparingly and preserve meaning and context. A paraphrase must not strengthen modality: “may” cannot become “does,” and “in this sample” cannot become universal. Separate the source's statement from the researcher's inference.

## Evidence retention

In normal output, include only decision-relevant evidence. In `raw-research`, retain useful rejected hypotheses, counterevidence, edge cases, version notes, and writer notes so a downstream Writer Skill can work without repeating discovery.
