#!/usr/bin/env python3
"""Validated, durable public-source acquisition; never a factual evidence gate.

Small stdlib implementation informed by ParsesUnix contracts/triage/freshness
and Koloda's separation of transport, publication and explicitly stale fallback.
The owner's Scrape.do / RedditAPI routing preference takes priority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import socket
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from contextlib import closing
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import source_access as access

POLICY_VERSION = "source-collector/2"
BLOCK_TEXT = (
    "just a moment",
    "verify you are human",
    "checking your browser",
    "sorry, you have been blocked",
    "enable javascript and cookies to continue",
    "访问被拒绝",
    "请求被拦截",
    "請完成下列動作以繼續瀏覽",
)
CANARIES = {
    "ptt.cc": "看板",
    "gamer.com.tw": "爐石",
    "iyingdi.com": "炉石",
    "hs.blizzard.cn": "炉石",
    "nga.cn": "炉石",
    "ngabbs.com": "炉石",
    "hsguru.com": "HSGuru",
    "hearthstone-decks.com": "Hearthstone",
    "hearthstone.judgehype.com": "Hearthstone",
    "beerbrick.com": "Hearthstone",
    "outof.games": "Hearthstone",
    "hearthpwn.com": "Hearthstone",
    "note.com": "ハースストーン",
    "coinconcede.com": "Coin Concede",
    "borntobewildhs.com": "Born",
    "hs.inven.co.kr": "하스스톤",
    "bilibili.com": "炉石",
}


@dataclass(frozen=True)
class Contract:
    kind: str = "html"
    canaries: tuple[str, ...] = ()
    json_paths: tuple[str, ...] = ()
    min_chars: int = 180
    expected_patch: str | None = None

    def __post_init__(self):
        if self.expected_patch and self.kind != "json":
            raise ValueError("PATCH_REQUIRES_JSON_METADATA")
        if (
            self.kind not in {"html", "json", "rss"}
            or not 0 <= self.min_chars <= 1_000_000
        ):
            raise ValueError("INVALID_CONTRACT")
        if self.kind == "html" and not self.canaries:
            raise ValueError("HTML_CANARY_REQUIRED")
        if self.kind == "json" and not self.json_paths:
            raise ValueError("JSON_PATH_REQUIRED")
        if any(
            not x or not isinstance(x, str) for x in (*self.canaries, *self.json_paths)
        ):
            raise ValueError("INVALID_CONTRACT_PROOF")

    @property
    def key(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True).encode()
        ).hexdigest()


def default_contract(url: str) -> Contract:
    host, path = urlsplit(url).hostname or "", urlsplit(url).path
    if path.rstrip("/").endswith(("/rss", ".xml", "/feed")):
        return Contract("rss", min_chars=0)
    if reddit_id(url):
        return Contract("json", json_paths=("results.0.text",), min_chars=0)
    if youtube_channel_id(url):
        return Contract("json", json_paths=("videos.0.id", "title"), min_chars=0)
    for domain, canary in CANARIES.items():
        if host == domain or host.endswith("." + domain):
            return Contract(canaries=(canary,))
    raise ValueError("EXPLICIT_RESPONSE_CONTRACT_REQUIRED")


def json_value(payload: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(payload, dict):
            payload = payload.get(part)
        elif isinstance(payload, list) and part.isdigit() and int(part) < len(payload):
            payload = payload[int(part)]
        else:
            return None
    return payload


def validate(raw: dict[str, Any], contract: Contract) -> dict[str, Any]:
    """Validate actual body; successful transport alone cannot promote it."""
    from chinese_hearthstone import clean_html

    status, body = raw["status"], raw.get("body", "")
    result = {"verdict": "PARSE_FAIL", "text": "", "title": None}
    if status in {404, 410}:
        return {**result, "verdict": "DEAD_URL"}
    if status == 429:
        return {**result, "verdict": "RATE_LIMITED"}
    if status in {401, 402}:
        return {**result, "verdict": "AUTH_REQUIRED"}
    if status >= 500:
        return {**result, "verdict": "ORIGIN_DOWN"}
    # Scripts may mention captcha/security on healthy pages. Inspect visible text.
    title, visible = clean_html(body) if contract.kind == "html" else (None, body)
    sample = (str(title or "") + " " + visible).casefold()
    if any(x in sample for x in BLOCK_TEXT) and len(visible) < 1500:
        return {**result, "verdict": "BLOCKED" if status == 403 else "SOFT_BLOCK"}
    if status == 403:
        host = urlsplit(raw.get("final_url", "")).hostname or ""
        if (
            host in {"bbs.nga.cn", "ngabbs.com", "nga.178.com"}
            and "访客不能直接访问" in str(title)
            and "guestJs" in body
            and "如不能自动跳转" in body
        ):
            return {**result, "verdict": "CSR_REQUIRED"}
        denied = any(
            x in sample
            for x in (
                "access denied",
                "permission denied",
                "login required",
                "sign in to continue",
                "查看所需的权限",
                "请先登录",
                "請先登入",
            )
        )
        return {**result, "verdict": "ACCESS_DENIED" if denied else "BLOCKED"}
    if status != 200:
        return result
    if (
        any(
            x in sample for x in ("sign in to continue", "login required", "登录后查看")
        )
        and len(visible) < 1500
    ):
        return {**result, "verdict": "AUTH_REQUIRED"}
    if contract.kind == "html":
        if not re.search(r"<[a-z][^>]*>", body, re.IGNORECASE):
            return result
        if body.lstrip().startswith(("{", "[")):
            return result
        if len(visible) < 400 and re.search(
            r"id=['\"](?:app|root|__next)['\"]", body, re.IGNORECASE
        ):
            return {**result, "verdict": "CSR_REQUIRED"}
        if len(visible) < contract.min_chars:
            return {**result, "verdict": "THIN_CONTENT"}
        if not all(x.casefold() in visible.casefold() for x in contract.canaries):
            return result
        rendered = raw.get("rendered_text")
        if rendered is not None and not all(
            x.casefold() in rendered.casefold() for x in contract.canaries
        ):
            return result
        result.update(text=visible, title=title)
    elif contract.kind == "json":
        try:
            payload = json.loads(body)
        except ValueError:
            return result
        if any(
            json_value(payload, p) in (None, "", [], {}) for p in contract.json_paths
        ):
            return result
        if len(body) < contract.min_chars:
            return {**result, "verdict": "THIN_CONTENT"}
        result.update(text=json.dumps(payload, ensure_ascii=False), data=payload)
        meta = payload.get("meta", {}) if isinstance(payload, dict) else {}
        if not isinstance(meta, dict):
            return result
        result["source_freshness"] = {
            k: meta.get(k)
            for k in (
                "fetched_at",
                "stale",
                "current_period",
                "current_patch_period",
                "cached_after_failure",
                "serving_cached_dataset",
            )
            if k in meta
        }
        if any(
            meta.get(k) is True
            for k in ("stale", "cached_after_failure", "serving_cached_dataset")
        ):
            return {**result, "verdict": "STALE_SOURCE"}
        if contract.expected_patch:
            patch = meta.get("current_patch_period") or meta.get("patch")
            if patch != contract.expected_patch:
                return {**result, "verdict": "PATCH_MISMATCH"}
    else:
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return result
        if root.tag not in {"rss", "{http://www.w3.org/2005/Atom}feed"}:
            return result
        entries = root.findall("./channel/item") or root.findall(
            "{http://www.w3.org/2005/Atom}entry"
        )
        usable = [
            e
            for e in entries
            if any(
                (c.text or "").strip() for c in e if c.tag.rsplit("}", 1)[-1] == "title"
            )
        ]
        if not usable:
            return result
        result.update(text=body, entry_count=len(usable))
    result["verdict"] = "OK"
    return result


def retry_delay(value: str | None, now: float) -> float:
    try:
        delay = float(value or "")
        return max(0.0, delay) if math.isfinite(delay) else 300.0
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value or "").timestamp() - now)
        except (ValueError, TypeError, OverflowError):
            return 300.0


def public_address(url: str) -> str:
    import ipaddress

    access.public_url(url)
    try:
        addresses = socket.getaddrinfo(
            urlsplit(url).hostname, urlsplit(url).port or 443, type=socket.SOCK_STREAM
        )
    except OSError:
        raise access.AccessError("DNS_UNAVAILABLE") from None
    if not addresses or any(
        not ipaddress.ip_address(a[4][0]).is_global for a in addresses
    ):
        raise access.AccessError("PUBLIC_HTTPS_URL_REQUIRED")
    return url


class PublicRedirect(HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_address(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def direct(url: str) -> dict[str, Any]:
    public_address(url)
    request = Request(
        url,
        headers={"User-Agent": "ManacostResearch/1.1", "Accept-Encoding": "identity"},
    )
    try:
        response = build_opener(PublicRedirect()).open(request, timeout=20)
    except HTTPError as exc:
        response = exc
    except (OSError, URLError, TimeoutError):
        raise access.AccessError("DIRECT_NETWORK_ERROR") from None
    with response:
        public_address(response.geturl())
        body = response.read(access.MAX_BYTES + 1)
        if len(body) > access.MAX_BYTES:
            raise access.AccessError("RESPONSE_TOO_LARGE")
        content_type = response.headers.get("Content-Type", "")
        encoding = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
        try:
            text = body.decode(encoding[1] if encoding else "utf-8", errors="replace")
        except LookupError:
            text = body.decode("utf-8", errors="replace")
        return {
            "status": response.code,
            "body": text,
            "final_url": response.geturl(),
            "retry_after": response.headers.get("Retry-After"),
        }


def scrape(url: str, render: bool = False) -> dict[str, Any]:
    # Same explicit provider preference as source_access.fetch; protected hosts
    # use super proxies. The render retry is separate and bounded by the caller.
    data, meta = access.request(
        "/",
        {
            "url": url,
            "super": "true",
            "disableRetry": "true",
            "transparentResponse": "true",
            **({"render": "true", "customWait": "5000"} if render else {}),
        },
    )
    encoding = re.search(r"charset=([\w-]+)", meta["content_type"], re.IGNORECASE)
    try:
        body = data.decode(encoding[1] if encoding else "utf-8", errors="replace")
    except LookupError:
        body = data.decode("utf-8", errors="replace")
    return {
        "status": int(meta["target_status"] or meta["provider_status"]),
        "body": body,
        "final_url": url,
        "retry_after": meta.get("retry_after"),
        "diagnostics": meta,
    }


def reddit_id(url: str) -> str | None:
    host = urlsplit(url).hostname or ""
    match = re.search(r"/comments/([a-zA-Z0-9]{1,16})(?:/|$)", urlsplit(url).path)
    return (
        match[1]
        if match and (host == "reddit.com" or host.endswith(".reddit.com"))
        else None
    )


def reddit(url: str) -> dict[str, Any]:
    import community_sources as community

    args = community.build_parser().parse_args(
        ["reddit-comments", "--post-id", reddit_id(url)]
    )
    payload = community.execute(args)
    return {
        "status": 200,
        "body": json.dumps(payload, ensure_ascii=False),
        "final_url": url,
    }


def youtube_channel_id(url: str) -> str | None:
    parts = urlsplit(url)
    if (parts.hostname or "").removeprefix("www.") != "youtube.com":
        return None
    match = re.fullmatch(r"/(@[A-Za-z0-9_.-]{1,100})(?:/videos)?/?", parts.path)
    return match[1] if match else None


def youtube_channel(url: str) -> dict[str, Any]:
    from community_sources import transcriptapi_get_json

    payload = transcriptapi_get_json(
        "/channel/videos",
        {"channel_id": youtube_channel_id(url), "limit": 3},
        max_attempts=1,
    )
    return {
        "status": 200,
        "body": json.dumps(payload, ensure_ascii=False),
        "final_url": url,
    }


def reddit_reserve(
    url: str, *, native: bool = False, render: bool = False
) -> dict[str, Any]:
    """Explicit reserve, preserving the difference from RedditAPI success."""
    from community_sources import normalize_reddit_comments

    target = f"https://www.reddit.com/comments/{reddit_id(url)}.json?raw_json=1"
    raw = direct(target) if native else scrape(target, render=render)
    if raw["status"] != 200:
        return raw
    try:
        listings = json.loads(raw["body"])
        comments = listings[1]["data"]["children"]
        if not isinstance(comments, list):
            return raw
    except (ValueError, TypeError, KeyError, IndexError):
        return raw
    payload = normalize_reddit_comments(
        {"comments": comments, "listing_status": "unknown"}, reddit_id(url)
    )
    return {**raw, "body": json.dumps(payload, ensure_ascii=False)}


def state_path() -> Path:
    return Path(
        os.environ.get(
            "MANACOST_SOURCE_STATE",
            Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache"))
            / "Manacost/research/source-state.sqlite3",
        )
    )


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or state_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots (key TEXT PRIMARY KEY, saved REAL, digest TEXT, payload TEXT);
                CREATE TABLE IF NOT EXISTS routes (key TEXT PRIMARY KEY, successes INTEGER, failures INTEGER, until REAL, verdict TEXT);
                CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, at REAL, url TEXT, route TEXT, verdict TEXT);
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def snapshot(self, key: str) -> tuple[float, dict[str, Any]] | None:
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT saved,digest,payload FROM snapshots WHERE key=?", (key,)
            ).fetchone()
        if not row:
            return None
        if hashlib.sha256(row[2].encode()).hexdigest() != row[1]:
            raise ValueError("SNAPSHOT_CHECKSUM_MISMATCH")
        return row[0], json.loads(row[2])

    def promote(self, key: str, result: dict[str, Any], now: float):
        if result["verdict"] != "OK":
            raise ValueError("ONLY_VALIDATED_SNAPSHOTS_CAN_BE_PROMOTED")
        payload = json.dumps(access.scrub(result), ensure_ascii=False, sort_keys=True)
        with closing(self.connect()) as db, db:
            db.execute(
                "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)",
                (key, now, hashlib.sha256(payload.encode()).hexdigest(), payload),
            )

    def cooldown(self, key: str, now: float) -> float:
        with closing(self.connect()) as db:
            row = db.execute("SELECT until FROM routes WHERE key=?", (key,)).fetchone()
        return max(0.0, row[0] - now) if row else 0.0

    def last_verdict(self, key: str) -> str | None:
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT verdict FROM routes WHERE key=?", (key,)
            ).fetchone()
        return row[0] if row else None

    def defer(self, key: str, until: float, verdict: str):
        with closing(self.connect()) as db, db:
            db.execute(
                """INSERT INTO routes VALUES(?,0,0,?,?) ON CONFLICT(key) DO UPDATE SET
                until=MAX(until,excluded.until), verdict=excluded.verdict""",
                (key, until, verdict),
            )

    def record(
        self, key: str, url: str, route: str, verdict: str, now: float, delay: float
    ):
        with closing(self.connect()) as db, db:
            db.execute(
                "INSERT INTO attempts(at,url,route,verdict) VALUES(?,?,?,?)",
                (now, url, route, verdict),
            )
            db.execute(
                """INSERT INTO routes VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
                successes=successes+excluded.successes, failures=failures+excluded.failures,
                until=excluded.until, verdict=excluded.verdict""",
                (key, int(verdict == "OK"), int(verdict != "OK"), now + delay, verdict),
            )

    def health(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT key,successes,failures,until,verdict FROM routes ORDER BY key"
            ).fetchall()
        return [
            dict(
                zip(
                    (
                        "route",
                        "successes",
                        "failures",
                        "cooldown_until",
                        "last_verdict",
                    ),
                    row,
                )
            )
            for row in rows
        ]


class Collector:
    def __init__(self, store: Store | None = None, *, now=time.time, browser=None):
        self.store, self.now = store or Store(), now
        self.browser = browser

    def collect(
        self,
        url: str,
        contract: Contract | None = None,
        *,
        ttl: float = 21600,
        refresh: bool = False,
        allow_stale: bool = False,
        browser_only: bool = False,
    ) -> dict[str, Any]:
        from community_sources import ProviderError

        access.load_credentials()
        access.public_url(url)
        if not math.isfinite(ttl) or not 0 <= ttl <= 86400:
            raise ValueError("INVALID_CACHE_TTL")
        contract = contract or default_contract(url)
        if browser_only and self.browser is None:
            raise ValueError("BROWSER_ROUTE_REQUIRED")
        browser_identity = (
            str(getattr(self.browser, "engine", "none"))
            + ":"
            + str(getattr(self.browser, "channel", "default"))
        )
        profile = ("browser-only:" if browser_only else "normal:") + browser_identity
        key = hashlib.sha256(
            (POLICY_VERSION + profile + url + contract.key).encode()
        ).hexdigest()
        old = self.store.snapshot(key)
        now = self.now()
        age = max(0.0, now - old[0]) if old else None
        if old and not refresh and age < ttl:
            return {**old[1], "cache": "HIT", "age_seconds": age, "attempts": []}
        deferred = self.store.cooldown("url:" + key, now)
        if deferred:
            failure = {
                "verdict": "COOLDOWN",
                "refresh_verdict": self.store.last_verdict("url:" + key),
                "url": url,
                "cache": "NEGATIVE",
                "retry_after_seconds": deferred,
                "attempts": [],
                "evidence_validated": False,
            }
            return self.fallback(old, failure, allow_stale)
        is_reddit = bool(reddit_id(url))
        is_native = (
            contract.kind == "rss"
            or urlsplit(url).hostname == "api.kolodahearthstone.com"
        )
        if browser_only:
            routes = [("browser", lambda: self.browser.fetch(url))]
        elif youtube_channel_id(url):
            routes = [("transcriptapi-channel", lambda: youtube_channel(url))]
        elif is_reddit:
            routes = [
                ("redditapi", lambda: reddit(url)),
                ("scrape-super", lambda: reddit_reserve(url)),
                ("direct", lambda: reddit_reserve(url, native=True)),
            ]
        elif is_native:
            routes = [("native", lambda: direct(url))]
        else:
            routes = [
                ("scrape-super", lambda: scrape(url)),
                ("direct", lambda: direct(url)),
            ]
        attempts: list[dict[str, Any]] = []
        blocked = False
        final = "UNAVAILABLE"
        for route, acquire in routes:
            route_key = (urlsplit(url).hostname or "") + ":" + route
            if route == "browser":
                route_key += ":" + browser_identity
            provider_key = "provider:" + (
                "scrape.do" if route.startswith("scrape") else route
            )
            cooldown = max(
                self.store.cooldown(route_key, now),
                self.store.cooldown(provider_key, now),
                self.store.cooldown("origin:" + (urlsplit(url).hostname or ""), now),
            )
            if cooldown:
                last = self.store.last_verdict(route_key)
                attempts.append(
                    {
                        "route": route,
                        "verdict": "COOLDOWN",
                        "last_verdict": last,
                        "retry_after_seconds": cooldown,
                    }
                )
                blocked = (
                    blocked
                    or route == "scrape-super"
                    and last in {"BLOCKED", "SOFT_BLOCK"}
                )
                final = "COOLDOWN"
                if (
                    route == "browser"
                    and not browser_only
                    and blocked
                    and last
                    in {"BLOCKED", "SOFT_BLOCK", "BROWSER_ERROR", "BROWSER_UNAVAILABLE"}
                ):
                    routes.append(
                        (
                            "scrape-super-render",
                            lambda: (
                                reddit_reserve(url, render=True)
                                if is_reddit
                                else scrape(url, render=True)
                            ),
                        )
                    )
                continue
            raw: dict[str, Any] = {}
            try:
                raw = acquire()
                checked = validate(raw, contract)
            except (access.AccessError, ProviderError, OSError, HTTPException) as exc:
                status = getattr(exc, "status", None)
                checked = {
                    "verdict": "PROVIDER_RATE_LIMITED"
                    if status == 429
                    else "PROVIDER_ERROR",
                    "error_code": getattr(exc, "code", None)
                    or getattr(exc, "provider_code", None)
                    or "ACCESS_ROUTE_FAILED",
                }
                raw["retry_after"] = getattr(exc, "retry_after", None)
                raw["provider_status"] = status
                if route in {"native", "direct"}:
                    code = getattr(exc, "code", "")
                    checked["verdict"] = (
                        "ORIGIN_DOWN"
                        if code in {"DIRECT_NETWORK_ERROR", "DNS_UNAVAILABLE"}
                        or isinstance(exc, (OSError, HTTPException))
                        else "PARSE_FAIL"
                    )
                if route == "browser":
                    checked["verdict"] = (
                        "BROWSER_UNAVAILABLE"
                        if getattr(exc, "code", "") == "BROWSER_UNAVAILABLE"
                        else "BROWSER_ERROR"
                    )
            now = self.now()
            final = checked["verdict"]
            delay = (
                retry_delay(raw.get("retry_after"), now)
                if final in {"RATE_LIMITED", "PROVIDER_RATE_LIMITED"}
                else {
                    "BLOCKED": 1800,
                    "SOFT_BLOCK": 1800,
                    "PROVIDER_ERROR": 300,
                    "ORIGIN_DOWN": 300,
                }.get(final, 0)
            )
            self.store.record(route_key, access.scrub(url), route, final, now, delay)
            if final == "PROVIDER_RATE_LIMITED":
                self.store.defer(provider_key, now + delay, final)
            if final in {"RATE_LIMITED", "ORIGIN_DOWN"}:
                self.store.defer(
                    "origin:" + (urlsplit(url).hostname or ""), now + delay, final
                )
            attempt = {
                "route": route,
                "verdict": final,
                "http_status": raw.get("status"),
                "provider_http_status": raw.get("provider_status"),
                "error_code": checked.get("error_code"),
                "retry_after_seconds": delay,
                "diagnostics": raw.get("diagnostics", {}),
            }
            if "source_freshness" in checked:
                attempt["source_freshness"] = checked["source_freshness"]
            attempts.append(attempt)
            if final == "OK":
                result = {
                    **checked,
                    "url": url,
                    "final_url": raw.get("final_url", url),
                    "provider": route,
                    "observed_at": now,
                    "contract": asdict(contract),
                    "cache": "MISS",
                    "age_seconds": 0,
                    "attempts": attempts,
                    "content_links": raw.get("content_links", []),
                    "evidence_validated": False,
                }
                self.store.promote(key, result, now)
                return access.scrub(result)
            if final in {
                "DEAD_URL",
                "ORIGIN_DOWN",
                "RATE_LIMITED",
                "AUTH_REQUIRED",
                "ACCESS_DENIED",
                "PARSE_FAIL",
                "PATCH_MISMATCH",
                "STALE_SOURCE",
            }:
                break
            if route == "scrape-super" and final in {"BLOCKED", "SOFT_BLOCK"}:
                blocked = True
            if (
                route == "direct"
                and (blocked or final == "CSR_REQUIRED")
                and final
                in {
                    "BLOCKED",
                    "SOFT_BLOCK",
                    "CSR_REQUIRED",
                    "THIN_CONTENT",
                    "PROVIDER_ERROR",
                }
            ):
                if self.browser is not None:
                    routes.append(("browser", lambda: self.browser.fetch(url)))
                elif blocked:
                    routes.append(
                        (
                            "scrape-super-render",
                            lambda: (
                                reddit_reserve(url, render=True)
                                if is_reddit
                                else scrape(url, render=True)
                            ),
                        )
                    )
            if (
                route == "browser"
                and not browser_only
                and blocked
                and final
                in {
                    "BLOCKED",
                    "SOFT_BLOCK",
                    "CSR_REQUIRED",
                    "BROWSER_UNAVAILABLE",
                    "BROWSER_ERROR",
                }
            ):
                routes.append(("scrape-super-render", lambda: scrape(url, render=True)))
        failure = {
            "verdict": final,
            "url": url,
            "cache": "NONE",
            "attempts": attempts,
            "evidence_validated": False,
        }
        negative_ttl = {
            "DEAD_URL": 86400,
            "ACCESS_DENIED": 3600,
            "AUTH_REQUIRED": 3600,
            "PARSE_FAIL": 600,
            "PATCH_MISMATCH": 300,
            "STALE_SOURCE": 300,
        }.get(final, 0)
        if negative_ttl:
            self.store.defer("url:" + key, self.now() + negative_ttl, final)
        return self.fallback(old, failure, allow_stale)

    def fallback(
        self, old, failure: dict[str, Any], allow_stale: bool
    ) -> dict[str, Any]:
        age = max(0.0, self.now() - old[0]) if old else None
        if old and allow_stale and age <= 7 * 86400:
            return {
                **old[1],
                **failure,
                "verdict": "STALE_LKG",
                "refresh_verdict": failure.get("refresh_verdict", failure["verdict"]),
                "cache": "STALE",
                "age_seconds": age,
                "stale": True,
            }
        return failure

    def batch(self, urls: list[str], **options) -> dict[str, Any]:
        if not 1 <= len(urls) <= 50:
            raise ValueError("BATCH_REQUIRES_1_TO_50_URLS")
        results = []
        for url in urls:
            try:
                results.append(self.collect(url, **options))
            except (ValueError, access.AccessError, sqlite3.Error):
                # Invalid URLs may contain credentials: do not echo them.
                results.append(
                    {
                        "verdict": "INPUT_OR_STATE_ERROR",
                        "url_hash": hashlib.sha256(url.encode()).hexdigest(),
                        "evidence_validated": False,
                    }
                )
            except Exception as exc:  # noqa: BLE001 -- batch boundary must account for each failed adapter
                # Isolate an unexpected adapter failure, account for the URL and
                # keep the class for debugging without exposing exception text.
                results.append(
                    {
                        "verdict": "UNEXPECTED_SOURCE_ERROR",
                        "error_type": type(exc).__name__,
                        "url_hash": hashlib.sha256(url.encode()).hexdigest(),
                        "evidence_validated": False,
                    }
                )
        return {
            "results": results,
            "accounting": {
                "input": len(urls),
                "accounted": len(results),
                "unaccounted": len(urls) - len(results),
            },
        }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", action="append", default=[])
    p.add_argument("--kind", choices=("html", "json", "rss"), default="html")
    p.add_argument("--canary", action="append", default=[])
    p.add_argument("--json-path", action="append", default=[])
    p.add_argument("--expected-patch")
    p.add_argument("--min-chars", type=int, default=180)
    p.add_argument("--ttl", type=float, default=21600)
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--allow-stale", action="store_true")
    p.add_argument("--browser", action="store_true")
    p.add_argument("--browser-only", action="store_true")
    p.add_argument(
        "--browser-engine", choices=("playwright", "patchright"), default="playwright"
    )
    p.add_argument("--browser-channel")
    p.add_argument("--health", action="store_true")
    p.add_argument("--state", type=Path)
    p.add_argument("--output", type=Path)
    args = p.parse_args(argv)
    browser = None
    try:
        if args.browser or args.browser_only:
            from source_browser import BrowserPool

            browser = BrowserPool(
                engine=args.browser_engine, channel=args.browser_channel
            )
        collector = Collector(Store(args.state), browser=browser)
        if args.expected_patch and args.kind != "json":
            raise ValueError("PATCH_REQUIRES_JSON_METADATA")
        contract = (
            Contract(
                args.kind,
                tuple(args.canary),
                tuple(args.json_path),
                args.min_chars,
                args.expected_patch,
            )
            if args.canary or args.json_path or args.kind != "html"
            else None
        )
        result = (
            {"routes": collector.store.health()}
            if args.health
            else collector.batch(
                args.url,
                contract=contract,
                ttl=args.ttl,
                refresh=args.refresh,
                allow_stale=args.allow_stale,
                browser_only=args.browser_only,
            )
        )
        if args.output:
            from source_library import write_json

            write_json(args.output, access.scrub(result))
            print(
                json.dumps(
                    {"saved": str(args.output), "accounting": result.get("accounting")}
                )
            )
        else:
            print(json.dumps(access.scrub(result), ensure_ascii=False, indent=2))
        return int(any(r["verdict"] != "OK" for r in result.get("results", [])))
    except (ValueError, access.AccessError, sqlite3.Error):
        print(
            json.dumps({"error": "INVALID_INPUT_OR_SOURCE_STATE"}),
            file=sys.stderr,
        )
        return 2
    finally:
        if browser is not None:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
