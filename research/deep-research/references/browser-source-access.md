# Optional browser access and owner-source audit

The adapter adopts bounded context reuse and public-network reconnaissance from
ParsesUnix: [pool](https://github.com/Manacost-Labs/ParsesUnix/blob/main/src/web_scraper/fetchers/browser_pool.py),
[worker/thread boundary](https://github.com/Manacost-Labs/ParsesUnix/blob/main/src/web_scraper/fetchers/browser_worker.py),
[render transport](https://github.com/Manacost-Labs/ParsesUnix/blob/main/src/web_scraper/fetchers/transports.py)
and [discovery screening](https://github.com/Manacost-Labs/ParsesUnix/blob/main/src/web_scraper/discovery/collector.py).
Runtime API references: [Playwright contexts](https://playwright.dev/python/docs/api/class-browsercontext)
and [Page](https://playwright.dev/python/docs/api/class-page).

## Runtime and commands

Core collection remains stdlib-only. Optional dependencies are pinned in
`references/examples/source-browser-requirements.txt`; install them in a local
environment, never in a portable archive. Package presence is not proof that a
browser binary can launch. Tested Windows runtime:

```text
uv pip install --python research/library/.venv/Scripts/python.exe -r research/deep-research/references/examples/source-browser-requirements.txt
research/library/.venv/Scripts/python.exe research/deep-research/scripts/source_access.py collect --url "https://bbs.nga.cn/thread.php?fid=422" --browser --browser-engine patchright --browser-channel chrome --output RUN/nga.json
```

Use installed Chrome via `--browser-channel chrome`, or install Chromium for
the chosen engine. Playwright and Patchright are optional alternatives; a
missing package/binary returns `BROWSER_UNAVAILABLE`. CLI closes the pool;
Python callers use `with BrowserPool(...) as pool` or explicitly `close()`.

## Route behavior

Scrape.do remains the web primary, followed by direct public HTTP. `--browser`
adds a local browser after a blocked/CSR native route, before a justified paid
render reserve. Mere browser availability never makes a parse failure, 404,
origin outage or genuine permission denial a reason to escalate.

`--browser-only` is an explicit visitor-view diagnosis with a separate identity
and no Scrape.do call. It still honors origin rate limits and its own route
pauses. Browser engine/channel have distinct histories, so a failed engine
does not silence another one. A paused failed browser does not erase an
otherwise justified paid reserve; provider pauses still apply to that reserve.

NGA exposes a real public continuation link `如不能自动跳转 可点此链接`. On the
known NGA hosts the matching visitor-bootstrap page is `CSR_REQUIRED`. The
adapter clicks the visible control once and lets the site's own page establish
anonymous visitor state. It does not inject guest cookies or open a login form.
The final rendered response still must pass the content contract.

```text
python scripts/source_access.py collect --url "https://search.bilibili.com/all?keyword=%E7%82%89%E7%9F%B3%E4%BC%A0%E8%AF%B4" --browser-only --browser-engine patchright --browser-channel chrome --output RUN/bilibili.json
python scripts/source_access.py collect --url https://www.hsguru.com/meta --browser --browser-channel chrome --output RUN/hsguru-web.json
```

## Isolation and evidence boundaries

One browser is reused, with separate nonpersistent contexts per host. Defaults
are four contexts, twenty pages per context and fifteen-minute context lifetime.
Old contexts are evicted/recycled. This is a serial synchronous owner-thread
implementation: crossing threads fails explicitly. It does not claim to
implement ParsesUnix's concurrent queue worker.

Public HTTPS is checked for navigation, redirects and subrequests. Media
downloads and ordinary writes are blocked. The limited exception is the
browser's own Cloudflare verification POST path; this is not replayed as an API.
Cookies stay inside ephemeral site contexts. Personal profiles, cookie/header
values, raw request bodies and session storage are not exported.

JSON XHR/fetch observations contain bounded metadata only: endpoint without
query values, safe parameter names, status and classification. Failed HTTP,
session-bound and signed requests cannot become working public API routes.
Protection endpoints and SVG/analytics noise are excluded. Even a successful
public-looking observation is only `DISCOVERY_ONLY` and has
`automatically_promoted=false`; no discovered endpoint is automatically replayed.

Rendered HTML passes the normal contract plus a visible-text canary check.
`content_links` contains up to sixty topic/deck/video leads, preferring a real
title over a duplicate counter/thumbnail. They are not inspected evidence.
Video page descriptions/comments do not prove media or caption access. Preserve
member/paywall prompts and exclude those sections from claimed coverage.

## Audit every owner source

```text
research/library/.venv/Scripts/python.exe research/deep-research/scripts/audit_owner_sources.py --browser --browser-engine patchright --browser-channel chrome --output RUN/owner-access
```

Every registered id goes through Collector and receives a receipt. Named
podcasts use verified RSS; YouTube uses TranscriptAPI channel metadata; other
sources use page contracts. Bilibili and note.com also get localized Hearthstone
searches. A readable generic homepage cannot hide a failed topic search.

Artifacts: `owner-source-results.json`, one `<id>-receipt.json` per source,
`owner-source-coverage.json` and its validation. Scope, provider, cache, selected
public URL and failures stay visible. `--refresh` requests revalidation while
honoring pauses. Keep both runs when availability changes: an old success does
not erase a new block. Nonzero exit means at least one source is unavailable;
`unaccounted=0` means accounting completeness, not universal readability.

YouTube success is `channel_discovery_only`; no video/caption inspection is
claimed. RSS success is `rss_catalogue`. The newest podcast GUID is checked
against the durable archive without modifying/transcribing anything. The audit
supplements topical discovery and preserves `evidence_validated=false`.
