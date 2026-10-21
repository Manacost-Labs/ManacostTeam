# Durable source acquisition

Use `scripts/source_access.py collect` for repeatable public reads. `search`
remains the Scrape.do discovery command; low-level `fetch` remains available
for deliberate transport diagnostics. Collection never performs a web search
or turns snippets into evidence.

## Practice adopted from the owner's repositories

Inspected on 21 October 2026:

- [ParsesUnix contracts](https://github.com/Manacost-Labs/ParsesUnix/blob/6c0820d0b2a6c279225a0f3f53e2cdd24a0e5a3e/src/web_scraper/contracts.py),
  [triage](https://github.com/Manacost-Labs/ParsesUnix/blob/6c0820d0b2a6c279225a0f3f53e2cdd24a0e5a3e/src/web_scraper/triage.py)
  and [freshness](https://github.com/Manacost-Labs/ParsesUnix/blob/6c0820d0b2a6c279225a0f3f53e2cdd24a0e5a3e/src/web_scraper/freshness/store.py):
  validate content after every response, distinguish causes before retrying,
  keep durable route outcomes, and account for every input URL.
- [Koloda response contracts](https://github.com/Manacost-Labs/api.kolodahearthstone.com/blob/8d409543bd904f829e85bcae5d4a5187f6ab1fd1/app/parsesunix_contracts.py)
  and [publication gate](https://github.com/Manacost-Labs/api.kolodahearthstone.com/blob/8d409543bd904f829e85bcae5d4a5187f6ab1fd1/app/publish_gate.py):
  transport proof is separate from dataset semantics; a failed candidate must
  not replace valid data; old data and data served after a failed update must
  remain explicitly old.

This is a small independent stdlib implementation, not a bundled copy or a
claim that all capabilities of those frameworks have been integrated.
ParsesUnix's default cheap-first provider order is deliberately not adopted:
the owner explicitly selected Scrape.do first for web/HSGuru and RedditAPI
first for Reddit. Public RSS and the first-party Koloda JSON API use native
HTTP. No browser, account login, scheduler or production parser is installed.

## Contract before network access

For HTML, specify meaningful words that must occur in the readable content.
Canaries in scripts, navigation or login controls do not prove an article.
Known public Hearthstone venues have small default canaries. A canary proves
the requested response shape/topic only, not an author's conclusion.
For JSON, require a nonempty dotted path; list indexes are supported, wildcards
are not. Zero is a valid value. RSS/Atom requires actual titled entries.
Unknown venues require an explicit contract before a provider can be called.

```text
python scripts/source_access.py collect --url https://www.ptt.cc/bbs/Hearthstone/index.html --output RUN/ptt-read.json
python scripts/source_access.py collect --url "https://forum.gamer.com.tw/C.php?bsn=24044&snA=72210" --output RUN/gamer-read.json
python scripts/source_access.py collect --url https://www.reddit.com/r/CompetitiveHS/comments/POST_ID/ --output RUN/reddit-read.json
python scripts/source_access.py collect --url https://hearthstonecommute.libsyn.com/rss --output RUN/episodes-feed.json
python scripts/source_access.py collect --url https://example.com/article --canary "EXACT_TOPIC_WORDS" --output RUN/article-read.json
```

Shell users must quote URLs containing `&`; URLs and topics are public data,
never credential-bearing links. Repeat `--url` for a batch of up to 50 URLs.
The result has one outcome per input occurrence, including duplicates and bad
inputs, with `accounting.unaccounted=0`. A repeated URL may be a cache hit, not
an independent source. Invalid URLs are represented by a hash without echoing
credentials. Query coverage, inspected coverage and independence stay distinct.

The first-party HSGuru cached dataset is an explicit alternative to a blocked
web page, never proof that the requested page/deck was inspected:

```text
python scripts/source_access.py collect --url https://api.kolodahearthstone.com/v1/hsguru/meta --kind json --json-path data.items.0 --expected-patch VERIFIED_PATCH_PERIOD --output RUN/koloda-hsguru.json
```

Replace `VERIFIED_PATCH_PERIOD` with a patch independently verified for the
research task. Preserve the query's format, rank, period and minimum games;
these are in the response `data`. `data.items`, not `data`, is the row list.
An unfiltered collection without `--expected-patch` proves acquisition only.
`meta.stale=false` does not establish a match to the intended patch. Inspect
`source_freshness`, original `data` and metadata before comparing any figures.
`stale`, `cached_after_failure` or `serving_cached_dataset` set to true block
promotion even when the network request just succeeded. A different or missing
expected patch is `PATCH_MISMATCH`.

## Retry, cost and route memory

The normal web route is Scrape.do super, then public direct HTTP if useful.
A single extra Scrape.do render request is allowed only after an actual block
and a failed native alternative; a bare CSR shell alone does not authorize it.
There are at most two Scrape.do calls per URL collection. Reddit uses RedditAPI
comments first; its explicitly named reserve reads and normalizes the public
Reddit JSON tree. Preserve `pagination.listing_status`, placeholders and
warnings: successful access is not proof that all comments were obtained.

- `404/410`: stop; negative URL/contract cache for 24 hours.
- `401/402` or explicit access-control text: stop; no login or access bypass.
- Silent `403` or a short challenge: block; a public alternative may be tried.
- Target `5xx`/network outage: stop; defer the origin for five minutes.
- Target `429`: honor Retry-After across routes on that origin.
- Provider `429`: defer that provider across domains; a native alternative may
  remain available. Numeric/date Retry-After is persisted; no blocking sleeps.
- Parse/contract failure: stop, fix the contract; do not buy another fetch.
- Provider failure: keep it distinct from target failure; a failed proxy job
  cannot establish that the original URL is dead or private.

Blocks defer a route for 30 minutes. When the pause expires, the selected
primary is probed again, so a formerly working fallback does not permanently
replace it. Failed contracts also receive a short negative cache. `--refresh`
bypasses positive TTL, not origin/provider restrictions or negative-cache
pauses. Change an incorrect contract to fix its identity; do not use diagnostic
`fetch` as an automatic retry loop.

## Durable state and source age

Default state is `%LOCALAPPDATA%/Manacost/research/source-state.sqlite3` on
Windows, outside the checkout. `MANACOST_SOURCE_STATE` or `--state PATH` can
select another private local path. Do not place the database in a portable
package or Git. It stores public snapshots, checksums, original observation
times and a body-free attempt ledger with route outcomes. SQL transactions
promote only `OK`; corruption fails without triggering a paid replacement.
Validation-policy version and contract participate in cache identity.

Default positive TTL is six hours, configurable with `--ttl` from 0 to 86400
seconds. HIT retains the original `observed_at` and reports `age_seconds`;
it never updates the source's publication date or the API's `fetched_at`.
For patch-sensitive work, use the verified patch in a JSON contract and choose
an appropriate TTL. A cached read counts as reuse of an inspected source, not
as a new network check or a newly published source.

`--allow-stale` explicitly allows a previous valid snapshot up to seven days
old when refresh fails. It returns `STALE_LKG`, `stale=true`, age and the refresh
failure. It is not `OK`, and the CLI exits nonzero. Never silently combine it
with fresh datasets or promote it as a current-patch source. No snapshot from
another contract/expected patch is reused. Without the flag, failed refreshes
return no fallback content.

```text
python scripts/source_access.py collect --health
python scripts/source_access.py collect --url PUBLIC_URL --refresh --allow-stale --output RUN/source-read.json
```

## Research handoff

Keep the collector receipt in the run and inspect relevant original content.
Record its provider, final public URL, observation time, cache/age, failures and
fallback status in the source notes/coverage log. For Reddit, open several
independent discussions and substantive counterarguments; one normalized tree
is still one discussion. For podcasts, RSS discovery precedes the existing
durable transcript archive; this collector never retranscribes an episode.

All results retain `evidence_validated=false`. The existing snapshot → Source
→ Evidence → Claim chain, exact quotations, freshness checks and semantic
auditor remain required before an editorial handoff. A route health report is
an operational record, not a factual review or a percentage of reliable facts.
