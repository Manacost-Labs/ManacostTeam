#!/usr/bin/env python3
"""Chinese Hearthstone source ingestion with Scrape.do escalation.

The module is dependency-free and deliberately separates retrieval from
deterministic extraction. Provider credentials are read from the environment
and never included in output or exception messages.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import html
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

SCHEMA_VERSION = "1.1"
SCRAPE_DO_TOKEN_ENV = "SCRAPE_DO_API_TOKEN"
KHS_TOKEN_ENV = "KHS_API_TOKEN"
SCRAPE_DO_ENDPOINT = "https://api.scrape.do/"
KHS_BASE_URL = "https://api.kolodahearthstone.com"
MAX_RESPONSE_BYTES = 5_000_000
CACHE_FORMAT_VERSION = 1
RATE_WINDOW_SECONDS = 60.0
DEFAULT_REQUESTS_PER_MINUTE = 30
DEFAULT_MAX_RATE_WAIT_SECONDS = 30.0


class FetchStatus(str, Enum):
    SUCCESS = "SUCCESS"
    RATE_LIMITED = "RATE_LIMITED"
    BLOCKED = "BLOCKED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    INCOMPLETE = "INCOMPLETE"
    NETWORK_ERROR = "NETWORK_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    UNSUPPORTED = "UNSUPPORTED"


class CNClassification(str, Enum):
    CN_ORIGINAL = "CN_ORIGINAL"
    CN_VARIANT = "CN_VARIANT"
    CN_META = "CN_META"
    WESTERN_REPOST = "WESTERN_REPOST"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EscalationLevel:
    name: str
    render: bool = False
    super_proxy: bool = False


ESCALATION_LEVELS = (
    EscalationLevel("normal"),
    EscalationLevel("render", render=True),
    EscalationLevel("super", super_proxy=True),
    EscalationLevel("super_render", render=True, super_proxy=True),
)


@dataclass(frozen=True)
class SourceProfile:
    key: str
    display_name: str
    domains: tuple[str, ...]
    source_type: str
    poll_minutes: int
    min_clean_chars: int = 180
    expected_markers: tuple[str, ...] = ()
    search_hints: tuple[str, ...] = ()


SOURCE_PROFILES: dict[str, SourceProfile] = {
    "iyingdi": SourceProfile(
        "iyingdi",
        "旅法师营地 / IYingdi",
        ("iyingdi.com", "battle.com", "mob.battle.com"),
        "article",
        180,
        expected_markers=("炉石", "营地", "卡组"),
        search_hints=("国服", "卡组", "构筑", "攻略"),
    ),
    "taptap": SourceProfile(
        "taptap",
        "TapTap Hearthstone",
        ("taptap.cn", "taptap.com"),
        "community",
        120,
        expected_markers=("炉石", "TapTap", "卡组"),
        search_hints=("自创", "国服", "上分", "留牌"),
    ),
    "nga": SourceProfile(
        "nga",
        "NGA Hearthstone",
        ("nga.cn", "bbs.nga.cn"),
        "forum",
        120,
        expected_markers=("炉石", "卡组", "NGA"),
        search_hints=("自创", "国服", "对局", "攻略"),
    ),
    "bilibili": SourceProfile(
        "bilibili",
        "Bilibili",
        ("bilibili.com", "b23.tv"),
        "video",
        60,
        expected_markers=("哔哩哔哩", "bilibili", "视频"),
        search_hints=("炉石", "国服", "卡组", "攻略"),
    ),
    "gamersky": SourceProfile(
        "gamersky",
        "游民星空 / GamerSky",
        ("gamersky.com",),
        "secondary_article",
        720,
        expected_markers=("炉石", "游民星空", "卡组"),
        search_hints=("炉石传说", "卡组", "攻略"),
    ),
    "17173": SourceProfile(
        "17173",
        "17173 Hearthstone",
        ("17173.com",),
        "secondary_article",
        720,
        expected_markers=("炉石", "17173", "卡组"),
        search_hints=("炉石传说", "卡组", "国服"),
    ),
}


ANTI_BOT_MARKERS = (
    "captcha",
    "verify you are human",
    "人机验证",
    "安全验证",
    "访问过于频繁",
    "cf-chl-",
    "challenge-platform",
)
AUTH_MARKERS = ("请登录", "登录后查看", "sign in to continue", "login required")
BLOCK_MARKERS = ("access denied", "forbidden", "访问被拒绝", "请求被拦截")
SPA_MARKERS = ('id="root"></div>', 'id="app"></div>', "__next_data__")
DROP_HINTS = (
    "nav",
    "footer",
    "header",
    "sidebar",
    "advert",
    "recommend",
    "related",
    "login",
    "cookie",
    "share",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_url(url: str) -> str:
    """Drop fragments and common tracking parameters without changing identity."""
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Expected an absolute HTTP(S) URL.")
    kept = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"spm", "from", "source", "share_source"}
    ]
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path or "/",
            urlencode(kept),
            "",
        )
    )


def identify_source(url: str) -> SourceProfile | None:
    host = (urlsplit(url).hostname or "").lower()
    for profile in SOURCE_PROFILES.values():
        if any(
            host == domain or host.endswith(f".{domain}") for domain in profile.domains
        ):
            return profile
    return None


def profile_for(source: str | None, url: str | None = None) -> SourceProfile:
    if source:
        try:
            return SOURCE_PROFILES[source]
        except KeyError as exc:
            raise ValueError(f"Unsupported source profile: {source}") from exc
    if url:
        detected = identify_source(url)
        if detected:
            return detected
    raise ValueError("Source profile could not be determined.")


class CleanHTMLParser(HTMLParser):
    """Small deterministic cleaner for article-like public HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth_to_skip = 0
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): (value or "").lower() for key, value in attrs}
        marker = " ".join((attrs_map.get("class", ""), attrs_map.get("id", "")))
        should_drop = tag in {
            "script",
            "style",
            "noscript",
            "svg",
            "nav",
            "footer",
            "form",
        }
        should_drop = should_drop or any(hint in marker for hint in DROP_HINTS)
        if self.depth_to_skip:
            self.depth_to_skip += 1
        elif should_drop:
            self.depth_to_skip = 1
        elif tag == "title":
            self.in_title = True
        elif tag in {"p", "br", "li", "h1", "h2", "h3", "blockquote", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.depth_to_skip:
            self.depth_to_skip -= 1
            return
        if tag == "title":
            self.in_title = False
        elif tag in {"p", "li", "h1", "h2", "h3", "blockquote", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.depth_to_skip:
            return
        text = data.strip()
        if not text:
            return
        if self.in_title:
            self.title_parts.append(text)
        self.parts.append(text)

    def result(self) -> tuple[str | None, str]:
        title = " ".join(self.title_parts).strip() or None
        text = " ".join(self.parts)
        text = re.sub(r"[ \t\u00a0]+", " ", text)
        text = re.sub(r"\s*\n\s*", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return title, html.unescape(text)


def clean_html(raw_html: str) -> tuple[str | None, str]:
    parser = CleanHTMLParser()
    parser.feed(raw_html)
    parser.close()
    return parser.result()


class _MetadataHTMLParser(HTMLParser):
    """Collect declared HTML metadata without executing embedded content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.time_values: list[str] = []
        self.json_ld_blocks: list[str] = []
        self._in_json_ld = False
        self._json_ld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): value or "" for key, value in attrs}
        if tag == "meta":
            key = (
                attrs_map.get("property")
                or attrs_map.get("name")
                or attrs_map.get("itemprop")
                or ""
            ).strip().lower()
            content = attrs_map.get("content", "").strip()
            if key and content and key not in self.meta:
                self.meta[key] = content
        elif tag == "time" and attrs_map.get("datetime", "").strip():
            self.time_values.append(attrs_map["datetime"].strip())
        elif tag == "script" and "ld+json" in attrs_map.get("type", "").lower():
            self._in_json_ld = True
            self._json_ld_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._json_ld_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_json_ld:
            block = "".join(self._json_ld_parts).strip()
            if block:
                self.json_ld_blocks.append(block)
            self._in_json_ld = False
            self._json_ld_parts = []


@dataclass
class PageMetadata:
    author: str | None = None
    publisher: str | None = None
    published_at: str | None = None
    modified_at: str | None = None
    field_sources: dict[str, str] = field(default_factory=dict)


def _json_ld_nodes(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        graph = value.get("@graph")
        if isinstance(graph, (list, Mapping)):
            yield from _json_ld_nodes(graph)
    elif isinstance(value, list):
        for item in value:
            yield from _json_ld_nodes(item)


def _entity_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, Mapping):
        name = value.get("name")
        return str(name).strip() if name else None
    if isinstance(value, list):
        names = [name for item in value if (name := _entity_name(item))]
        return ", ".join(names) or None
    return None


def _normalize_timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
        except ValueError:
            return None
    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).isoformat()
    except ValueError:
        pass
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, pattern).isoformat()
        except ValueError:
            continue
    return None


def _title_date(title: str | None) -> str | None:
    match = re.search(r"(?<!\d)(20\d{6})(?!\d)", title or "")
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def extract_page_metadata(
    raw: str, clean_text: str, title: str | None
) -> PageMetadata:
    parser = _MetadataHTMLParser()
    try:
        parser.feed(raw)
        parser.close()
    except (TypeError, ValueError):
        return PageMetadata()

    metadata = PageMetadata()
    nodes: list[Mapping[str, Any]] = []
    for block in parser.json_ld_blocks:
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        nodes.extend(_json_ld_nodes(payload))

    for node in nodes:
        if metadata.author is None and (author := _entity_name(node.get("author"))):
            metadata.author = author
            metadata.field_sources["author"] = "json-ld:author"
        if metadata.publisher is None and (
            publisher := _entity_name(node.get("publisher"))
        ):
            metadata.publisher = publisher
            metadata.field_sources["publisher"] = "json-ld:publisher"
        if metadata.published_at is None:
            for key in ("datePublished", "pubDate"):
                if value := _normalize_timestamp(node.get(key)):
                    metadata.published_at = value
                    metadata.field_sources["published_at"] = f"json-ld:{key}"
                    break
        if metadata.modified_at is None:
            for key in ("dateModified", "upDate"):
                if value := _normalize_timestamp(node.get(key)):
                    metadata.modified_at = value
                    metadata.field_sources["modified_at"] = f"json-ld:{key}"
                    break

    if metadata.author is None:
        byline = re.search(r"(?:^|\n)([^\n]{1,40})\s+Lv\.\d+(?:\n|$)", clean_text)
        if byline:
            metadata.author = byline.group(1).strip()
            metadata.field_sources["author"] = "visible-byline:lv"
    if metadata.author is None:
        for key in ("article:author", "author", "byl"):
            if value := parser.meta.get(key):
                metadata.author = value
                metadata.field_sources["author"] = f"meta:{key}"
                break

    if metadata.publisher is None:
        for key in ("og:site_name", "application-name"):
            if value := parser.meta.get(key):
                metadata.publisher = value
                metadata.field_sources["publisher"] = f"meta:{key}"
                break
    if metadata.publisher is None and parser.meta.get("author"):
        metadata.publisher = parser.meta["author"]
        metadata.field_sources["publisher"] = "meta:author"

    if metadata.published_at is None:
        for key in (
            "article:published_time",
            "datepublished",
            "pubdate",
            "publishdate",
        ):
            if value := _normalize_timestamp(parser.meta.get(key)):
                metadata.published_at = value
                metadata.field_sources["published_at"] = f"meta:{key}"
                break
    if metadata.modified_at is None:
        for key in ("article:modified_time", "datemodified", "lastmod"):
            if value := _normalize_timestamp(parser.meta.get(key)):
                metadata.modified_at = value
                metadata.field_sources["modified_at"] = f"meta:{key}"
                break

    if metadata.published_at is None and parser.time_values:
        if value := _normalize_timestamp(parser.time_values[0]):
            metadata.published_at = value
            metadata.field_sources["published_at"] = "html:time[datetime]"
    if metadata.published_at is None and (value := _title_date(title)):
        metadata.published_at = value
        metadata.field_sources["published_at"] = "title:yyyymmdd"
    return metadata


@dataclass
class ValidationResult:
    valid: bool
    status: FetchStatus
    reasons: list[str] = field(default_factory=list)
    clean_text: str = ""
    title: str | None = None


def validate_content(
    body: str,
    profile: SourceProfile,
    *,
    status_code: int = 200,
    content_type: str = "text/html",
) -> ValidationResult:
    lowered = body.lower()
    if status_code == 429:
        return ValidationResult(
            False, FetchStatus.RATE_LIMITED, ["provider_rate_limited"]
        )
    if status_code in {401, 407}:
        return ValidationResult(
            False, FetchStatus.AUTH_REQUIRED, ["provider_auth_failed"]
        )
    if status_code == 403 or any(marker in lowered for marker in BLOCK_MARKERS):
        return ValidationResult(False, FetchStatus.BLOCKED, ["access_blocked"])
    if status_code in {404, 410}:
        return ValidationResult(False, FetchStatus.UNSUPPORTED, ["dead_url"])
    if status_code == 400:
        return ValidationResult(False, FetchStatus.UNSUPPORTED, ["bad_request"])
    if any(marker in lowered for marker in ANTI_BOT_MARKERS):
        return ValidationResult(False, FetchStatus.BLOCKED, ["challenge_page"])
    if any(marker.lower() in lowered for marker in AUTH_MARKERS):
        return ValidationResult(False, FetchStatus.AUTH_REQUIRED, ["login_wall"])

    if "json" in content_type.lower():
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return ValidationResult(False, FetchStatus.PARSE_ERROR, ["invalid_json"])
        clean_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        title = None
    else:
        try:
            title, clean_text = clean_html(body)
        except (TypeError, ValueError):
            return ValidationResult(
                False, FetchStatus.PARSE_ERROR, ["html_clean_failed"]
            )

    reasons: list[str] = []
    if len(clean_text) < profile.min_clean_chars:
        reasons.append("content_too_short")
    if profile.expected_markers and not any(
        marker.lower() in clean_text.lower() for marker in profile.expected_markers
    ):
        reasons.append("expected_marker_missing")
    if any(marker in lowered for marker in SPA_MARKERS) and len(clean_text) < 500:
        reasons.append("spa_shell")
    if reasons:
        return ValidationResult(
            False, FetchStatus.INCOMPLETE, reasons, clean_text, title
        )
    return ValidationResult(True, FetchStatus.SUCCESS, [], clean_text, title)


@dataclass
class FetchAttempt:
    level: str
    status: FetchStatus
    status_code: int | None
    elapsed_ms: int
    provider_status_code: int | None = None
    rate_limit_wait_ms: int = 0
    retry_after: str | None = None
    request_cost: str | None = None
    remaining_credits: str | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class FetchResult:
    status: FetchStatus
    requested_url: str
    resolved_url: str | None
    profile: str
    fetched_at: str
    body: str | None
    clean_text: str | None
    title: str | None
    content_type: str | None
    attempts: list[FetchAttempt]
    browser_fallback_required: bool = False
    cache_status: str = "BYPASS"
    cache_age_seconds: int | None = None
    diagnostic_codes: list[str] = field(default_factory=list)

    def public_dict(self, include_body: bool = False) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        for attempt in result["attempts"]:
            attempt["status"] = attempt["status"].value
        if not include_body:
            result.pop("body", None)
        reported_costs: list[float] = []
        for attempt in self.attempts:
            if attempt.request_cost is not None:
                try:
                    reported_costs.append(float(attempt.request_cost))
                except ValueError:
                    pass
        error_codes = list(
            dict.fromkeys(
                [
                    *self.diagnostic_codes,
                    *(
                        reason
                        for attempt in self.attempts
                        for reason in attempt.reasons
                    ),
                ]
            )
        )
        result["diagnostics"] = {
            "cache": {
                "status": self.cache_status,
                "age_seconds": self.cache_age_seconds,
            },
            "network_requests": sum(
                attempt.level != "local_rate_limit" for attempt in self.attempts
            ),
            "reported_credits_used": round(sum(reported_costs), 4),
            "unattributed_cost_attempts": sum(
                attempt.level != "local_rate_limit"
                and attempt.request_cost is None
                for attempt in self.attempts
            ),
            "remaining_credits": next(
                (
                    attempt.remaining_credits
                    for attempt in reversed(self.attempts)
                    if attempt.remaining_credits is not None
                ),
                None,
            ),
            "codes": error_codes,
        }
        return result


Transport = Callable[[Request, float], tuple[int, Mapping[str, str], bytes]]


def _urllib_transport(
    request: Request, timeout: float
) -> tuple[int, Mapping[str, str], bytes]:
    try:
        with urlopen(request, timeout=timeout) as response:
            return (
                response.status,
                response.headers,
                response.read(MAX_RESPONSE_BYTES + 1),
            )
    except HTTPError as exc:
        return exc.code, exc.headers, exc.read(MAX_RESPONSE_BYTES + 1)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    return next(
        (str(value) for key, value in headers.items() if str(key).lower() == wanted),
        None,
    )


def default_runtime_dir() -> Path:
    configured = os.environ.get("DEEP_RESEARCH_CACHE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser() / "chinese-hearthstone"
    return Path.home() / ".cache" / "deep-research" / "chinese-hearthstone"


class SlidingWindowRateLimiter:
    """Cross-process local limiter for provider requests."""

    def __init__(
        self,
        limit: int = DEFAULT_REQUESTS_PER_MINUTE,
        *,
        window_seconds: float = RATE_WINDOW_SECONDS,
        state_dir: Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if limit < 1:
            raise ValueError("Rate limit must be at least one request per window.")
        if window_seconds <= 0:
            raise ValueError("Rate-limit window must be positive.")
        self.limit = limit
        self.window_seconds = window_seconds
        self.state_dir = state_dir or default_runtime_dir()
        self.clock = clock

    def reserve(self) -> float:
        """Reserve one request or return seconds until capacity is available."""

        timestamp = self.clock()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        state_path = self.state_dir / "scrape-do-rate.json"
        lock_path = self.state_dir / "scrape-do-rate.lock"
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    raw = json.loads(state_path.read_text(encoding="utf-8"))
                    events = [
                        float(value)
                        for value in raw
                        if float(value) > timestamp - self.window_seconds
                    ]
                except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
                    events = []
                if len(events) >= self.limit:
                    return max(0.001, self.window_seconds - (timestamp - min(events)))
                events.append(timestamp)
                temporary = state_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(events), encoding="utf-8")
                os.chmod(temporary, 0o600)
                os.replace(temporary, state_path)
                return 0.0
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class FetchCache:
    """Private on-disk cache containing successful public source responses."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or default_runtime_dir() / "responses"

    @staticmethod
    def _key(target_url: str, profile: SourceProfile) -> str:
        material = f"{CACHE_FORMAT_VERSION}\n{profile.key}\n{target_url}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def load(
        self, target_url: str, profile: SourceProfile, ttl_seconds: float
    ) -> tuple[dict[str, Any] | None, int | None, str]:
        path = self.directory / f"{self._key(target_url, profile)}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            created_at = float(payload["created_at"])
            age = max(0, int(time.time() - created_at))
            if (
                payload.get("cache_format_version") != CACHE_FORMAT_VERSION
                or payload.get("requested_url") != target_url
                or payload.get("profile") != profile.key
                or not isinstance(payload.get("body"), str)
            ):
                return None, age, "INVALID"
            if age > ttl_seconds:
                return None, age, "STALE"
            return payload, age, "HIT"
        except FileNotFoundError:
            return None, None, "MISS"
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None, None, "INVALID"

    def store(self, result: FetchResult) -> None:
        if result.status != FetchStatus.SUCCESS or result.body is None:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        cache_key = self._key(result.requested_url, SOURCE_PROFILES[result.profile])
        path = self.directory / f"{cache_key}.json"
        payload = {
            "cache_format_version": CACHE_FORMAT_VERSION,
            "created_at": time.time(),
            "requested_url": result.requested_url,
            "resolved_url": result.resolved_url,
            "profile": result.profile,
            "fetched_at": result.fetched_at,
            "body": result.body,
            "content_type": result.content_type,
        }
        temporary = path.with_suffix(f".{os.getpid()}.{time.time_ns()}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)


class ScrapeDoClient:
    """Bounded Scrape.do client with content-aware mode escalation."""

    def __init__(
        self,
        token: str | None = None,
        *,
        timeout: float = 60.0,
        max_attempts_per_level: int = 1,
        max_retry_after: float = 30.0,
        max_rate_wait: float = DEFAULT_MAX_RATE_WAIT_SECONDS,
        transport: Transport = _urllib_transport,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        rate_limiter: SlidingWindowRateLimiter | None = None,
        cache: FetchCache | None = None,
        cache_ttl_seconds: float | None = None,
        refresh: bool = False,
    ) -> None:
        self._token = (token or os.environ.get(SCRAPE_DO_TOKEN_ENV, "")).strip()
        self.timeout = timeout
        self.max_attempts_per_level = max(1, min(max_attempts_per_level, 3))
        self.max_retry_after = max_retry_after
        self.max_rate_wait = max(0.0, max_rate_wait)
        self.transport = transport
        self.sleep = sleep
        self.rng = rng or random.Random()
        self.rate_limiter = rate_limiter
        self.cache = cache
        self.cache_ttl_seconds = cache_ttl_seconds
        self.refresh = refresh

    @property
    def configured(self) -> bool:
        return bool(self._token)

    def _provider_request(self, target_url: str, level: EscalationLevel) -> Request:
        if not self._token:
            raise RuntimeError(
                f"Credential is not configured. Set {SCRAPE_DO_TOKEN_ENV}."
            )
        params: dict[str, str] = {
            "token": self._token,
            "url": target_url,
            "disableRetry": "true",
            "transparentResponse": "true",
        }
        if level.render:
            params["render"] = "true"
        if level.super_proxy:
            params["super"] = "true"
        # Scrape.do API mode authenticates via a query parameter. The complete
        # provider URL stays inside this transport method and is never logged,
        # persisted, returned, or copied into an exception message.
        provider_url = f"{SCRAPE_DO_ENDPOINT}?{urlencode(params)}"
        return Request(
            provider_url,
            headers={
                "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
                "User-Agent": "ResearchTeam-Chinese-Hearthstone/1.0",
            },
            method="GET",
        )

    @staticmethod
    def _retry_after(headers: Mapping[str, str]) -> str | None:
        return _header(headers, "Retry-After")

    def _retry_delay(self, retry_after: str | None, attempt: int) -> float:
        if retry_after:
            try:
                seconds = float(retry_after)
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(retry_after)
                    seconds = max(0.0, parsed.timestamp() - time.time())
                except (TypeError, ValueError, OverflowError):
                    seconds = 0.0
            return min(seconds, self.max_retry_after)
        return min((2**attempt) + self.rng.uniform(0.0, 0.5), self.max_retry_after)

    def fetch(self, target_url: str, profile: SourceProfile) -> FetchResult:
        target_url = canonical_url(target_url)
        attempts: list[FetchAttempt] = []
        diagnostic_codes: list[str] = []
        cache_status = "BYPASS"
        cache_age: int | None = None
        if self.cache is not None:
            cache_status = "REFRESH" if self.refresh else "MISS"
            if not self.refresh:
                ttl_seconds = (
                    self.cache_ttl_seconds
                    if self.cache_ttl_seconds is not None
                    else profile.poll_minutes * 60
                )
                cached, cache_age, cache_status = self.cache.load(
                    target_url, profile, max(0.0, ttl_seconds)
                )
                if cached is not None:
                    body = cached["body"]
                    content_type = cached.get("content_type") or "text/html"
                    validation = validate_content(
                        body, profile, content_type=content_type
                    )
                    if validation.valid:
                        return FetchResult(
                            FetchStatus.SUCCESS,
                            target_url,
                            cached.get("resolved_url") or target_url,
                            profile.key,
                            cached.get("fetched_at") or utc_now(),
                            body,
                            validation.clean_text,
                            validation.title,
                            content_type,
                            [],
                            cache_status="HIT",
                            cache_age_seconds=cache_age,
                        )
                    cache_status = "INVALID"
                    diagnostic_codes.append("cached_content_invalid")
        last_status = FetchStatus.NETWORK_ERROR
        last_body: str | None = None
        last_clean: str | None = None
        last_title: str | None = None
        last_type: str | None = None
        last_resolved: str | None = None

        for level in ESCALATION_LEVELS:
            for attempt_number in range(self.max_attempts_per_level):
                rate_wait_ms = 0
                if self.rate_limiter is not None:
                    total_wait = 0.0
                    try:
                        while True:
                            wait_seconds = self.rate_limiter.reserve()
                            if wait_seconds <= 0:
                                break
                            if total_wait + wait_seconds > self.max_rate_wait:
                                last_status = FetchStatus.RATE_LIMITED
                                attempts.append(
                                    FetchAttempt(
                                        "local_rate_limit",
                                        last_status,
                                        429,
                                        0,
                                        rate_limit_wait_ms=int(total_wait * 1000),
                                        retry_after=str(max(1, int(wait_seconds + 0.999))),
                                        reasons=["local_rate_limit"],
                                    )
                                )
                                return FetchResult(
                                    last_status,
                                    target_url,
                                    None,
                                    profile.key,
                                    utc_now(),
                                    None,
                                    None,
                                    None,
                                    None,
                                    attempts,
                                    cache_status=cache_status,
                                    cache_age_seconds=cache_age,
                                    diagnostic_codes=[
                                        *diagnostic_codes,
                                        "local_rate_limit",
                                    ],
                                )
                            self.sleep(wait_seconds)
                            total_wait += wait_seconds
                        rate_wait_ms = int(total_wait * 1000)
                    except OSError:
                        last_status = FetchStatus.RATE_LIMITED
                        attempts.append(
                            FetchAttempt(
                                "local_rate_limit",
                                last_status,
                                None,
                                0,
                                reasons=["local_rate_limiter_unavailable"],
                            )
                        )
                        return FetchResult(
                            last_status,
                            target_url,
                            None,
                            profile.key,
                            utc_now(),
                            None,
                            None,
                            None,
                            None,
                            attempts,
                            cache_status=cache_status,
                            cache_age_seconds=cache_age,
                            diagnostic_codes=[
                                *diagnostic_codes,
                                "local_rate_limiter_unavailable",
                            ],
                        )
                started = time.monotonic()
                try:
                    request = self._provider_request(target_url, level)
                    status_code, headers, body_bytes = self.transport(
                        request, self.timeout
                    )
                except (URLError, TimeoutError, OSError):
                    elapsed = int((time.monotonic() - started) * 1000)
                    last_status = FetchStatus.NETWORK_ERROR
                    attempts.append(
                        FetchAttempt(
                            level.name,
                            last_status,
                            None,
                            elapsed,
                            rate_limit_wait_ms=rate_wait_ms,
                            reasons=["network_error"],
                        )
                    )
                    if attempt_number + 1 < self.max_attempts_per_level:
                        self.sleep(self._retry_delay(None, attempt_number))
                    continue
                elapsed = int((time.monotonic() - started) * 1000)
                content_type = _header(headers, "Content-Type") or "text/html"
                target_status_text = _header(headers, "Scrape.do-Initial-Status-Code")
                try:
                    target_status = (
                        int(target_status_text) if target_status_text else status_code
                    )
                except ValueError:
                    target_status = status_code
                if 300 <= target_status < 400:
                    target_status = status_code
                charset = "utf-8"
                match = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
                if match:
                    charset = match.group(1)
                try:
                    body = body_bytes.decode(charset, errors="replace")
                except LookupError:
                    body = body_bytes.decode("utf-8", errors="replace")
                validation = validate_content(
                    body, profile, status_code=target_status, content_type=content_type
                )
                retry_after = self._retry_after(headers)
                request_cost = _header(headers, "Scrape.do-Request-Cost")
                remaining_credits = _header(headers, "Scrape.do-Remaining-Credits")
                if len(body_bytes) > MAX_RESPONSE_BYTES:
                    validation = ValidationResult(
                        False,
                        FetchStatus.INCOMPLETE,
                        ["response_too_large"],
                        validation.clean_text,
                        validation.title,
                    )
                attempts.append(
                    FetchAttempt(
                        level.name,
                        validation.status,
                        target_status,
                        elapsed,
                        provider_status_code=status_code,
                        rate_limit_wait_ms=rate_wait_ms,
                        retry_after=retry_after,
                        request_cost=request_cost,
                        remaining_credits=remaining_credits,
                        reasons=validation.reasons,
                    )
                )
                last_status = validation.status
                last_body = body
                last_clean = validation.clean_text
                last_title = validation.title
                last_type = content_type
                last_resolved = _header(headers, "Scrape.do-Resolved-Url") or target_url
                if validation.valid:
                    result = FetchResult(
                        FetchStatus.SUCCESS,
                        target_url,
                        last_resolved,
                        profile.key,
                        utc_now(),
                        body,
                        validation.clean_text,
                        validation.title,
                        content_type,
                        attempts,
                        cache_status=cache_status,
                        cache_age_seconds=cache_age,
                        diagnostic_codes=diagnostic_codes,
                    )
                    if self.cache is not None:
                        try:
                            self.cache.store(result)
                        except (OSError, KeyError):
                            result.diagnostic_codes.append("cache_write_failed")
                    return result
                retryable = validation.status in {
                    FetchStatus.RATE_LIMITED,
                    FetchStatus.NETWORK_ERROR,
                } or target_status in {500, 502, 503, 504}
                if retryable and attempt_number + 1 < self.max_attempts_per_level:
                    self.sleep(self._retry_delay(retry_after, attempt_number))
                else:
                    break
            if last_status in {
                FetchStatus.AUTH_REQUIRED,
                FetchStatus.RATE_LIMITED,
                FetchStatus.UNSUPPORTED,
            }:
                break

        return FetchResult(
            last_status,
            target_url,
            last_resolved,
            profile.key,
            utc_now(),
            last_body,
            last_clean,
            last_title,
            last_type,
            attempts,
            browser_fallback_required=last_status
            in {FetchStatus.BLOCKED, FetchStatus.INCOMPLETE, FetchStatus.PARSE_ERROR},
            cache_status=cache_status,
            cache_age_seconds=cache_age,
            diagnostic_codes=diagnostic_codes,
        )


def _read_varint(raw: bytes, position: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while position < len(raw):
        byte = raw[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, position
        shift += 7
        if shift > 63:
            raise ValueError("Deckstring varint is too large.")
    raise ValueError("Unexpected end of deckstring.")


@dataclass
class Deck:
    deckstring: str
    format_id: int
    heroes: list[int]
    cards: dict[int, int]
    sideboards: list[tuple[int, int, int]] = field(default_factory=list)
    valid: bool = True
    validation_errors: list[str] = field(default_factory=list)
    cards_total: int = 0
    fingerprint: str = ""
    validation_warnings: list[str] = field(default_factory=list)
    deck_size_status: str = "EXPECTED"

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "cards": {str(key): value for key, value in sorted(self.cards.items())},
        }


def deck_fingerprint(cards: Mapping[int, int]) -> str:
    canonical = "|".join(f"{dbf}:{count}" for dbf, count in sorted(cards.items()))
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def decode_deckstring(deckstring: str, *, expected_cards: int | None = 30) -> Deck:
    normalized = re.sub(r"\s+", "", deckstring).strip()
    errors: list[str] = []
    warnings: list[str] = []
    try:
        padding = "=" * ((4 - len(normalized) % 4) % 4)
        raw = base64.b64decode(normalized + padding, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid base64 deckstring.") from exc
    if not raw or raw[0] != 0:
        raise ValueError("Invalid deckstring header.")
    position = 1
    version, position = _read_varint(raw, position)
    if version != 1:
        raise ValueError(f"Unsupported deckstring version: {version}")
    format_id, position = _read_varint(raw, position)
    if format_id not in {1, 2, 3}:
        errors.append("unsupported_format")

    hero_count, position = _read_varint(raw, position)
    heroes: list[int] = []
    for _ in range(hero_count):
        hero, position = _read_varint(raw, position)
        heroes.append(hero)
    if not heroes:
        errors.append("missing_hero")

    cards: Counter[int] = Counter()
    one_count, position = _read_varint(raw, position)
    for _ in range(one_count):
        card_id, position = _read_varint(raw, position)
        cards[card_id] += 1
    two_count, position = _read_varint(raw, position)
    for _ in range(two_count):
        card_id, position = _read_varint(raw, position)
        cards[card_id] += 2
    n_count, position = _read_varint(raw, position)
    for _ in range(n_count):
        card_id, position = _read_varint(raw, position)
        count, position = _read_varint(raw, position)
        if count <= 0:
            errors.append("invalid_card_count")
        cards[card_id] += count

    sideboards: list[tuple[int, int, int]] = []
    if position < len(raw):
        sideboard_version = raw[position]
        position += 1
        if sideboard_version == 1:
            for fixed_count in (1, 2):
                group_count, position = _read_varint(raw, position)
                for _ in range(group_count):
                    card_id, position = _read_varint(raw, position)
                    owner, position = _read_varint(raw, position)
                    sideboards.append((card_id, fixed_count, owner))
            group_count, position = _read_varint(raw, position)
            for _ in range(group_count):
                card_id, position = _read_varint(raw, position)
                count, position = _read_varint(raw, position)
                owner, position = _read_varint(raw, position)
                sideboards.append((card_id, count, owner))
        elif sideboard_version != 0:
            errors.append("unsupported_sideboard_version")
    if position != len(raw):
        errors.append("trailing_deckstring_data")

    cards_total = sum(cards.values())
    if expected_cards is None:
        deck_size_status = "UNCHECKED"
    elif cards_total == expected_cards:
        deck_size_status = "EXPECTED"
    else:
        # Rulebreaker cards and other client-supported mechanics may encode
        # generated or auxiliary cards in addition to the playable deck. A
        # size mismatch is therefore a review signal, not structural damage.
        warnings.append(f"unexpected_card_total:{cards_total}")
        deck_size_status = "SPECIAL_OR_UNVERIFIED"
    if any(dbf <= 0 for dbf in cards):
        errors.append("invalid_dbf_id")
    return Deck(
        normalized,
        format_id,
        heroes,
        dict(cards),
        sideboards,
        not errors,
        errors,
        cards_total,
        deck_fingerprint(cards),
        warnings,
        deck_size_status,
    )


DECKSTRING_PATTERN = re.compile(r"(?<![A-Za-z0-9+/])AAE[A-Za-z0-9+/_=-]{18,}")


def _deck_occurrences(
    text: str, *, expected_cards: int | None = 30, deduplicate: bool = True
) -> list[tuple[Deck, int, int]]:
    occurrences: list[tuple[Deck, int, int]] = []
    seen: set[str] = set()
    for match in DECKSTRING_PATTERN.finditer(text):
        candidate = match.group(0).rstrip(".,;:!?，。；：！？)]}〉》")
        if deduplicate and candidate in seen:
            continue
        seen.add(candidate)
        try:
            deck = decode_deckstring(candidate, expected_cards=expected_cards)
        except ValueError as exc:
            deck = Deck(
                candidate,
                0,
                [],
                {},
                valid=False,
                validation_errors=[str(exc)],
            )
        occurrences.append((deck, match.start(), match.start() + len(candidate)))
    return occurrences


def extract_deckstrings(text: str, *, expected_cards: int | None = 30) -> list[Deck]:
    return [
        deck
        for deck, _, _ in _deck_occurrences(text, expected_cards=expected_cards)
    ]


@dataclass
class DeckComparison:
    shared_cards: int
    left_total: int
    right_total: int
    similarity: float
    relation: str
    removed: dict[int, int]
    added: dict[int, int]

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["removed"] = {
            str(key): count for key, count in sorted(self.removed.items())
        }
        value["added"] = {str(key): count for key, count in sorted(self.added.items())}
        return value


def compare_decks(left: Mapping[int, int], right: Mapping[int, int]) -> DeckComparison:
    shared = sum(
        min(left.get(key, 0), right.get(key, 0)) for key in set(left) | set(right)
    )
    left_total = sum(left.values())
    right_total = sum(right.values())
    denominator = max(left_total, right_total, 1)
    if shared == left_total == right_total:
        relation = "EXACT"
    elif shared == 29 and left_total == right_total == 30:
        relation = "NEAR_DUPLICATE"
    elif shared == 28 and left_total == right_total == 30:
        relation = "VARIANT"
    elif 26 <= shared <= 27 and left_total == right_total == 30:
        relation = "ARCHETYPE_VARIANT"
    else:
        relation = "DISTINCT"
    removed = {
        key: count
        for key in set(left) | set(right)
        if (count := left.get(key, 0) - right.get(key, 0)) > 0
    }
    added = {
        key: count
        for key in set(left) | set(right)
        if (count := right.get(key, 0) - left.get(key, 0)) > 0
    }
    return DeckComparison(
        shared,
        left_total,
        right_total,
        round(shared / denominator, 4),
        relation,
        removed,
        added,
    )


REGION_MAP = {"国服": "CN", "欧服": "EU", "美服": "NA", "亚服": "ASIA"}

CN_HEARTHSTONE_TERMS = {
    "炉石传说": "Hearthstone",
    "卡组": "deck",
    "套牌": "deck",
    "卡组代码": "deck code",
    "卡组分享": "deck share",
    "攻略": "guide",
    "标准": "Standard",
    "标准模式": "Standard",
    "狂野": "Wild",
    "狂野模式": "Wild",
    "酒馆战棋": "Battlegrounds",
    "职业": "class",
    "胜率": "winrate",
    "场数": "games",
    "总场数": "games",
    "赢": "wins",
    "输": "losses",
    "传说": "Legend",
    "登顶": "Rank 1 / top ladder",
    "上分": "ladder climbing",
    "环境": "meta",
    "构筑": "deckbuilding",
    "对局": "matchup",
    "留牌": "mulligan",
    "补丁": "patch",
    "数据": "data",
    "来源": "source",
    "作者": "author",
    "最新": "latest",
    "国服": "CN server",
    "欧服": "EU",
    "美服": "Americas",
    "亚服": "Asia",
}


@dataclass
class CNStats:
    region: str | None = None
    games: int | None = None
    wins: int | None = None
    losses: int | None = None
    win_rate: float | None = None
    rank_range: str | None = None
    average_game_minutes: float | None = None
    updated_at_raw: str | None = None


def _number_after(
    text: str, labels: Iterable[str], *, decimal: bool = False
) -> float | int | None:
    joined = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{joined})\s*[:：]?\s*([0-9]+(?:\.[0-9]+)?)", text, re.IGNORECASE
    )
    if not match:
        return None
    return float(match.group(1)) if decimal else int(float(match.group(1)))


def extract_cn_stats(text: str) -> CNStats:
    region = next((code for marker, code in REGION_MAP.items() if marker in text), None)
    win_rate = _number_after(text, ("胜率",), decimal=True)
    rank_match = re.search(
        r"(?:排名区间|分段|排名)\s*[:：]?\s*([^\n，。；]{1,40})", text
    )
    updated_match = re.search(
        r"(?:最后更新时间|更新时间)\s*[:：]?\s*([^\n，。；]{4,40})", text
    )
    return CNStats(
        region=region,
        games=_number_after(text, ("总场数", "场次", "样本")),
        wins=_number_after(text, ("胜场", "赢")),
        losses=_number_after(text, ("负场", "输")),
        win_rate=float(win_rate) if win_rate is not None else None,
        rank_range=rank_match.group(1).strip() if rank_match else None,
        average_game_minutes=(
            float(value)
            if (value := _number_after(text, ("平均对局时长",), decimal=True))
            is not None
            else None
        ),
        updated_at_raw=updated_match.group(1).strip() if updated_match else None,
    )


def _has_cn_stats(stats: CNStats) -> bool:
    return any(value is not None for value in asdict(stats).values())


_DECK_LABEL_SKIP_MARKERS = (
    "复制代码",
    "跳转详情",
    "卡组代码",
    "卡组简析",
    "卡组介绍",
    "服务器",
    "总场数",
    "胜率",
    "排名区间",
    "平均对局时长",
    "最后更新时间",
)


def _is_deck_label_candidate(line: str) -> bool:
    normalized = line.strip(" #*-｜|")
    if not normalized or len(normalized) > 50:
        return False
    if DECKSTRING_PATTERN.search(normalized) or re.match(r"^https?://", normalized):
        return False
    if any(marker in normalized for marker in _DECK_LABEL_SKIP_MARKERS):
        return False
    if re.match(r"^(?:赢|输|粉尘|传说|史诗|普通|稀有)\s*[:：]", normalized):
        return False
    return bool(re.search(r"[\u3400-\u9fff]", normalized))


def _extract_deck_label(after: str, before: str) -> str | None:
    after_lines = [line.strip() for line in after.splitlines() if line.strip()]
    for index, line in enumerate(after_lines):
        if re.match(r"^服务器\s*[:：]", line):
            for candidate in after_lines[index + 1 : index + 4]:
                if _is_deck_label_candidate(candidate):
                    return candidate.strip(" #*-｜|")

    combined = f"{before[-600:]}\n{after[:600]}"
    class_label = re.search(
        r"(?:^|\n)\s*((?:德鲁伊|潜行者|萨满祭司|萨满|法师|猎人|"
        r"圣骑士|牧师|术士|战士|恶魔猎手|死亡骑士)\s*[｜|]\s*"
        r"[^\n]{1,30})",
        combined,
    )
    if class_label:
        return class_label.group(1).strip()

    before_lines = [line.strip() for line in before.splitlines() if line.strip()]
    for candidate in reversed(before_lines[-8:]):
        if _is_deck_label_candidate(candidate):
            return candidate.strip(" #*-｜|")
    return None


def extract_deck_records(
    text: str, *, expected_cards: int | None = 30
) -> list[dict[str, Any]]:
    """Associate each deck code with its nearest label and statistics block."""
    occurrences = _deck_occurrences(
        text, expected_cards=expected_cards, deduplicate=False
    )
    records: list[dict[str, Any]] = []
    for index, (deck, start, end) in enumerate(occurrences, start=1):
        next_start = (
            occurrences[index][1] if index < len(occurrences) else len(text)
        )
        previous_end = occurrences[index - 2][2] if index > 1 else 0
        before = text[previous_end:start]
        after = text[end:next_start]
        stats = extract_cn_stats(after)
        if len(occurrences) == 1 and not _has_cn_stats(stats):
            stats = extract_cn_stats(text)
        context = after.strip() or before.strip()
        records.append(
            {
                "index": index,
                "archetype_zh": _extract_deck_label(after, before),
                "deck": deck.as_dict(),
                "statistics": asdict(stats),
                "source_locator": {"start": start, "end": next_start},
                "context_hash": hashlib.sha256(context.encode("utf-8")).hexdigest(),
            }
        )
    return records


@dataclass
class Provenance:
    original_author: str | None = None
    original_source: str | None = None
    attribution_url: str | None = None
    repost_markers: list[str] = field(default_factory=list)
    attribution_quality: str = "NONE"


def extract_provenance(text: str) -> Provenance:
    source = re.search(
        r"(?:来源|转载自|原文)\s*[:：]\s*([^\n，。；】\]]{1,100})", text
    )
    author = re.search(
        r"(?:作者|原作者)\s*[:：]\s*([^\n，。；】\]]{1,60})", text
    )
    if author is None:
        author = re.search(r"本期由\s*([^\n，。；】\]]{1,60}?)\s*给大家带来", text)
    url = re.search(r"https?://[^\s<>'\"]+", text)
    markers = [marker for marker in ("来源", "转载", "搬运", "原文") if marker in text]
    source_value = source.group(1).strip() if source else None
    author_value = author.group(1).strip() if author else None
    attribution_url = url.group(0).rstrip(".,;，。；") if url else None
    return Provenance(
        original_author=author_value,
        original_source=source_value,
        attribution_url=attribution_url,
        repost_markers=markers,
        attribution_quality=(
            "DIRECT_URL"
            if attribution_url
            else "PARTIAL"
            if source_value or author_value
            else "NONE"
        ),
    )


@dataclass
class ClassificationResult:
    label: CNClassification
    confidence: float
    signals: list[str]
    comparison: dict[str, Any] | None = None


ORIGINAL_MARKERS = ("自创", "原创", "自己构筑", "本人构筑", "独家构筑")
CN_RESULT_MARKERS = ("国服", "登顶", "国服前", "排名", "传说")
WESTERN_MARKERS = (
    "hearthstone-decks.net",
    "hsreplay",
    "hsguru",
    "hearthstonetopdecks",
    "d0nkey",
    "vicious syndicate",
)


def classify_cn_deck(
    text: str,
    stats: CNStats,
    provenance: Provenance,
    *,
    western_match_checked: bool = False,
    comparison: DeckComparison | None = None,
) -> ClassificationResult:
    lowered = text.lower()
    signals: list[str] = []
    original = [marker for marker in ORIGINAL_MARKERS if marker in text]
    cn_results = [marker for marker in CN_RESULT_MARKERS if marker in text]
    western = [marker for marker in WESTERN_MARKERS if marker in lowered]
    if provenance.repost_markers:
        signals.extend(f"repost:{marker}" for marker in provenance.repost_markers)
    signals.extend(f"western:{marker}" for marker in western)
    if western and provenance.repost_markers:
        return ClassificationResult(CNClassification.WESTERN_REPOST, 0.95, signals)

    if (
        comparison
        and comparison.relation
        in {
            "NEAR_DUPLICATE",
            "VARIANT",
            "ARCHETYPE_VARIANT",
        }
        and (cn_results or stats.region == "CN")
    ):
        signals.append(f"western_similarity:{comparison.shared_cards}/30")
        return ClassificationResult(
            CNClassification.CN_VARIANT,
            0.9 if comparison.shared_cards >= 28 else 0.8,
            signals,
            comparison.as_dict(),
        )

    if original and cn_results and western_match_checked and not comparison:
        signals.extend(f"original:{marker}" for marker in original)
        signals.extend(f"cn:{marker}" for marker in cn_results)
        return ClassificationResult(CNClassification.CN_ORIGINAL, 0.9, signals)

    statistical = stats.region == "CN" and any(
        value is not None for value in (stats.games, stats.win_rate, stats.rank_range)
    )
    if statistical:
        signals.append("cn_ladder_statistics")
        return ClassificationResult(CNClassification.CN_META, 0.85, signals)

    if original:
        signals.extend(f"unverified_original:{marker}" for marker in original)
    return ClassificationResult(
        CNClassification.UNKNOWN, 0.35 if original else 0.2, signals
    )


class CardDatabase(Protocol):
    def get_card(self, dbf_id: int) -> dict[str, Any] | None: ...


class KolodaCardDatabase:
    """Read-only DBF resolver for api.kolodahearthstone.com."""

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str = KHS_BASE_URL,
        timeout: float = 8.0,
        max_attempts: int = 2,
        transport: Transport = _urllib_transport,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._token = (token or os.environ.get(KHS_TOKEN_ENV, "")).strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_attempts = max(1, min(max_attempts, 3))
        self.transport = transport
        self.sleep = sleep
        self._cache: dict[int, dict[str, Any] | None] = {}

    @property
    def authenticated(self) -> bool:
        return bool(self._token)

    def get_card(self, dbf_id: int) -> dict[str, Any] | None:
        if dbf_id <= 0:
            raise ValueError("DBF ID must be positive.")
        if dbf_id in self._cache:
            return self._cache[dbf_id]
        url = f"{self.base_url}/api/v1/constructed-cards/by-dbf/{dbf_id}"
        headers = {"Accept": "application/json", "User-Agent": "ResearchTeam/1.0"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = Request(url, headers=headers, method="GET")
        for attempt in range(self.max_attempts):
            try:
                status, response_headers, body = self.transport(request, self.timeout)
            except (URLError, TimeoutError, OSError) as exc:
                if attempt + 1 < self.max_attempts:
                    self.sleep(min(2**attempt, 4))
                    continue
                raise RuntimeError("Koloda card API request failed.") from exc
            if status == 404:
                self._cache[dbf_id] = None
                return None
            if (status == 429 or status in {502, 503, 504}) and (
                attempt + 1 < self.max_attempts
            ):
                retry_after = _header(response_headers, "Retry-After")
                try:
                    delay = min(float(retry_after or 2**attempt), 10.0)
                except ValueError:
                    delay = min(float(2**attempt), 10.0)
                self.sleep(delay)
                continue
            if status in {401, 403}:
                raise RuntimeError("Koloda card API authorization failed.")
            if status != 200:
                raise RuntimeError(f"Koloda card API returned HTTP {status}.")
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError("Koloda card API returned invalid JSON.") from exc
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict) or data.get("dbf") != dbf_id:
                raise RuntimeError(
                    "Koloda card API returned an unexpected response shape."
                )
            normalized = {
                "dbf": data.get("dbf"),
                "card_id": data.get("card_id"),
                "name": data.get("name") or {},
                "card_class": data.get("class"),
                "card_type": data.get("card_type"),
                "card_set": data.get("card_set"),
                "collectible": data.get("collectible"),
                "formats": data.get("formats") or [],
                "updated_at": data.get("updated_at"),
            }
            self._cache[dbf_id] = normalized
            return normalized
        raise RuntimeError("Koloda card API request failed.")

    def resolve_deck(self, deck: Deck) -> dict[str, Any]:
        cards: list[dict[str, Any]] = []
        missing: list[int] = []
        for dbf_id, count in sorted(deck.cards.items()):
            card = self.get_card(dbf_id)
            if card is None:
                missing.append(dbf_id)
                continue
            cards.append({**card, "count": count})
        noncollectible = [
            card for card in cards if card.get("collectible") is False
        ]
        if deck.deck_size_status == "EXPECTED":
            size_assessment = "EXPECTED"
        elif noncollectible:
            size_assessment = "SPECIAL_ENCODING_DETECTED"
        else:
            size_assessment = "SPECIAL_OR_UNVERIFIED"
        return {
            "cards": cards,
            "missing_dbf_ids": missing,
            "complete": not missing and len(cards) == len(deck.cards),
            "deck_size_assessment": size_assessment,
            "collectible_entries_total": sum(
                card["count"] for card in cards if card.get("collectible") is True
            ),
            "noncollectible_entries_total": sum(
                card["count"] for card in noncollectible
            ),
            "noncollectible_dbf_ids": [card["dbf"] for card in noncollectible],
            "source": self.base_url,
        }


@dataclass
class GuideEvidence:
    evidence_id: str
    source_id: str
    source_url: str
    source_type: str
    category: str
    text_zh: str
    translation_ru: str | None
    timestamp_start: float | None
    timestamp_end: float | None
    topic_key: str
    stance: str
    lineage_id: str
    confidence: float
    collected_at: str


GUIDE_CATEGORIES = {
    "mulligan": ("留牌", "起手"),
    "matchup": ("对局", "优势", "劣势"),
    "gameplan": ("打法", "思路", "运营"),
    "replacement": ("替换", "可换", "单卡选择"),
    "result": ("胜率", "战绩", "登顶", "排名"),
}


def classify_guide_category(text: str) -> str:
    return next(
        (
            category
            for category, markers in GUIDE_CATEGORIES.items()
            if any(m in text for m in markers)
        ),
        "observation",
    )


def build_guide_queries(deckstring: str | None, archetype: str | None) -> list[str]:
    subject = deckstring or archetype
    if not subject:
        raise ValueError("A deckstring or archetype is required.")
    terms = ("留牌", "对局", "攻略", "国服", "上分", "构筑")
    sites = ("nga.cn", "taptap.cn", "bilibili.com", "iyingdi.com")
    return [f'site:{site} "{subject}" {term}' for site in sites for term in terms]


def empty_guide_schema() -> dict[str, Any]:
    """Return the ingestion contract; synthesis must happen downstream."""
    return {
        "content_type": "deck_guide",
        "gameplan": {"early_game": [], "mid_game": [], "late_game": []},
        "mulligan": {"always_keep": [], "conditional_keep": [], "never_keep": []},
        "matchups": [],
        "card_choices": [],
        "replacements": [],
        "combos": [],
        "win_conditions": [],
        "common_mistakes": [],
        "meta_observations": [],
        "author_claims": {
            "rank": None,
            "games": None,
            "wins": None,
            "losses": None,
            "winrate": None,
        },
    }


def make_guide_evidence(
    *,
    source_id: str,
    source_url: str,
    source_type: str,
    text_zh: str,
    lineage_id: str,
    index: int = 1,
    start: float | None = None,
    end: float | None = None,
    translation_ru: str | None = None,
    confidence: float = 0.65,
) -> GuideEvidence:
    category = classify_guide_category(text_zh)
    topic_key = hashlib.sha256(f"{category}|{text_zh.strip()}".encode()).hexdigest()[
        :16
    ]
    stance = (
        "negative"
        if any(term in text_zh for term in ("不要", "不留", "劣势", "不推荐"))
        else "positive"
    )
    return GuideEvidence(
        f"GE-{source_id}-{index:04d}",
        source_id,
        source_url,
        source_type,
        category,
        text_zh.strip(),
        translation_ru,
        start,
        end,
        topic_key,
        stance,
        lineage_id,
        confidence,
        utc_now(),
    )


def parse_bilibili_payload(
    payload: Mapping[str, Any], source_url: str
) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
    video_id = str(data.get("bvid") or data.get("aid") or data.get("id") or "unknown")
    owner = data.get("owner") if isinstance(data.get("owner"), Mapping) else {}
    subtitle = data.get("subtitle") or data.get("subtitles") or []
    if isinstance(subtitle, Mapping):
        subtitle = subtitle.get("body") or subtitle.get("segments") or []
    segments: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for index, item in enumerate(
        subtitle if isinstance(subtitle, list) else [], start=1
    ):
        if not isinstance(item, Mapping):
            continue
        text_zh = str(item.get("content") or item.get("text") or "").strip()
        if not text_zh:
            continue
        start = item.get("from") if item.get("from") is not None else item.get("start")
        end = item.get("to") if item.get("to") is not None else item.get("end")
        segment = {"start": start, "end": end, "text_zh": text_zh}
        segments.append(segment)
        if any(
            marker in text_zh
            for markers in GUIDE_CATEGORIES.values()
            for marker in markers
        ):
            evidence.append(
                asdict(
                    make_guide_evidence(
                        source_id=video_id,
                        source_url=source_url,
                        source_type="bilibili_subtitle",
                        text_zh=text_zh,
                        lineage_id=f"bilibili:{video_id}",
                        index=index,
                        start=float(start) if start is not None else None,
                        end=float(end) if end is not None else None,
                    )
                )
            )
    description = str(data.get("desc") or data.get("description") or "")
    comments = data.get("comments") or payload.get("comments") or []
    useful_comments: list[dict[str, Any]] = []
    for index, item in enumerate(
        comments if isinstance(comments, list) else [], start=1
    ):
        if not isinstance(item, Mapping):
            continue
        message = str(
            item.get("message") or item.get("content") or item.get("text") or ""
        ).strip()
        if len(message) < 8 or not any(
            marker in message
            for markers in GUIDE_CATEGORIES.values()
            for marker in markers
        ):
            continue
        useful_comments.append(
            {
                "comment_id": item.get("rpid") or item.get("id"),
                "author": item.get("author") or item.get("uname"),
                "text_zh": message,
                "category": classify_guide_category(message),
                "likes": item.get("like") or item.get("likes"),
                "provider_position": index,
                "evidence_status": "community_observation",
            }
        )
    return {
        "video_id": video_id,
        "title": data.get("title"),
        "author": owner.get("name") or data.get("author"),
        "published_at": data.get("pubdate") or data.get("published_at"),
        "description_zh": description,
        "deckstrings": [deck.as_dict() for deck in extract_deckstrings(description)],
        "transcript_segments": segments,
        "guide_evidence": evidence,
        "useful_comments": useful_comments,
    }


def cluster_evidence(records: Iterable[GuideEvidence]) -> list[dict[str, Any]]:
    groups: dict[str, list[GuideEvidence]] = defaultdict(list)
    for record in records:
        groups[record.topic_key].append(record)
    clusters: list[dict[str, Any]] = []
    for topic_key, items in sorted(groups.items()):
        lineages = {item.lineage_id for item in items}
        stances = {item.stance for item in items}
        if len(stances) > 1:
            state = "conflicting"
        elif len(lineages) >= 2:
            state = "corroborated"
        else:
            state = "single_source"
        clusters.append(
            {
                "topic_key": topic_key,
                "state": state,
                "independent_lineages": len(lineages),
                "evidence_ids": [item.evidence_id for item in items],
            }
        )
    return clusters


DEFAULT_SCORE_WEIGHTS = {
    "originality": 0.30,
    "performance": 0.25,
    "evidence": 0.20,
    "freshness": 0.15,
    "guide": 0.10,
}


def cn_deck_score(
    components: Mapping[str, float],
    weights: Mapping[str, float] = DEFAULT_SCORE_WEIGHTS,
) -> float:
    if set(weights) != set(DEFAULT_SCORE_WEIGHTS):
        raise ValueError("Score weights must define all CN deck score components.")
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        raise ValueError("Score weights must sum to 1.0.")
    for key in weights:
        value = components.get(key, 0.0)
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"Score component {key} must be between 0 and 1.")
    return round(
        sum(components.get(key, 0.0) * weight for key, weight in weights.items()) * 100,
        2,
    )


def source_type_for(profile: SourceProfile, classification: CNClassification) -> str:
    if classification == CNClassification.WESTERN_REPOST:
        return (
            "secondary_repost"
            if profile.source_type.startswith("secondary")
            else "western_repost"
        )
    if classification == CNClassification.CN_ORIGINAL:
        return "original_cn"
    if classification == CNClassification.CN_META:
        return "cn_data"
    if profile.source_type in {"community", "forum", "video"}:
        return "cn_community"
    if profile.source_type.startswith("secondary"):
        return "compilation"
    return "unknown"


def pipeline_metrics(
    fetches: Iterable[FetchResult], documents: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    fetch_rows = list(fetches)
    document_rows = list(documents)
    mode_successes: Counter[str] = Counter()
    credits: list[float] = []
    for fetch in fetch_rows:
        for attempt in fetch.attempts:
            if attempt.status == FetchStatus.SUCCESS:
                mode_successes[attempt.level] += 1
            if attempt.request_cost is not None:
                try:
                    credits.append(float(attempt.request_cost))
                except ValueError:
                    pass
    all_decks = [
        deck for document in document_rows for deck in document.get("decks", [])
    ]
    fingerprints = [deck.get("fingerprint") for deck in all_decks if deck.get("valid")]
    classes = Counter(
        str(document.get("classification", {}).get("label", "UNKNOWN"))
        for document in document_rows
    )
    attributed = sum(
        bool(document.get("provenance", {}).get("original_source"))
        for document in document_rows
    )
    cache_hits = sum(fetch.cache_status == "HIT" for fetch in fetch_rows)
    network_requests = sum(
        attempt.level != "local_rate_limit"
        for fetch in fetch_rows
        for attempt in fetch.attempts
    )
    return {
        "pages_discovered": len(fetch_rows),
        "pages_fetched": sum(
            fetch.status == FetchStatus.SUCCESS for fetch in fetch_rows
        ),
        "successes_by_mode": dict(mode_successes),
        "blocked_pages": sum(
            fetch.status == FetchStatus.BLOCKED for fetch in fetch_rows
        ),
        "rate_limited_pages": sum(
            fetch.status == FetchStatus.RATE_LIMITED for fetch in fetch_rows
        ),
        "local_rate_limited_pages": sum(
            any(attempt.level == "local_rate_limit" for attempt in fetch.attempts)
            for fetch in fetch_rows
        ),
        "network_requests": network_requests,
        "local_rate_limit_wait_ms": sum(
            attempt.rate_limit_wait_ms
            for fetch in fetch_rows
            for attempt in fetch.attempts
        ),
        "cache_hits": cache_hits,
        "cache_misses": sum(
            fetch.cache_status in {"MISS", "STALE", "INVALID", "REFRESH"}
            for fetch in fetch_rows
        ),
        "cache_hit_rate": round(cache_hits / max(len(fetch_rows), 1), 4),
        "browser_fallback_rate": round(
            sum(fetch.browser_fallback_required for fetch in fetch_rows)
            / max(len(fetch_rows), 1),
            4,
        ),
        "parser_successes": sum(
            document.get("validation", {}).get("valid") is True
            for document in document_rows
        ),
        "deckstrings_found": len(all_decks),
        "invalid_deckstrings": sum(not deck.get("valid", False) for deck in all_decks),
        "unique_decks": len(set(fingerprints)),
        "duplicate_decks": len(fingerprints) - len(set(fingerprints)),
        "classifications": dict(classes),
        "provenance_rate": round(attributed / max(len(document_rows), 1), 4),
        "average_credits_per_document": round(
            sum(credits) / max(len(document_rows), 1), 4
        ),
        "unattributed_cost_attempts": sum(
            attempt.request_cost is None
            for fetch in fetch_rows
            for attempt in fetch.attempts
        ),
    }


def site_health(fetches: Iterable[FetchResult]) -> dict[str, Any]:
    grouped: dict[str, list[FetchResult]] = defaultdict(list)
    for fetch in fetches:
        grouped[fetch.profile].append(fetch)
    return {
        profile: {
            "status": rows[-1].status.value,
            "last_checked_at": rows[-1].fetched_at,
            "last_good_at": next(
                (
                    row.fetched_at
                    for row in reversed(rows)
                    if row.status == FetchStatus.SUCCESS
                ),
                None,
            ),
            "healthy": rows[-1].status == FetchStatus.SUCCESS,
        }
        for profile, rows in sorted(grouped.items())
    }


def inspect_document(
    raw: str,
    *,
    source_url: str,
    profile: SourceProfile,
    content_type: str = "text/html",
    western_deck: Deck | None = None,
    western_match_checked: bool = False,
) -> dict[str, Any]:
    validation = validate_content(raw, profile, content_type=content_type)
    clean_text = validation.clean_text
    deck_records = extract_deck_records(clean_text)
    decks = [deck.as_dict() for deck in extract_deckstrings(clean_text)]
    stats = extract_cn_stats(clean_text)
    provenance = extract_provenance(clean_text)
    page_metadata = extract_page_metadata(raw, clean_text, validation.title)
    comparison = None
    if western_deck and decks and decks[0]["valid"]:
        comparison = compare_decks(
            western_deck.cards,
            {int(key): value for key, value in decks[0]["cards"].items()},
        )
    classification = classify_cn_deck(
        clean_text,
        stats,
        provenance,
        western_match_checked=western_match_checked,
        comparison=comparison,
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    source_id = hashlib.sha256(canonical_url(source_url).encode()).hexdigest()[:16]
    observed_at = utc_now()
    for record in deck_records:
        record_stats = CNStats(**record["statistics"])
        record_comparison = comparison if record["index"] == 1 else None
        record_classification = classify_cn_deck(
            clean_text,
            record_stats,
            provenance,
            western_match_checked=western_match_checked,
            comparison=record_comparison,
        )
        fingerprint = record["deck"].get("fingerprint") or record["deck"].get(
            "deckstring", ""
        )
        record["record_id"] = hashlib.sha256(
            f"{source_id}|{fingerprint}|{record['context_hash']}".encode()
        ).hexdigest()[:20]
        record["source_id"] = source_id
        record["classification"] = {
            "label": record_classification.label.value,
            "confidence": record_classification.confidence,
            "signals": record_classification.signals,
            "comparison": record_classification.comparison,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "source": profile.key,
        "source_id": source_id,
        "source_url": canonical_url(source_url),
        "fetched_at": observed_at,
        "language": "zh-CN",
        "title": validation.title,
        "author": provenance.original_author or page_metadata.author,
        "publisher": page_metadata.publisher,
        "published_at": page_metadata.published_at,
        "modified_at": page_metadata.modified_at,
        "page_metadata": asdict(page_metadata),
        "content_hash": digest,
        "validation": {
            "valid": validation.valid,
            "status": validation.status.value,
            "reasons": validation.reasons,
        },
        "clean_text_zh": clean_text,
        "decks": decks,
        "deck_records": deck_records,
        "statistics": asdict(stats),
        "provenance": asdict(provenance),
        "classification": {
            "label": classification.label.value,
            "confidence": classification.confidence,
            "signals": classification.signals,
            "comparison": classification.comparison,
        },
        "source_type": source_type_for(profile, classification.label),
        "terminology_matches": {
            term: meaning
            for term, meaning in CN_HEARTHSTONE_TERMS.items()
            if term in clean_text
        },
        "deduplication": {
            "canonical_url_key": hashlib.sha256(
                canonical_url(source_url).encode()
            ).hexdigest(),
            "content_hash": digest,
            "lineage_hint": provenance.attribution_url or canonical_url(source_url),
            "earliest_observed_source": {
                "url": canonical_url(source_url),
                "observed_at": observed_at,
                "scope": "crawler_observation_only",
            },
        },
    }


def load_config(path: Path | None) -> dict[str, Any]:
    config = {
        "score_weights": DEFAULT_SCORE_WEIGHTS.copy(),
        "fetch": {
            "timeout_seconds": 60,
            "max_attempts_per_level": 1,
            "requests_per_minute": DEFAULT_REQUESTS_PER_MINUTE,
            "max_rate_wait_seconds": DEFAULT_MAX_RATE_WAIT_SECONDS,
            "cache_enabled": True,
            "cache_directory": None,
            "cache_ttl_seconds": None,
        },
        "sources": {
            key: {"poll_minutes": profile.poll_minutes, "enabled": True}
            for key, profile in SOURCE_PROFILES.items()
        },
    }
    if path is None:
        return config
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("Config root must be an object.")
    if isinstance(payload.get("score_weights"), dict):
        config["score_weights"].update(payload["score_weights"])
        cn_deck_score({}, config["score_weights"])
    if isinstance(payload.get("fetch"), dict):
        config["fetch"].update(payload["fetch"])
    if isinstance(payload.get("sources"), dict):
        for key, value in payload["sources"].items():
            if key not in SOURCE_PROFILES:
                raise ValueError(f"Unknown source in config: {key}")
            if isinstance(value, dict):
                config["sources"][key].update(value)
    return config


def doctor() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "scrape_do": {
            "configured": bool(os.environ.get(SCRAPE_DO_TOKEN_ENV, "").strip()),
            "credential_env": SCRAPE_DO_TOKEN_ENV,
            "escalation": [level.name for level in ESCALATION_LEVELS],
            "local_rate_limit_per_minute": DEFAULT_REQUESTS_PER_MINUTE,
            "max_local_rate_wait_seconds": DEFAULT_MAX_RATE_WAIT_SECONDS,
            "cache_default": "enabled",
            "cache_credential_content": False,
        },
        "koloda_card_database": {
            "base_url": KHS_BASE_URL,
            "public_reads_available_without_token": True,
            "token_configured": bool(os.environ.get(KHS_TOKEN_ENV, "").strip()),
            "credential_env": KHS_TOKEN_ENV,
        },
        "sources": {
            key: {
                "display_name": profile.display_name,
                "poll_minutes": profile.poll_minutes,
                "domains": profile.domains,
            }
            for key, profile in SOURCE_PROFILES.items()
        },
    }


def _write_json(payload: Any, output: Path | None = None) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Report configuration without secret values.")
    subparsers.add_parser("profiles", help="List Chinese source profiles.")

    inspect_parser = subparsers.add_parser(
        "inspect", help="Inspect saved HTML or JSON offline."
    )
    inspect_parser.add_argument("--file", type=Path, required=True)
    inspect_parser.add_argument("--url", required=True)
    inspect_parser.add_argument("--source", choices=sorted(SOURCE_PROFILES))
    inspect_parser.add_argument("--content-type", default="text/html")
    inspect_parser.add_argument("--western-deckstring")
    inspect_parser.add_argument("--western-match-checked", action="store_true")
    inspect_parser.add_argument("--output", type=Path)

    fetch_parser = subparsers.add_parser(
        "fetch", help="Fetch one public source through Scrape.do."
    )
    fetch_parser.add_argument("--url", required=True)
    fetch_parser.add_argument("--source", choices=sorted(SOURCE_PROFILES))
    fetch_parser.add_argument("--config", type=Path)
    fetch_parser.add_argument("--output", type=Path)
    fetch_parser.add_argument("--include-raw", action="store_true")
    fetch_parser.add_argument("--resolve-cards", action="store_true")
    fetch_parser.add_argument(
        "--refresh", action="store_true", help="Bypass a fresh cache entry."
    )
    fetch_parser.add_argument(
        "--no-cache", action="store_true", help="Disable cache reads and writes."
    )

    deck_parser = subparsers.add_parser(
        "deck", help="Decode and optionally resolve one deckstring."
    )
    deck_parser.add_argument("deckstring")
    deck_parser.add_argument("--resolve-cards", action="store_true")
    deck_parser.add_argument("--output", type=Path)

    query_parser = subparsers.add_parser(
        "guide-queries", help="Build localized GuideHunter queries."
    )
    group = query_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--deckstring")
    group.add_argument("--archetype")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            _write_json(doctor())
            return 0
        if args.command == "profiles":
            _write_json(doctor()["sources"])
            return 0
        if args.command == "guide-queries":
            _write_json(
                {"queries": build_guide_queries(args.deckstring, args.archetype)}
            )
            return 0
        if args.command == "deck":
            deck = decode_deckstring(args.deckstring)
            result: dict[str, Any] = {"deck": deck.as_dict()}
            if args.resolve_cards:
                result["card_database"] = KolodaCardDatabase().resolve_deck(deck)
            _write_json(result, args.output)
            return 0 if deck.valid else 2
        if args.command == "inspect":
            raw = args.file.read_text(encoding="utf-8")
            profile = profile_for(args.source, args.url)
            western = (
                decode_deckstring(args.western_deckstring)
                if args.western_deckstring
                else None
            )
            result = inspect_document(
                raw,
                source_url=args.url,
                profile=profile,
                content_type=args.content_type,
                western_deck=western,
                western_match_checked=args.western_match_checked,
            )
            _write_json(result, args.output)
            return 0 if result["validation"]["valid"] else 2
        if args.command == "fetch":
            profile = profile_for(args.source, args.url)
            config = load_config(args.config)
            fetch_config = config["fetch"]
            cache_enabled = bool(fetch_config["cache_enabled"]) and not args.no_cache
            configured_directory = fetch_config.get("cache_directory")
            runtime_directory = (
                Path(str(configured_directory)).expanduser()
                if configured_directory
                else default_runtime_dir()
            )
            client = ScrapeDoClient(
                timeout=float(fetch_config["timeout_seconds"]),
                max_attempts_per_level=int(fetch_config["max_attempts_per_level"]),
                max_rate_wait=float(fetch_config["max_rate_wait_seconds"]),
                rate_limiter=SlidingWindowRateLimiter(
                    int(fetch_config["requests_per_minute"]),
                    state_dir=runtime_directory,
                ),
                cache=FetchCache(runtime_directory / "responses")
                if cache_enabled
                else None,
                cache_ttl_seconds=(
                    float(fetch_config["cache_ttl_seconds"])
                    if fetch_config.get("cache_ttl_seconds") is not None
                    else None
                ),
                refresh=args.refresh,
            )
            fetched = client.fetch(args.url, profile)
            result: dict[str, Any] = {"fetch": fetched.public_dict(args.include_raw)}
            if fetched.status == FetchStatus.SUCCESS and fetched.body is not None:
                document = inspect_document(
                    fetched.body,
                    source_url=fetched.resolved_url or fetched.requested_url,
                    profile=profile,
                    content_type=fetched.content_type or "text/html",
                )
                if args.resolve_cards:
                    resolver = KolodaCardDatabase()
                    document["card_database"] = [
                        resolver.resolve_deck(
                            Deck(
                                deckstring=deck["deckstring"],
                                format_id=deck["format_id"],
                                heroes=deck["heroes"],
                                cards={
                                    int(key): value
                                    for key, value in deck["cards"].items()
                                },
                                sideboards=[
                                    tuple(item) for item in deck["sideboards"]
                                ],
                                valid=deck["valid"],
                                validation_errors=deck["validation_errors"],
                                cards_total=deck["cards_total"],
                                fingerprint=deck["fingerprint"],
                                validation_warnings=deck.get(
                                    "validation_warnings", []
                                ),
                                deck_size_status=deck.get(
                                    "deck_size_status", "EXPECTED"
                                ),
                            )
                        )
                        for deck in document["decks"]
                        if deck["valid"]
                    ]
                result["document"] = document
            _write_json(result, args.output)
            return 0 if fetched.status == FetchStatus.SUCCESS else 2
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
