#!/usr/bin/env python3
"""Read-only adapters for RedditAPI, GetXAPI, TinyFish, and TranscriptAPI.

The adapters normalize discovery data into a small provider-neutral envelope.
Credentials are read from the environment or managed by the TinyFish CLI and
are never included in output.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None


SCHEMA_VERSION = "1.0"
REDDIT_BASE_URL = "https://api.redditapis.com"
GETX_BASE_URL = "https://api.getxapi.com"
TRANSCRIPTAPI_BASE_URL = "https://api.transcriptapi.io"
REDDIT_KEY_ENV = "REDDITAPIS_KEY"
GETX_KEY_ENV = "GETXAPI_KEY"
TRANSCRIPTAPI_KEY_ENV = "TRANSCRIPTAPI_TOKEN"
TRANSCRIPTAPI_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})
TRANSCRIPTAPI_MAX_RETRY_DELAY_SECONDS = 5.0
TINYFISH_KEY_ENV = "TINYFISH_API_KEY"
TINYFISH_SEARCH_URL = "https://api.search.tinyfish.ai"
TINYFISH_FETCH_URL = "https://api.fetch.tinyfish.ai"
TINYFISH_SEARCH_LIMIT = 30
TINYFISH_FETCH_URL_LIMIT = 150
STATS_API_BASE_URL = os.environ.get(
    "HEARTHSTONE_STATS_API_URL",
    "https://api.kolodahearthstone.com/v1",
).strip().rstrip("/")
STATS_API_DATASET_BASE_URL = (
    STATS_API_BASE_URL.removesuffix("/v1")
    if STATS_API_BASE_URL.endswith("/v1")
    else STATS_API_BASE_URL
)
STATS_API_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
STATS_API_TIMEOUT_SECONDS = 20.0
STATS_API_PATHS = {
    "health": "/health",
    "sources": "/sources",
    "datasets": "/datasets",
    "dataset": "/datasets/{source_id}",
    "constructed-decks": "/constructed/decks",
    "constructed-archetypes": "/constructed/archetypes",
    "hsguru-meta": "/hsguru/meta",
    "battlegrounds-heroes": "/battlegrounds/heroes",
    "battlegrounds-minions": "/battlegrounds/minions",
    "arena-classes": "/arena/classes",
    "parsing-reliability": "/system/parsing-reliability",
}
STATS_API_SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
RATE_WINDOW_SECONDS = 60
MAX_PROVIDER_RESPONSE_BYTES = 10_000_000


class ProviderError(RuntimeError):
    """A safe provider error that never contains credentials."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        status: int | None = None,
        retry_after: str | None = None,
        provider_code: str | None = None,
        retryable: bool | None = None,
        credits_refunded: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.retry_after = retry_after
        self.provider_code = provider_code
        self.retryable = retryable
        self.credits_refunded = credits_refunded

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "provider": self.provider,
            "message": str(self),
        }
        if self.status is not None:
            result["status"] = self.status
        if self.retry_after:
            result["retry_after"] = self.retry_after
        if self.provider_code:
            result["provider_code"] = self.provider_code
        if self.retryable is not None:
            result["retryable"] = self.retryable
        if self.credits_refunded is not None:
            result["credits_refunded"] = self.credits_refunded
        return result


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def iso_from_epoch(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
    except (TypeError, ValueError, OSError):
        return None


def normalize_datetime(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return iso_from_epoch(value)
    text = str(value)
    if text.endswith("Z") or "T" in text:
        return text
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def envelope(
    provider: str,
    operation: str,
    query_context: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    pagination: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": provider,
        "operation": operation,
        "collected_at": utc_now(),
        "query_context": query_context,
        "results": results,
        "pagination": pagination or {},
        "warnings": warnings or [],
    }


def require_key(name: str, provider: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ProviderError(
            provider,
            f"Credential is not configured. Set {name} in the local environment.",
        )
    return value


def get_json(
    provider: str,
    base_url: str,
    path: str,
    params: dict[str, Any],
    key_env: str,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    key = require_key(key_env, provider)
    clean_params = {key: value for key, value in params.items() if value not in (None, "")}
    url = f"{base_url}{path}"
    if clean_params:
        url = f"{url}?{urlencode(clean_params)}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "deep-research-community-sources/1.0",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ProviderError(
            provider,
            f"Provider returned HTTP {exc.code}.",
            status=exc.code,
            retry_after=exc.headers.get("Retry-After"),
        ) from exc
    except URLError as exc:
        raise ProviderError(provider, "Provider request failed.") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError(provider, "Provider returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise ProviderError(provider, "Provider returned an unexpected response shape.")
    return payload


JsonTransport = Callable[[Request, float], tuple[int, Mapping[str, str], bytes]]


def _urllib_json_transport(
    request: Request, timeout: float
) -> tuple[int, Mapping[str, str], bytes]:
    try:
        with urlopen(request, timeout=timeout) as response:
            return (
                response.status,
                response.headers,
                response.read(MAX_PROVIDER_RESPONSE_BYTES + 1),
            )
    except HTTPError as exc:
        return exc.code, exc.headers, exc.read(MAX_PROVIDER_RESPONSE_BYTES + 1)


def _transcriptapi_retry_delay(
    headers: Mapping[str, str], attempt: int
) -> float:
    retry_after = next(
        (
            str(value).strip()
            for name, value in headers.items()
            if str(name).lower() == "retry-after"
        ),
        "",
    )
    if re.fullmatch(r"\d+(?:\.\d+)?", retry_after):
        return min(
            TRANSCRIPTAPI_MAX_RETRY_DELAY_SECONDS,
            max(0.1, float(retry_after)),
        )
    return 1.5 * (attempt + 1)


def transcriptapi_get_json(
    path: str,
    params: dict[str, Any],
    *,
    timeout: float = 60.0,
    max_attempts: int = 2,
    transport: JsonTransport = _urllib_json_transport,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Call one read-only TranscriptAPI endpoint with one bounded retry."""

    key = require_key(TRANSCRIPTAPI_KEY_ENV, "transcriptapi")
    clean_params = {
        name: value for name, value in params.items() if value not in (None, "")
    }
    target = f"{TRANSCRIPTAPI_BASE_URL}{path}"
    if clean_params:
        target = f"{target}?{urlencode(clean_params)}"
    request = Request(
        target,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "deep-research-youtube/1.0",
        },
        method="GET",
    )
    attempts = max(1, min(max_attempts, 2))
    for attempt in range(attempts):
        try:
            status, headers, body = transport(request, timeout)
        except (URLError, TimeoutError, OSError) as exc:
            if attempt + 1 < attempts:
                sleep(1.5 * (attempt + 1))
                continue
            raise ProviderError(
                "transcriptapi",
                "Provider request failed after a bounded retry.",
                retryable=True,
            ) from exc
        if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
            raise ProviderError(
                "transcriptapi",
                "Provider response exceeded the configured size limit.",
                status=status,
            )
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderError(
                "transcriptapi", "Provider returned invalid JSON.", status=status
            ) from exc
        if 200 <= status < 300:
            if not isinstance(payload, dict):
                raise ProviderError(
                    "transcriptapi",
                    "Provider returned an unexpected response shape.",
                    status=status,
                )
            return payload
        error = payload if isinstance(payload, dict) else {}
        retryable_value = error.get("retryable")
        retryable = retryable_value if isinstance(retryable_value, bool) else None
        if (
            status in TRANSCRIPTAPI_TRANSIENT_STATUSES
            and retryable is not False
            and attempt + 1 < attempts
        ):
            sleep(_transcriptapi_retry_delay(headers, attempt))
            continue
        retry_after = next(
            (
                str(value)
                for name, value in headers.items()
                if str(name).lower() == "retry-after"
            ),
            None,
        )
        raise ProviderError(
            "transcriptapi",
            f"Provider returned HTTP {status}.",
            status=status,
            retry_after=retry_after,
            provider_code=str(error.get("error")) if error.get("error") else None,
            retryable=retryable,
            credits_refunded=(
                bool(error["credits_refunded"])
                if isinstance(error.get("credits_refunded"), bool)
                else None
            ),
        )
    raise ProviderError("transcriptapi", "Provider request failed.")
def stats_api_query_params(operation: str, params: dict[str, Any]) -> dict[str, Any]:
    """Translate adapter options to the exact query contract of each API route."""

    clean_params = {
        key: value for key, value in params.items() if value not in (None, "")
    }
    if operation == "dataset":
        return {}
    if operation != "hsguru-meta":
        return clean_params

    source_id = str(clean_params.get("source_id") or "")
    if source_id.startswith("hsguru_meta_"):
        source_parts = source_id.removeprefix("hsguru_meta_").split("_")
        if len(source_parts) >= 2:
            clean_params.setdefault("format", source_parts[0])
            clean_params.setdefault("rank", "_".join(source_parts[1:]))

    translated: dict[str, Any] = {}
    for source_name, api_name in (
        ("format_name", "format"),
        ("rank_range", "rank"),
        ("period", "period"),
        ("min_games", "min_games"),
    ):
        if clean_params.get(source_name) is not None:
            translated[api_name] = clean_params[source_name]
    if clean_params.get("format") is not None:
        translated["format"] = clean_params["format"]
    if clean_params.get("rank") is not None:
        translated["rank"] = clean_params["rank"]
    return translated


def reddit_flags(post: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    author = str(post.get("author") or "").lower()
    searchable = f"{post.get('title', '')} {post.get('text', '')}".lower()
    if author in {"automoderator", "modteam"}:
        flags.append("automated")
    if any(term in searchable for term in ("giveaway", "give-away", "розыгрыш")):
        flags.append("giveaway")
    for field, label in (
        ("is_crosspost", "crosspost"),
        ("stickied", "stickied"),
        ("locked", "locked"),
        ("over_18", "nsfw"),
    ):
        if post.get(field):
            flags.append(label)
    return flags


def normalize_reddit_post(
    post: dict[str, Any], position: int, rank_kind: str
) -> dict[str, Any]:
    published_at = normalize_datetime(post.get("created")) or iso_from_epoch(
        post.get("created_utc")
    )
    source_url = post.get("url")
    if not source_url and post.get("permalink"):
        source_url = f"https://www.reddit.com{post['permalink']}"
    return {
        "platform": "reddit",
        "source_kind": "post",
        "source_id": post.get("id"),
        "source_url": source_url,
        "author": post.get("author"),
        "community": post.get("subreddit"),
        "title": post.get("title"),
        "text": post.get("text") or "",
        "published_at": published_at,
        "metrics": {
            "score": post.get("upvotes"),
            "comments": post.get("comments"),
            "upvote_ratio": post.get("upvote_ratio"),
        },
        "provider_position": position,
        "provider_rank_kind": rank_kind,
        "classification_flags": reddit_flags(post),
    }


def normalize_reddit_posts(
    payload: dict[str, Any], operation: str, query_context: dict[str, Any]
) -> dict[str, Any]:
    posts = payload.get("posts")
    if not isinstance(posts, list):
        posts = []
    rank_kind = str(query_context.get("sort") or "provider_order")
    results = [
        normalize_reddit_post(post, position, rank_kind)
        for position, post in enumerate(posts, start=1)
        if isinstance(post, dict)
    ]
    warnings = [
        "Engagement is contextual metadata, not proof of truth or population prevalence.",
        "Review automated, giveaway, stickied, and crosspost flags before trend synthesis.",
    ]
    status = payload.get("listing_status")
    if status in {"truncated", "unknown"}:
        warnings.append(f"Reddit listing coverage is partial: {status}.")
    return envelope(
        "redditapi",
        operation,
        query_context,
        results,
        pagination={
            "next_cursor": payload.get("after"),
            "listing_status": status,
            "exhausted_reason": payload.get("exhausted_reason"),
        },
        warnings=warnings,
    )


def iter_reddit_nodes(nodes: Any, depth: int = 0):
    if not isinstance(nodes, list):
        return
    for node in nodes:
        if not isinstance(node, dict):
            continue
        kind = node.get("kind")
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        yield kind, data, depth
        replies = data.get("replies")
        if isinstance(replies, dict):
            children = replies.get("data", {}).get("children", [])
            yield from iter_reddit_nodes(children, depth + 1)
        elif isinstance(replies, list):
            yield from iter_reddit_nodes(replies, depth + 1)


def normalize_reddit_comments(
    payload: dict[str, Any], post_id: str
) -> dict[str, Any]:
    comments: list[dict[str, Any]] = []
    hidden_count = 0
    for kind, data, depth in iter_reddit_nodes(payload.get("comments", [])):
        if kind == "more":
            hidden_count += int(data.get("count") or len(data.get("children") or []))
            continue
        if kind != "t1":
            continue
        comment_id = data.get("id")
        comments.append(
            {
                "platform": "reddit",
                "source_kind": "comment",
                "source_id": comment_id,
                "source_url": (
                    f"https://www.reddit.com/comments/{post_id}/comment/{comment_id}/"
                    if comment_id
                    else None
                ),
                "author": data.get("author"),
                "community": data.get("subreddit"),
                "text": data.get("body") or "",
                "published_at": iso_from_epoch(data.get("created_utc")),
                "metrics": {"score": data.get("score", data.get("ups"))},
                "thread": {
                    "post_id": post_id,
                    "parent_id": data.get("parent_id"),
                    "depth": depth,
                },
            }
        )
    warnings = [
        "Comment trees are convenience samples; score and repetition do not establish prevalence."
    ]
    if hidden_count:
        warnings.append(f"The response contains placeholders for at least {hidden_count} comments.")
    if payload.get("listing_status") in {"truncated", "unknown"}:
        warnings.append("The provider does not establish that the comment tree is complete.")
    return envelope(
        "redditapi",
        "comments",
        {"post_id": post_id},
        comments,
        pagination={
            "listing_status": payload.get("listing_status"),
            "hidden_comment_count": hidden_count,
        },
        warnings=warnings,
    )


def normalize_x_tweet(
    tweet: dict[str, Any], position: int, product: str
) -> dict[str, Any]:
    author = tweet.get("author") if isinstance(tweet.get("author"), dict) else {}
    return {
        "platform": "x",
        "source_kind": "post",
        "source_id": tweet.get("id"),
        "source_url": tweet.get("url") or tweet.get("twitterUrl"),
        "author": {
            "id": author.get("id"),
            "username": author.get("userName"),
            "name": author.get("name"),
            "verified": bool(author.get("isVerified") or author.get("isBlueVerified")),
            "followers": author.get("followers"),
        },
        "text": tweet.get("text") or "",
        "published_at": normalize_datetime(tweet.get("createdAt")),
        "language": tweet.get("lang"),
        "metrics": {
            "likes": tweet.get("likeCount"),
            "replies": tweet.get("replyCount"),
            "reposts": tweet.get("retweetCount"),
            "quotes": tweet.get("quoteCount"),
            "views": tweet.get("viewCount"),
            "bookmarks": tweet.get("bookmarkCount"),
        },
        "provider_position": position,
        "provider_rank_kind": product.lower(),
        "classification_flags": ["reply"] if tweet.get("isReply") else [],
    }


def normalize_x_search(
    payload: dict[str, Any], query: str, product: str, cursor: str | None = None
) -> dict[str, Any]:
    tweets = payload.get("tweets")
    if not isinstance(tweets, list):
        tweets = []
    results = [
        normalize_x_tweet(tweet, position, product)
        for position, tweet in enumerate(tweets, start=1)
        if isinstance(tweet, dict)
    ]
    warnings = [
        "Top is provider relevance order, not a guaranteed engagement ranking.",
        "Engagement values are observations at collection time and are not proof of truth or prevalence.",
        "GetXAPI is a third-party service, not the official X API.",
    ]
    return envelope(
        "getxapi",
        "advanced_search",
        {"query": query, "product": product, "cursor": cursor},
        results,
        pagination={
            "has_more": payload.get("has_more"),
            "next_cursor": payload.get("next_cursor"),
        },
        warnings=warnings,
    )


YOUTUBE_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_video_id(value: str) -> str:
    """Normalize a bare YouTube id or a common public video URL."""

    candidate = value.strip()
    if YOUTUBE_VIDEO_ID_RE.fullmatch(candidate):
        return candidate
    parts = urlsplit(candidate)
    host = (parts.hostname or "").lower().removeprefix("www.")
    video_id: str | None = None
    if host == "youtu.be":
        video_id = parts.path.strip("/").split("/", 1)[0]
    elif host in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parts.path.rstrip("/") == "/watch":
            video_id = (parse_qs(parts.query).get("v") or [None])[0]
        else:
            path_parts = parts.path.strip("/").split("/")
            if len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed", "live"}:
                video_id = path_parts[1]
    if not video_id or not YOUTUBE_VIDEO_ID_RE.fullmatch(video_id):
        raise ProviderError(
            "transcriptapi", "Expected a YouTube video URL or 11-character video id."
        )
    return video_id


def youtube_url(video_id: str, start: float | None = None) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    if start is not None:
        url = f"{url}&t={max(0, int(start))}s"
    return url


def parse_display_views(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip().upper().replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*([KMB])?", text)
    if not match:
        return None
    multiplier = {None: 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    return int(float(match.group(1)) * multiplier[match.group(2)])


def parse_display_duration(value: Any) -> int | None:
    if value in (None, ""):
        return None
    parts = str(value).strip().split(":")
    if not 1 <= len(parts) <= 3 or any(not part.isdigit() for part in parts):
        return None
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total


def normalize_youtube_search(
    payload: dict[str, Any],
    query: str,
    limit: int,
    *,
    channel_id: str | None = None,
) -> dict[str, Any]:
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raw_results = []
    results: list[dict[str, Any]] = []
    for position, item in enumerate(raw_results, start=1):
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id") or "")
        if not YOUTUBE_VIDEO_ID_RE.fullmatch(raw_id):
            continue
        results.append(
            {
                "platform": "youtube",
                "source_kind": "video_search_result",
                "source_id": raw_id,
                "source_url": youtube_url(raw_id),
                "title": item.get("title"),
                "channel": item.get("channel"),
                "metrics": {
                    "views": parse_display_views(item.get("views")),
                    "views_display": item.get("views"),
                    "duration_seconds": parse_display_duration(item.get("duration")),
                    "duration_display": item.get("duration"),
                },
                "provider_position": position,
                "provider_rank_kind": "search_relevance",
                "expertise": {
                    "status": "channel_scoped_unverified"
                    if channel_id
                    else "unverified",
                    "channel_id": channel_id,
                    "rule": "Verify professional role independently; views and channel name are insufficient.",
                },
                "evidence_status": "discovery_only",
            }
        )
    return envelope(
        "transcriptapi",
        "youtube_channel_search" if channel_id else "youtube_search",
        {"query": query, "limit": limit, "channel_id": channel_id},
        results,
        warnings=[
            "Search position is provider relevance, not quality, expertise, or popularity.",
            "Search results omit an exact publication timestamp; verify freshness on the YouTube page.",
            "A channel or view count does not establish professional-player status.",
            "Search records are discovery_only until the video and relevant transcript segment are inspected.",
            "TranscriptAPI is a third-party YouTube access provider.",
        ],
    )


def transcript_windows(
    segments: list[dict[str, Any]], span_seconds: float = 30.0
) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    window_start = 0.0
    for segment in segments:
        start = float(segment["start"])
        if current and start >= window_start + span_seconds:
            windows.append(_transcript_window(current))
            current = []
        if not current:
            window_start = start
        current.append(segment)
    if current:
        windows.append(_transcript_window(current))
    return windows


def _transcript_window(segments: list[dict[str, Any]]) -> dict[str, Any]:
    start = float(segments[0]["start"])
    end = max(float(segment["end"]) for segment in segments)
    video_id = str(segments[0]["video_id"])
    return {
        "start": start,
        "end": round(end, 2),
        "text": " ".join(str(segment["text"]).strip() for segment in segments).strip(),
        "timestamp_url": youtube_url(video_id, start),
        "segment_count": len(segments),
    }


def normalize_youtube_transcript(
    payload: dict[str, Any],
    video_id: str,
    *,
    language: str | None = None,
    translate_to: str | None = None,
    provider: str = "transcriptapi",
    operation: str = "youtube_transcript",
    extra_warnings: list[str] | None = None,
) -> dict[str, Any]:
    raw_segments = payload.get("transcript")
    if not isinstance(raw_segments, list):
        raw_segments = []
    segments: list[dict[str, Any]] = []
    for item in raw_segments:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        try:
            start = max(0.0, float(item.get("start", 0.0)))
            duration = max(0.0, float(item.get("duration", 0.0)))
        except (TypeError, ValueError):
            continue
        segments.append(
            {
                "video_id": video_id,
                "start": round(start, 2),
                "duration": round(duration, 2),
                "end": round(start + duration, 2),
                "text": item["text"],
                "timestamp_url": youtube_url(video_id, start),
            }
        )
    digest = hashlib.sha256(
        json.dumps(segments, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    result = {
        "platform": "youtube",
        "source_kind": "video_transcript",
        "caption_provider": provider,
        "source_id": video_id,
        "source_url": youtube_url(video_id),
        "language_requested": language,
        "translated_to": payload.get("translated_to") or translate_to,
        "segments": segments,
        "evidence_windows": transcript_windows(segments),
        "segment_count": len(segments),
        "content_hash": digest,
        "evidence_status": "inspect_segments_before_claim",
    }
    warnings = [
        "Captions may be auto-generated and can misrecognize names, game terms, numbers, or negation.",
        "Use timestamped segments as locators; verify consequential claims against the video context.",
        "A transcript records what was said, not whether the statement is correct or current.",
        "Do not reproduce a full transcript in the final answer; quote minimally and cite the video timestamp.",
    ]
    if translate_to:
        warnings.append(
            "Provider translation was requested and may consume additional credits; retain the original-language evidence when available."
        )
    warnings.extend(extra_warnings or [])
    return envelope(
        provider,
        operation,
        {
            "video_id": video_id,
            "language": language,
            "translate_to": translate_to,
        },
        [result],
        warnings=warnings,
    )


PublicCaptionFetcher = Callable[
    [str, list[str] | None], tuple[list[dict[str, Any]], dict[str, Any]]
]


def _youtube_transcript_api_fetch(
    video_id: str, languages: list[str] | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read a public caption track through the optional youtube-transcript-api."""

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:  # pragma: no cover - exercised through doctor/tests
        raise ProviderError(
            "youtube_public_captions",
            "Optional dependency is unavailable. Run with `uv run --with youtube-transcript-api` or install youtube-transcript-api locally.",
        ) from exc
    try:
        transcript = YouTubeTranscriptApi().fetch(video_id, languages=languages)
        rows = transcript.to_raw_data()
    except Exception as exc:  # library exceptions vary by release
        raise ProviderError(
            "youtube_public_captions",
            "Public YouTube captions are unavailable for this video.",
        ) from exc
    metadata = {
        "language_code": getattr(transcript, "language_code", None),
        "language": getattr(transcript, "language", None),
        "is_generated": getattr(transcript, "is_generated", None),
    }
    return rows if isinstance(rows, list) else [], metadata


def public_youtube_transcript(
    video_id: str,
    *,
    language: str | None = None,
    fetcher: PublicCaptionFetcher = _youtube_transcript_api_fetch,
) -> dict[str, Any]:
    """Explicit reserve path for public captions when TranscriptAPI is unavailable."""

    languages = [language] if language else None
    try:
        rows, metadata = fetcher(video_id, languages)
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(
            "youtube_public_captions",
            "Public YouTube caption retrieval failed.",
        ) from exc
    payload = {"transcript": rows}
    normalized = normalize_youtube_transcript(
        payload,
        video_id,
        language=language,
        provider="youtube_public_captions",
        operation="youtube_public_transcript",
        extra_warnings=[
            "This is an explicit reserve route, not a hidden replacement for TranscriptAPI; record the primary-provider gap.",
            "Public caption access is unofficial and can stop working or be blocked independently of the YouTube page.",
        ],
    )
    if normalized["results"]:
        normalized["results"][0]["caption_track"] = metadata
        normalized["results"][0]["fallback_role"] = "explicit_reserve"
    normalized["query_context"]["fallback_role"] = "explicit_reserve"
    return normalized


def default_cache_dir() -> Path:
    configured = os.environ.get("DEEP_RESEARCH_CACHE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "deep-research"


def reserve_rate_capacity(
    bucket: str,
    units: int,
    limit: int,
    *,
    cache_dir: Path | None = None,
    now: float | None = None,
) -> None:
    """Reserve units in a local sliding-window limiter without waiting."""

    if units < 1 or units > limit:
        raise ProviderError("tinyfish", "Requested unit count exceeds the local rate limit.")
    timestamp = time.time() if now is None else now
    directory = cache_dir or default_cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / f"{bucket}-rate.json"
    lock_path = directory / f"{bucket}-rate.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            try:
                raw = json.loads(state_path.read_text(encoding="utf-8"))
                events = [float(value) for value in raw if float(value) > timestamp - RATE_WINDOW_SECONDS]
            except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
                events = []
            if len(events) + units > limit:
                retry_after = max(1, int(RATE_WINDOW_SECONDS - (timestamp - min(events)) + 1))
                raise ProviderError(
                    "tinyfish",
                    "Local TinyFish rate limit reached; retry later.",
                    status=429,
                    retry_after=str(retry_after),
                )
            events.extend([timestamp] * units)
            state_path.write_text(json.dumps(events), encoding="utf-8")
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def run_tinyfish(arguments: list[str], operation: str) -> dict[str, Any]:
    executable = shutil.which("tinyfish")
    if not executable:
        raise ProviderError("tinyfish", "TinyFish CLI is not installed or is not on PATH.")
    try:
        result = subprocess.run(
            [executable, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderError("tinyfish", f"TinyFish {operation} timed out.") from exc
    if result.returncode != 0:
        raise ProviderError("tinyfish", f"TinyFish {operation} failed.")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProviderError("tinyfish", "TinyFish returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise ProviderError("tinyfish", "TinyFish returned an unexpected response shape.")
    return payload


def tinyfish_request(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call TinyFish REST APIs without putting the key in an argument or URL."""

    key = require_key(TINYFISH_KEY_ENV, "tinyfish")
    if params:
        clean_params = {key: value for key, value in params.items() if value not in (None, "")}
        if clean_params:
            url = f"{url}?{urlencode(clean_params)}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        url,
        data=data,
        headers={
            "X-API-Key": key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urlopen(request, timeout=150.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ProviderError(
            "tinyfish",
            f"TinyFish returned HTTP {exc.code}.",
            status=exc.code,
            retry_after=exc.headers.get("Retry-After"),
        ) from exc
    except URLError as exc:
        raise ProviderError("tinyfish", "TinyFish request failed.") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("tinyfish", "TinyFish returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise ProviderError("tinyfish", "TinyFish returned an unexpected response shape.")
    return payload


def tinyfish_search(
    query: str,
    page: int,
    *,
    location: str | None = None,
    language: str | None = None,
    include_domains: str | None = None,
    exclude_domains: str | None = None,
) -> dict[str, Any]:
    if shutil.which("tinyfish"):
        command = ["search", "query", query]
        for option, value in (
            ("--location", location),
            ("--language", language),
            ("--include-domains", include_domains),
            ("--exclude-domains", exclude_domains),
        ):
            if value:
                command.extend([option, value])
        command.extend(["--page", str(page)])
        return run_tinyfish(command, "search")
    query_parts = [query]
    if include_domains:
        query_parts.extend(f"site:{domain.strip()}" for domain in include_domains.split(",") if domain.strip())
    if exclude_domains:
        query_parts.extend(f"-site:{domain.strip()}" for domain in exclude_domains.split(",") if domain.strip())
    return tinyfish_request(
        "GET",
        TINYFISH_SEARCH_URL,
        params={
            "query": " ".join(query_parts),
            "location": location,
            "language": language,
            "page": page,
        },
    )


def tinyfish_fetch(urls: list[str]) -> dict[str, Any]:
    if shutil.which("tinyfish"):
        return run_tinyfish(["fetch", "content", "get", *urls, "--format", "json"], "fetch")
    return tinyfish_request(
        "POST",
        TINYFISH_FETCH_URL,
        body={"urls": urls, "format": "markdown"},
    )


def stats_api_endpoint(operation: str, params: dict[str, Any]) -> tuple[str, str]:
    """Resolve one fixed public statistics route without accepting arbitrary URLs."""

    path = STATS_API_PATHS.get(operation)
    if path is None:
        raise ProviderError("koloda_stats_api", "Unsupported statistics operation.")
    if operation == "dataset":
        source_id = str(params.get("source_id") or "")
        if not STATS_API_SOURCE_ID_RE.fullmatch(source_id):
            raise ProviderError(
                "koloda_stats_api",
                "Dataset source_id must contain only lowercase letters, digits, underscores or hyphens.",
            )
        path = f"/datasets/{source_id}"
        return f"{STATS_API_DATASET_BASE_URL}{path}", path
    return f"{STATS_API_BASE_URL}{path}", path


def stats_api_request(operation: str, params: dict[str, Any]) -> dict[str, Any]:
    """Read one allowlisted, public statistics endpoint with GET only."""

    url, _path = stats_api_endpoint(operation, params)
    clean_params = stats_api_query_params(operation, params)
    if clean_params:
        url = f"{url}?{urlencode(clean_params)}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "deep-research-koloda-stats/1.0",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=STATS_API_TIMEOUT_SECONDS) as response:
            raw = response.read(STATS_API_MAX_RESPONSE_BYTES + 1)
            if len(raw) > STATS_API_MAX_RESPONSE_BYTES:
                raise ProviderError("koloda_stats_api", "Statistics response is too large.")
            payload = json.loads(raw.decode("utf-8"))
    except ProviderError:
        raise
    except HTTPError as exc:
        raise ProviderError(
            "koloda_stats_api",
            f"Statistics API returned HTTP {exc.code}.",
            status=exc.code,
            retry_after=exc.headers.get("Retry-After"),
        ) from exc
    except URLError as exc:
        raise ProviderError("koloda_stats_api", "Statistics API request failed.") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderError("koloda_stats_api", "Statistics API returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise ProviderError("koloda_stats_api", "Statistics API returned an unexpected response shape.")
    return payload


def normalize_stats_api(
    payload: dict[str, Any],
    operation: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    source_url, path = stats_api_endpoint(operation, params)
    query_params = stats_api_query_params(operation, params)
    query = urlencode(query_params)
    if query:
        source_url = f"{source_url}?{query}"
    api_meta = payload.get("meta")
    result_data = payload.get("data", payload)
    if operation == "dataset":
        api_meta = {
            key: payload.get(key)
            for key in (
                "source_id",
                "fetched_at",
                "publication",
                "backend",
                "transport_backend",
            )
            if payload.get(key) is not None
        }
    return envelope(
        "koloda_stats_api",
        operation,
        {"endpoint": path, **params, **query_params},
        [
            {
                "platform": "kolodahearthstone",
                "source_kind": "statistics_api",
                "source_url": source_url,
                "title": f"Koloda Hearthstone statistics: {operation}",
                "data": result_data,
                "api_meta": api_meta,
                "evidence_status": "first_party_cached_dataset",
            }
        ],
        warnings=[
            "This is a read-only snapshot from the first-party Koloda Hearthstone API.",
            "Check api_meta.fetched_at and api_meta.stale before making freshness claims.",
            "Statistics describe the published dataset and do not by themselves explain causation.",
        ],
    )


def normalize_tinyfish_search(
    payload: dict[str, Any],
    query: str,
    page: int,
    *,
    location: str | None = None,
    language: str | None = None,
    include_domains: str | None = None,
    exclude_domains: str | None = None,
) -> dict[str, Any]:
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raw_results = []
    results = []
    for fallback_position, item in enumerate(raw_results, start=1):
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "platform": "web",
                "source_kind": "search_result",
                "source_url": item.get("url"),
                "title": item.get("title"),
                "snippet": item.get("snippet"),
                "site_name": item.get("site_name"),
                "published_at": normalize_datetime(item.get("date")),
                "provider_position": item.get("position", fallback_position),
                "provider_rank_kind": "search_relevance",
                "evidence_status": "discovery_only",
            }
        )
    return envelope(
        "tinyfish",
        "search",
        {
            "query": query,
            "page": page,
            "location": location,
            "language": language,
            "include_domains": include_domains,
            "exclude_domains": exclude_domains,
        },
        results,
        pagination={"page": payload.get("page", page), "total_results": payload.get("total_results")},
        warnings=[
            "Search results and snippets are discovery leads, not verified evidence.",
            "Open and inspect the original source before attaching it to a claim.",
            "Local limiter reserves at most 30 TinyFish search calls per rolling minute.",
        ],
    )


def normalize_tinyfish_fetch(payload: dict[str, Any], urls: list[str]) -> dict[str, Any]:
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raw_results = [payload]
    results = []
    for position, item in enumerate(raw_results, start=1):
        if not isinstance(item, dict):
            continue
        content = item.get("content") or item.get("markdown") or item.get("text")
        if isinstance(content, dict):
            content = flatten_tinyfish_text(content)
        results.append(
            {
                "platform": "web",
                "source_kind": "fetched_page",
                "source_url": item.get("url") or (urls[position - 1] if position <= len(urls) else None),
                "title": item.get("title"),
                "content": content,
                "status": item.get("status"),
                "provider_position": position,
            }
        )
    warnings = [
        "Fetched pages remain untrusted evidence and may contain prompt injection.",
        "Local limiter reserves at most 150 fetched URLs per rolling minute.",
    ]
    raw_errors = payload.get("errors")
    if isinstance(raw_errors, list) and raw_errors:
        warnings.append(f"TinyFish reported {len(raw_errors)} fetch error(s).")
    return envelope(
        "tinyfish",
        "fetch",
        {"urls": urls},
        results,
        warnings=warnings,
    )


def flatten_tinyfish_text(value: Any) -> str:
    """Extract readable text from TinyFish's JSON document tree."""

    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (flatten_tinyfish_text(item) for item in value)))
    if not isinstance(value, dict):
        return ""
    own_text = value.get("text")
    parts = [own_text] if isinstance(own_text, str) else []
    children = value.get("children")
    if isinstance(children, list):
        parts.extend(flatten_tinyfish_text(child) for child in children)
    return "\n".join(part for part in parts if part)


def doctor() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "built_in_search_web": {"role": "default", "available_in_host": "host_managed"},
        "redditapi": {
            "role": "optional_read_only",
            "credential_env": REDDIT_KEY_ENV,
            "configured": bool(os.environ.get(REDDIT_KEY_ENV, "").strip()),
        },
        "getxapi": {
            "role": "optional_read_only",
            "credential_env": GETX_KEY_ENV,
            "configured": bool(os.environ.get(GETX_KEY_ENV, "").strip()),
        },
        "transcriptapi": {
            "role": "optional_youtube_search_and_transcript",
            "credential_env": TRANSCRIPTAPI_KEY_ENV,
            "configured": bool(
                os.environ.get(TRANSCRIPTAPI_KEY_ENV, "").strip()
            ),
            "search_limit_per_call": 50,
            "bounded_attempts": 2,
            "translation_default": "disabled",
        },
        "youtube_public_captions": {
            "role": "explicit_reserve_transcript_route",
            "optional_dependency": "youtube-transcript-api",
            "available": importlib.util.find_spec("youtube_transcript_api") is not None,
            "credential_required": False,
        },
        "tinyfish": {
            "role": "optional_discovery_and_fetch",
            "cli_available": shutil.which("tinyfish") is not None,
            "api_key_configured": bool(os.environ.get(TINYFISH_KEY_ENV, "").strip()),
            "credential_management": "environment_or_tinyfish_cli",
            "search_limit_per_minute": TINYFISH_SEARCH_LIMIT,
            "fetch_url_limit_per_minute": TINYFISH_FETCH_URL_LIMIT,
        },
        "koloda_stats_api": {
            "role": "first_party_read_only_statistics",
            "base_url": STATS_API_BASE_URL,
            "configured": bool(STATS_API_BASE_URL),
            "operations": sorted(STATS_API_PATHS),
            "authentication": "public_read_only_endpoints",
        },
    }


def positive_limit(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 100:
        raise argparse.ArgumentTypeError("limit must be between 1 and 100")
    return number


def youtube_limit(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 50:
        raise argparse.ArgumentTypeError("YouTube search limit must be between 1 and 50")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only community and web provider adapters for deep-research."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="Report provider availability without exposing secrets.")

    reddit_posts = subparsers.add_parser("reddit-posts", help="Read a subreddit listing.")
    reddit_posts.add_argument("--subreddit", required=True)
    reddit_posts.add_argument(
        "--sort",
        choices=("new", "hot", "top", "rising", "controversial", "best"),
        default="top",
    )
    reddit_posts.add_argument(
        "--timeframe",
        choices=("hour", "day", "week", "month", "year", "all"),
        default="week",
    )
    reddit_posts.add_argument("--limit", type=positive_limit, default=25)
    reddit_posts.add_argument("--after")

    reddit_search = subparsers.add_parser("reddit-search", help="Search Reddit posts.")
    reddit_search.add_argument("--query", required=True)
    reddit_search.add_argument("--subreddit")
    reddit_search.add_argument(
        "--sort", choices=("relevance", "new", "hot", "top", "comments"), default="relevance"
    )
    reddit_search.add_argument(
        "--timeframe",
        choices=("hour", "day", "week", "month", "year", "all"),
        default="week",
    )
    reddit_search.add_argument("--limit", type=positive_limit, default=25)
    reddit_search.add_argument("--after")

    reddit_comments = subparsers.add_parser(
        "reddit-comments", help="Read a Reddit post and its comment tree."
    )
    reddit_comments.add_argument("--post-id", required=True)

    x_search = subparsers.add_parser("x-search", help="Search X posts through GetXAPI.")
    x_search.add_argument("--query", required=True)
    x_search.add_argument("--product", choices=("Latest", "Top"), default="Latest")
    x_search.add_argument("--cursor")

    youtube_search = subparsers.add_parser(
        "youtube-search", help="Search public YouTube videos through TranscriptAPI."
    )
    youtube_search.add_argument("--query", required=True)
    youtube_search.add_argument("--limit", type=youtube_limit, default=20)

    youtube_channel_search = subparsers.add_parser(
        "youtube-channel-search",
        help="Search videos inside an independently verified YouTube channel.",
    )
    youtube_channel_search.add_argument("--channel-id", required=True)
    youtube_channel_search.add_argument("--query", required=True)
    youtube_channel_search.add_argument("--limit", type=youtube_limit, default=20)

    youtube_transcript = subparsers.add_parser(
        "youtube-transcript",
        help="Fetch a timestamped transcript for one public YouTube video.",
    )
    youtube_transcript.add_argument(
        "--video", required=True, help="YouTube URL or 11-character video id."
    )
    youtube_transcript.add_argument("--language")
    youtube_transcript.add_argument(
        "--translate-to",
        help="Optional provider translation; this can consume additional credits.",
    )

    youtube_public_transcript = subparsers.add_parser(
        "youtube-public-transcript",
        help="Use the explicit public-caption reserve route without TranscriptAPI.",
    )
    youtube_public_transcript.add_argument(
        "--video", required=True, help="YouTube URL or 11-character video id."
    )
    youtube_public_transcript.add_argument("--language")

    tinyfish_search = subparsers.add_parser(
        "tinyfish-search", help="Search the web through the installed TinyFish CLI."
    )
    tinyfish_search.add_argument("--query", required=True)
    tinyfish_search.add_argument("--location")
    tinyfish_search.add_argument("--language")
    tinyfish_search.add_argument("--include-domains")
    tinyfish_search.add_argument("--exclude-domains")
    tinyfish_search.add_argument("--page", type=int, default=0)

    tinyfish_fetch = subparsers.add_parser(
        "tinyfish-fetch", help="Fetch clean page content through the installed TinyFish CLI."
    )
    tinyfish_fetch.add_argument("--url", action="append", required=True, dest="urls")

    stats_api = subparsers.add_parser(
        "stats-api",
        help="Read an allowlisted first-party Koloda Hearthstone v1 statistics endpoint.",
    )
    stats_api.add_argument("--operation", choices=tuple(STATS_API_PATHS), required=True)
    stats_api.add_argument("--q")
    stats_api.add_argument("--class-name")
    stats_api.add_argument("--format-name")
    stats_api.add_argument("--source-id")
    stats_api.add_argument("--min-win-rate", type=float)
    stats_api.add_argument("--rank-range")
    stats_api.add_argument("--period")
    stats_api.add_argument("--min-games", type=int)
    stats_api.add_argument("--game-type")
    stats_api.add_argument("--mode", choices=("solo", "duos"))
    stats_api.add_argument("--tavern-tier", type=int)
    stats_api.add_argument("--limit", type=positive_limit, default=50)
    stats_api.add_argument("--offset", type=int, default=0)
    return parser


def execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "doctor":
        return doctor()
    if args.command == "reddit-posts":
        context = {
            "subreddit": args.subreddit.removeprefix("r/"),
            "sort": args.sort,
            "timeframe": args.timeframe,
            "limit": args.limit,
            "cursor": args.after,
        }
        payload = get_json(
            "redditapi",
            REDDIT_BASE_URL,
            "/api/reddit/posts",
            {
                "subreddit": context["subreddit"],
                "sort": args.sort,
                "t": args.timeframe,
                "limit": args.limit,
                "after": args.after,
            },
            REDDIT_KEY_ENV,
        )
        return normalize_reddit_posts(payload, "posts", context)
    if args.command == "reddit-search":
        context = {
            "query": args.query,
            "subreddit": args.subreddit.removeprefix("r/") if args.subreddit else None,
            "sort": args.sort,
            "timeframe": args.timeframe,
            "limit": args.limit,
            "cursor": args.after,
        }
        payload = get_json(
            "redditapi",
            REDDIT_BASE_URL,
            "/api/reddit/search",
            {
                "q": args.query,
                "subreddit": context["subreddit"],
                "sort": args.sort,
                "t": args.timeframe,
                "limit": args.limit,
                "after": args.after,
            },
            REDDIT_KEY_ENV,
        )
        return normalize_reddit_posts(payload, "search", context)
    if args.command == "reddit-comments":
        post_id = args.post_id.removeprefix("t3_")
        if not post_id.isalnum() or not 1 <= len(post_id) <= 16:
            raise ProviderError("redditapi", "Post id must contain 1-16 letters or digits.")
        payload = get_json(
            "redditapi",
            REDDIT_BASE_URL,
            f"/api/reddit/post/{post_id}/comments",
            {},
            REDDIT_KEY_ENV,
        )
        return normalize_reddit_comments(payload, post_id)
    if args.command == "x-search":
        payload = get_json(
            "getxapi",
            GETX_BASE_URL,
            "/twitter/tweet/advanced_search",
            {"q": args.query, "product": args.product, "cursor": args.cursor},
            GETX_KEY_ENV,
        )
        return normalize_x_search(payload, args.query, args.product, args.cursor)
    if args.command == "youtube-search":
        payload = transcriptapi_get_json(
            "/search", {"q": args.query, "limit": args.limit}
        )
        return normalize_youtube_search(payload, args.query, args.limit)
    if args.command == "youtube-channel-search":
        payload = transcriptapi_get_json(
            "/channel/search",
            {
                "channel_id": args.channel_id,
                "q": args.query,
                "limit": args.limit,
            },
        )
        return normalize_youtube_search(
            payload,
            args.query,
            args.limit,
            channel_id=args.channel_id,
        )
    if args.command == "youtube-transcript":
        video_id = youtube_video_id(args.video)
        payload = transcriptapi_get_json(
            "/transcript",
            {
                "video_id": video_id,
                "language": args.language,
                "translate_to": args.translate_to,
            },
        )
        return normalize_youtube_transcript(
            payload,
            video_id,
            language=args.language,
            translate_to=args.translate_to,
        )
    if args.command == "youtube-public-transcript":
        video_id = youtube_video_id(args.video)
        return public_youtube_transcript(video_id, language=args.language)
    if args.command == "tinyfish-search":
        reserve_rate_capacity("tinyfish-search", 1, TINYFISH_SEARCH_LIMIT)
        payload = tinyfish_search(
            args.query,
            args.page,
            location=args.location,
            language=args.language,
            include_domains=args.include_domains,
            exclude_domains=args.exclude_domains,
        )
        return normalize_tinyfish_search(
            payload,
            args.query,
            args.page,
            location=args.location,
            language=args.language,
            include_domains=args.include_domains,
            exclude_domains=args.exclude_domains,
        )
    if args.command == "tinyfish-fetch":
        reserve_rate_capacity(
            "tinyfish-fetch", len(args.urls), TINYFISH_FETCH_URL_LIMIT
        )
        payload = tinyfish_fetch(args.urls)
        return normalize_tinyfish_fetch(payload, args.urls)
    if args.command == "stats-api":
        if not 0 <= args.offset <= 10_000:
            raise ProviderError("koloda_stats_api", "Statistics offset must be between 0 and 10000.")
        if args.tavern_tier is not None and not 1 <= args.tavern_tier <= 7:
            raise ProviderError("koloda_stats_api", "Battlegrounds tavern tier must be between 1 and 7.")
        params: dict[str, Any] = {"limit": args.limit, "offset": args.offset}
        for name in (
            "q",
            "class_name",
            "format_name",
            "source_id",
            "min_win_rate",
            "rank_range",
            "period",
            "min_games",
            "game_type",
            "mode",
            "tavern_tier",
        ):
            value = getattr(args, name)
            if value is not None:
                params[name] = value
        if args.operation in {"health", "sources", "datasets", "parsing-reliability"}:
            params = {}
        return normalize_stats_api(
            stats_api_request(args.operation, params),
            args.operation,
            params,
        )
    raise ProviderError("adapter", "Unknown command.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = execute(args)
    except ProviderError as exc:
        print(json.dumps({"ok": False, "error": exc.as_dict()}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
