# Freshness Policy

## Principle

Freshness is compatibility with the researched state, not merely source age. An old source can remain authoritative for unchanged mechanics; a new article can already be stale after a hotfix.

## Establish current context

Before relying on changing information, record:

- current date and timezone when relevant;
- current product/game/software version;
- patch, season, expansion, balance update, hotfix, or release channel;
- the effective date of the change;
- region, platform, mode, or jurisdiction.

Use ChatGPT Search/Web to locate the primary change history or current official state.

## Compare versions

For each material source record both `CURRENT VERSION` and `SOURCE VERSION`, then assign:

- `CURRENT`: explicitly covers current state;
- `LIKELY_CURRENT`: recent and no incompatible change found, but exact version is not explicit;
- `VERSION-COMPATIBLE`: older, yet the relevant mechanism/data definition is demonstrably unchanged;
- `PARTIALLY_STALE`: some claims remain usable and others were affected;
- `STALE`: a relevant change invalidates its use for the current claim;
- `HISTORICAL`: used only to explain prior state or evolution.

Explain why an older source remains applicable. Do not label it compatible merely because no contradiction was noticed.

## Temporal validation

For a current meta or live product, prioritize:

1. current patch/version and current season/window;
2. current version with older but compatible mechanics;
3. previous patch/version for transition context;
4. older sources for history or hypotheses only.

When a balance patch, release, policy change, or dataset revision appears, identify every dependent claim it may invalidate. Re-run targeted queries for affected branches.

## Baseline plus patch overlays

Treat a launch explainer or reference table as a baseline, not a timeless snapshot. Build the current state by applying every relevant later hotfix and patch in chronological order. A newer explicit delta overrides the older value only for the affected field; unaffected fields may remain version-compatible after checking. Then inspect the latest available patch even when it contains no relevant delta, because that negative freshness check bounds the current snapshot.

For row-based systems, record provenance per row or field when patches change only part of the table. Never cite the old baseline alone for a value that was later changed.

## Dates that must remain distinct

- publication or upload date;
- effective/event date;
- data collection window;
- last update date;
- access date.

A page's “updated” date does not prove every embedded fact or dataset was refreshed.

## Freshness gate

A current claim fails if the source version is unknown and a material change is plausible, the data window predates a relevant change, or current official context was never checked. Resolve with a current source, prove version compatibility, narrow to a historical claim, or disclose uncertainty.
