#!/usr/bin/env python3
"""Keep the durable Hearthstone source catalog current between research runs.

Reads ``research/library/feeds.json`` (patch notes, podcasts, statistics,
community threads), acquires every feed through ``source_collector.Collector``
(cache, cooldowns after failures, explicit ``STALE_LKG``), parses the items
and appends unseen ones to ``research/library/catalog/<feed>.jsonl``.
Statistics feeds keep dated snapshots. Podcast episodes that have no
transcript in the archive yet are listed with the ``source_library.py``
command that archives them; transcription itself stays an explicit step.

Every run appends one line to ``catalog/refresh-log.jsonl`` with each feed's
verdict, so a blocked or stale feed stays visible. Catalog items are discovery
leads: research still opens the page or transcript before citing it.
Run it from a scheduler (see ``research/library/README.md``); it exits 1 when
any feed failed and 0 otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable

import source_access
from source_collector import Collector, Contract, Store, direct

SCRIPTS = Path(__file__).resolve().parent
LIBRARY = SCRIPTS.parents[1] / "library"
FEEDS_FILE = LIBRARY / "feeds.json"
KINDS = ("blizzard_articles", "rss", "html_links", "json_snapshot")
HREF_RE = re.compile(r"""href=["']([^"'#]+)""", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_feeds(path: Path) -> list[dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    feeds = document.get("feeds") if isinstance(document, dict) else None
    if not isinstance(feeds, list) or not feeds:
        raise ValueError(f"{path.name}: feeds must be a non-empty list")
    seen = set()
    for feed in feeds:
        if not isinstance(feed, dict) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", str(feed.get("id", ""))):
            raise ValueError(f"{path.name}: every feed needs a lowercase id")
        if feed["id"] in seen:
            raise ValueError(f"{path.name}: duplicate feed {feed['id']}")
        seen.add(feed["id"])
        if feed.get("kind") not in KINDS or not str(feed.get("url", "")).startswith("https://"):
            raise ValueError(f"{feed['id']}: kind must be one of {', '.join(KINDS)} with an https url")
        if feed["kind"] == "html_links" and not (feed.get("canary") and feed.get("link_pattern")):
            raise ValueError(f"{feed['id']}: html_links needs canary and link_pattern")
    return feeds


def contract_for(feed: dict[str, Any]) -> Contract:
    if feed["kind"] == "rss":
        return Contract("rss", min_chars=0)
    if feed["kind"] == "blizzard_articles":
        return Contract("json", json_paths=("0.id",), min_chars=0)
    return Contract("json", json_paths=tuple(feed.get("json_paths") or ("data",)), min_chars=0)


def parse_blizzard(data: Any) -> list[dict[str, Any]]:
    items = []
    for article in data if isinstance(data, list) else []:
        if not isinstance(article, dict) or not isinstance(article.get("id"), int):
            continue
        published = article.get("publish")
        items.append({
            "item_id": str(article["id"]),
            "title": article.get("title"),
            "url": f"https://hearthstone.blizzard.com/en-us/news/{article['id']}",
            "published_at": datetime.fromtimestamp(published / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
            if isinstance(published, (int, float)) else None,
            "summary": article.get("summary"),
        })
    return items


def parse_rss(text: str, url: str) -> list[dict[str, Any]]:
    from source_library import parse_feed

    items = []
    for entry in parse_feed(text.encode("utf-8"), url):
        items.append({
            "item_id": str(entry["episode_id"]),
            "title": entry.get("title"),
            "url": entry.get("source_url"),
            "published_at": entry.get("published_at"),
            "audio_url": entry.get("audio_url"),
            "publisher_transcripts": entry.get("publisher_transcripts") or [],
        })
    return items


def parse_links(html: str, pattern: str) -> list[dict[str, Any]]:
    wanted = re.compile(pattern)
    links = dict.fromkeys(link for link in HREF_RE.findall(html) if wanted.match(link))
    return [{"item_id": link, "title": None, "url": link, "published_at": None} for link in links]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def published(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def transcript_queue(feed: dict[str, Any], items: list[dict[str, Any]], archived: Callable[[str, str], bool],
                     *, since: datetime) -> list[dict[str, Any]]:
    """Recent episodes only: a first run must not queue a feed's whole back catalog."""
    queue = []
    for item in items:
        when = published(item.get("published_at"))
        if when is None or when < since or archived(feed.get("series", feed["id"]), item["item_id"]):
            continue
        command = (
            f"python3 scripts/source_library.py transcribe --series {feed.get('series', feed['id'])} "
            f"--episode-id '{item['item_id']}' --source-url '{item.get('url') or feed['url']}' --audio PATH_TO_AUDIO"
        )
        queue.append({"feed_id": feed["id"], "item_id": item["item_id"], "title": item.get("title"),
                      "audio_url": item.get("audio_url"), "publisher_transcripts": item.get("publisher_transcripts", []),
                      "command": command})
    return queue


def archive_index(transcripts: Path) -> Callable[[str, str], bool]:
    """(series, episode) pairs already in the transcript archive."""
    pairs = set()
    for path in transcripts.glob("*.json") if transcripts.is_dir() else []:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict):
            pairs.add((str(record.get("series")), str(record.get("episode_id"))))
    return lambda series, episode: (series, episode) in pairs


def fetch_listing(feed: dict[str, Any]) -> dict[str, Any]:
    """A listing page needs its raw links, which the collector's visible text drops."""
    try:
        raw = direct(feed["url"])
    except source_access.AccessError as exc:
        return {"verdict": exc.code, "attempts": [{"route": "direct", "verdict": exc.code, "http_status": exc.status}]}
    if raw["status"] != 200 or feed["canary"] not in raw["body"]:
        return {"verdict": "PARSE_FAIL", "attempts": [{"route": "direct", "verdict": "PARSE_FAIL", "http_status": raw["status"]}]}
    return {"verdict": "OK", "cache": "NONE", "text": raw["body"]}


def refresh_feed(feed: dict[str, Any], collector: Collector, catalog: Path, *, ttl: float, refresh: bool,
                 archived: Callable[[str, str], bool], queue_since: datetime) -> dict[str, Any]:
    if feed["kind"] == "html_links":
        result = fetch_listing(feed)
    else:
        result = collector.collect(feed["url"], contract_for(feed), ttl=ttl, refresh=refresh, allow_stale=True)
    report: dict[str, Any] = {"feed_id": feed["id"], "source_class": feed.get("source_class"), "verdict": result["verdict"],
                              "cache": result.get("cache"), "new_items": 0, "queued_transcripts": 0}
    if result["verdict"] not in {"OK", "STALE_LKG"}:
        report["attempts"] = [{key: attempt.get(key) for key in ("route", "verdict", "http_status")} for attempt in result.get("attempts", [])]
        return report
    seen_at = utc_now()
    if feed["kind"] == "json_snapshot":
        payload = result.get("data")
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        snapshots = catalog / "snapshots" / feed["id"]
        known = {item.get("content_sha256") for item in read_jsonl(catalog / f"{feed['id']}.jsonl")}
        if digest not in known:
            snapshots.mkdir(parents=True, exist_ok=True)
            path = snapshots / f"{seen_at[:10]}-{digest[:12]}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            freshness = result.get("source_freshness", {})
            append_jsonl(catalog / f"{feed['id']}.jsonl", [{
                "item_id": digest[:16], "url": feed["url"], "content_sha256": digest, "snapshot": str(path.relative_to(catalog)),
                "source_freshness": freshness, "first_seen_at": seen_at, "stale": result["verdict"] == "STALE_LKG",
            }])
            report["new_items"] = 1
        return report
    if feed["kind"] == "blizzard_articles":
        items = parse_blizzard(result.get("data"))
    elif feed["kind"] == "rss":
        items = parse_rss(str(result.get("text", "")), feed["url"])
    else:
        items = parse_links(str(result.get("text", "")), feed["link_pattern"])
    path = catalog / f"{feed['id']}.jsonl"
    known = {item["item_id"] for item in read_jsonl(path)}
    fresh = [dict(item, feed_id=feed["id"], source_class=feed.get("source_class"), first_seen_at=seen_at,
                  evidence_status="discovery_only") for item in items if item["item_id"] not in known]
    append_jsonl(path, fresh)
    report["new_items"] = len(fresh)
    if feed.get("series"):
        queue = transcript_queue(feed, fresh, archived, since=queue_since)
        append_jsonl(catalog / "transcript-queue.jsonl", queue)
        report["queued_transcripts"] = len(queue)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--feeds", type=Path, default=FEEDS_FILE)
    parser.add_argument("--catalog", type=Path, default=LIBRARY / "catalog")
    parser.add_argument("--transcripts", type=Path, default=LIBRARY / "transcripts")
    parser.add_argument("--feed", action="append", default=[], help="Refresh only these feed ids")
    parser.add_argument("--ttl", type=float, default=3600, help="Reuse a successful fetch younger than this (seconds)")
    parser.add_argument("--refresh", action="store_true", help="Ignore the fetch cache")
    parser.add_argument("--queue-days", type=int, default=14, help="Queue transcripts for episodes published this recently")
    parser.add_argument("--state", type=Path, help="source_collector state database")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        feeds = load_feeds(args.feeds)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    unknown = sorted(set(args.feed) - {feed["id"] for feed in feeds})
    if unknown:
        print(f"error: unknown feed {', '.join(unknown)}", file=sys.stderr)
        return 2
    collector = Collector(Store(args.state))
    archived = archive_index(args.transcripts)
    reports = []
    for feed in feeds:
        if args.feed and feed["id"] not in args.feed:
            continue
        try:
            reports.append(refresh_feed(feed, collector, args.catalog, ttl=args.ttl, refresh=args.refresh, archived=archived,
                                        queue_since=datetime.now(timezone.utc) - timedelta(days=args.queue_days)))
        except (ValueError, OSError) as exc:
            # One broken feed must not hide the others; the log keeps the failure.
            reports.append({"feed_id": feed["id"], "verdict": "REFRESH_ERROR", "error": f"{type(exc).__name__}: {exc}"})
    append_jsonl(args.catalog / "refresh-log.jsonl", [{"run_at": utc_now(), "feeds": reports}])
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        for report in reports:
            print(f"- {report['feed_id']}: {report['verdict']}, {report.get('new_items', 0)} new"
                  + (f", {report['queued_transcripts']} transcripts queued" if report.get("queued_transcripts") else ""))
    return int(any(report["verdict"] not in {"OK", "STALE_LKG"} for report in reports))


if __name__ == "__main__":
    sys.exit(main())
