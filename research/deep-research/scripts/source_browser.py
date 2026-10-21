#!/usr/bin/env python3
"""Optional bounded browser route inspired by ParsesUnix's browser pool.

One browser, isolated nonpersistent contexts, one owning thread. Network
observations are discovery metadata only; credentials and response bodies are
never recorded in the candidate ledger.
"""

from __future__ import annotations

import importlib
import os
import re
import threading
import time
from collections import OrderedDict
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

import source_access as access

SENSITIVE = re.compile(
    r"token|secret|password|signature|w_rid|sessdata|bili_jct|csrf|access_key|authorization",
    re.IGNORECASE,
)
NOISE = re.compile(
    r"/cdn-cgi/|/bfs/|/log(?:/|$)|analytics|recaptcha|/relations$|/nav$|/suggest$",
    re.IGNORECASE,
)
AUTH_HEADERS = {"authorization", "cookie", "x-api-key", "x-csrf-token"}


def candidate(
    url: str, method: str, status: int, content_type: str, header_names
) -> dict | None:
    """Only metadata; a one-page observation never becomes a working API route."""
    if "json" not in content_type.lower() or NOISE.search(urlsplit(url).path):
        return None
    try:
        access.public_url(url)
    except access.AccessError:
        return None
    parts = urlsplit(url)
    keys = [k for k, _ in parse_qsl(parts.query)]
    has_auth = any(str(k).lower() in AUTH_HEADERS for k in header_names)
    signed = any(SENSITIVE.search(k) for k in keys)
    return {
        "endpoint": urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")),
        "query_keys": [k for k in keys if not SENSITIVE.search(k)],
        "method": method,
        "status": status,
        "classification": "FAILED_HTTP_NOT_REPLAYED"
        if not 200 <= status < 300
        else "SESSION_OR_AUTH_NOT_REPLAYED"
        if has_auth or signed
        else "DISCOVERY_ONLY",
        "automatically_promoted": False,
    }


def content_links(anchors: list[dict], origin: str) -> list[dict]:
    result, seen = [], {}
    for item in anchors:
        url = urljoin(origin, item.get("href") or "")
        try:
            access.public_url(url)
        except access.AccessError:
            continue
        if any(SENSITIVE.search(k) for k, _ in parse_qsl(urlsplit(url).query)):
            continue
        if not re.search(r"/video/BV|/read\.php\?|/archetype/|/deck/", url):
            continue
        title = str(item.get("text") or "")[:250]
        if url in seen:
            previous = seen[url]
            if sum(c.isalpha() for c in title) > sum(
                c.isalpha() for c in previous["title"]
            ):
                previous["title"] = title
            continue
        row = {
            "url": url,
            "title": title,
            "evidence_status": "discovery_only",
        }
        seen[url] = row
        result.append(row)
    return result[:60]


class BrowserPool:
    def __init__(
        self,
        *,
        engine: str = "playwright",
        channel: str | None = None,
        max_contexts: int = 4,
        max_pages: int = 20,
        context_ttl: float = 900,
        wait_ms: int = 5000,
        factory=None,
        validator=None,
        now=time.monotonic,
    ):
        if (
            engine not in {"playwright", "patchright"}
            or not 1 <= max_contexts <= 8
            or max_pages < 1
            or context_ttl <= 0
            or not 0 <= wait_ms <= 15000
        ):
            raise ValueError("INVALID_BROWSER_OPTIONS")
        self.engine = engine
        self.channel = (
            channel
            or os.environ.get("MANACOST_BROWSER_CHANNEL")
            or ("chrome" if os.name == "nt" else None)
        )
        self.max_contexts, self.max_pages, self.context_ttl = (
            max_contexts,
            max_pages,
            context_ttl,
        )
        self.wait_ms, self.factory, self.validator, self.now = (
            wait_ms,
            factory,
            validator,
            now,
        )
        self.owner = threading.get_ident()
        self.playwright = self.browser = None
        self.contexts = OrderedDict()
        self.metrics = {
            "browser_launches": 0,
            "contexts_created": 0,
            "contexts_reused": 0,
            "contexts_closed": 0,
            "pages_closed": 0,
            "cleanup_failures": 0,
        }

    def _check_thread(self):
        if threading.get_ident() != self.owner:
            raise access.AccessError("BROWSER_THREAD_MISMATCH")

    def _public(self, url: str):
        if self.validator:
            return self.validator(url)
        from source_collector import public_address

        return public_address(url)

    def _start(self):
        if self.browser is not None:
            return
        try:
            factory = (
                self.factory
                or importlib.import_module(self.engine + ".sync_api").sync_playwright
            )
            self.playwright = factory().start()
            self.browser = self.playwright.chromium.launch(
                headless=True, **({"channel": self.channel} if self.channel else {})
            )
            self.metrics["browser_launches"] += 1
        except Exception:  # noqa: BLE001 -- optional runtime boundary, no exception text leaks
            self.close()
            raise access.AccessError("BROWSER_UNAVAILABLE") from None

    def _guard(self, route):
        request = route.request
        try:
            self._public(request.url)
            parts = urlsplit(request.url)
            public_verification = request.method == "POST" and parts.path.startswith(
                "/cdn-cgi/challenge-platform/"
            )
            if request.method not in {"GET", "HEAD"} or request.resource_type in {
                "media",
                "font",
                "image",
            }:
                if public_verification:
                    route.continue_()
                else:
                    route.abort()
            else:
                route.continue_()
        except (access.AccessError, ValueError, OSError):
            route.abort()

    def _close_context(self, context):
        try:
            context.close()
        except Exception:  # noqa: BLE001 -- cleanup is best effort, counted separately
            self.metrics["cleanup_failures"] += 1
        self.metrics["contexts_closed"] += 1

    def _context(self, url: str):
        domain = urlsplit(url).hostname
        previous = self.contexts.pop(domain, None)
        if previous and (
            previous[1] >= self.max_pages
            or self.now() - previous[2] >= self.context_ttl
        ):
            self._close_context(previous[0])
            previous = None
        if previous:
            entry = (previous[0], previous[1] + 1, previous[2])
            self.metrics["contexts_reused"] += 1
        else:
            while len(self.contexts) >= self.max_contexts:
                self._close_context(self.contexts.popitem(last=False)[1][0])
            context = self.browser.new_context(
                accept_downloads=False,
                service_workers="block",
                locale="zh-CN"
                if domain and any(s in domain for s in ("nga.", "bilibili."))
                else "en-US",
            )
            context.route("**/*", self._guard)
            entry = (context, 1, self.now())
            self.metrics["contexts_created"] += 1
        self.contexts[domain] = entry
        return entry[0]

    def fetch(self, url: str) -> dict:
        self._check_thread()
        self._public(url)
        self._start()
        page = self._context(url).new_page()
        ledger, navigation = [], {"status": 0}
        continued = False

        def response_seen(response):
            try:
                request = response.request
                if (
                    request.resource_type == "document"
                    and request.frame == page.main_frame
                ):
                    navigation["status"] = response.status
                if request.resource_type not in {"xhr", "fetch"} or len(ledger) >= 30:
                    return
                observed = candidate(
                    response.url,
                    request.method,
                    response.status,
                    response.headers.get("content-type", ""),
                    request.all_headers().keys(),
                )
                if observed is not None:
                    ledger.append(observed)
            except Exception:  # noqa: BLE001 -- reconnaissance cannot fail acquisition
                return

        page.on("response", response_seen)
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if response is not None:
                navigation["status"] = response.status
            page.wait_for_timeout(self.wait_ms)
            # NGA explicitly exposes a public visitor-continue link. Use that
            # real UI once; do not inject guest cookies or enter a login flow.
            if (urlsplit(url).hostname or "") in {
                "bbs.nga.cn",
                "ngabbs.com",
                "nga.178.com",
            }:
                guest = page.get_by_text("如不能自动跳转 可点此链接", exact=True)
                if guest.count():
                    guest.click(timeout=3000)
                    page.wait_for_timeout(self.wait_ms)
                    continued = True
            self._public(page.url)
            markup = page.content()
            if len(markup.encode("utf-8")) > access.MAX_BYTES:
                raise access.AccessError("RESPONSE_TOO_LARGE")
            visible = page.locator("body").inner_text(timeout=5000)
            anchors = page.locator("a[href]").evaluate_all(
                "nodes => nodes.slice(0, 600).map(a => ({href:a.href, text:a.innerText}))"
            )
            return {
                "status": navigation["status"],
                "body": markup,
                "rendered_text": visible,
                "final_url": page.url,
                "content_links": content_links(anchors, page.url),
                "diagnostics": {
                    "browser_engine": self.engine,
                    "network_candidates": ledger,
                    "public_guest_continue": continued,
                    "pool": dict(self.metrics),
                },
            }
        except access.AccessError:
            raise
        except Exception:  # noqa: BLE001 -- safe optional browser transport boundary
            raise access.AccessError("BROWSER_NAVIGATION_FAILED") from None
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001 -- cleanup must not mask acquisition failure
                self.metrics["cleanup_failures"] += 1
            finally:
                self.metrics["pages_closed"] += 1

    def close(self):
        self._check_thread()
        for context, _, _ in self.contexts.values():
            self._close_context(context)
        self.contexts.clear()
        for obj, method in ((self.browser, "close"), (self.playwright, "stop")):
            if obj is not None:
                try:
                    getattr(obj, method)()
                except Exception:  # noqa: BLE001 -- cleanup must not mask original failure
                    self.metrics["cleanup_failures"] += 1
        self.browser = self.playwright = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
