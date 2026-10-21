#!/usr/bin/env python3
"""Probe every registered owner source through Collector; content is not truth.

Channel metadata, RSS and readable pages have different coverage levels.
The permanent transcript library is read for identity only, never rewritten.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from source_collector import Collector, Contract, Store
from source_library import (
    checklist,
    coverage,
    library_root,
    parse_feed,
    required_sources,
    utc_now,
    write_json,
)

FALLBACKS = {
    "bilibili": "https://search.bilibili.com/all?keyword=%E7%82%89%E7%9F%B3%E4%BC%A0%E8%AF%B4",
    "note-hearthstone": "https://note.com/search?q=%E3%83%8F%E3%83%BC%E3%82%B9%E3%82%B9%E3%83%88%E3%83%BC%E3%83%B3&context=note&mode=search",
}


def archive_match(feed_result: dict, source_id: str, root: Path | None) -> dict:
    if feed_result.get("verdict") != "OK" or not root:
        return {"status": "NOT_CHECKED"}
    try:
        episodes = parse_feed(feed_result["text"].encode(), feed_result["url"])
        latest = episodes[0] if episodes else None
        if not latest:
            return {"status": "NO_EPISODE"}
        episode_id = latest.get("episode_id")
        for path in root.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            if (
                record.get("series") == source_id
                and record.get("episode_id") == episode_id
            ):
                return {
                    "status": "PRESENT",
                    "episode_id": episode_id,
                    "archive_key": record.get("archive_key"),
                }
        return {"status": "NOT_ARCHIVED", "episode_id": episode_id}
    except (OSError, ValueError, KeyError):
        return {"status": "ARCHIVE_CHECK_FAILED"}


def audit(
    collector: Collector,
    output: Path,
    *,
    sources=None,
    refresh=False,
    archive: Path | None = None,
) -> dict:
    sources = required_sources() if sources is None else sources
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for source in sources:
        sid, url = source["id"], source["owner_urls"][0]
        attempts, selected, level = [], None, "unavailable"
        now = utc_now()
        try:
            feeds = source.get("feed_urls") or []
            # These RSS URLs have been verified and belong to this named podcast;
            # the audit does not pretend that the HTML homepage was inspected.
            target = feeds[0] if feeds else url
            first = collector.collect(
                target, Contract("rss", min_chars=0) if feeds else None, refresh=refresh
            )
            attempts.append(first)
            selected = first
            topic_search_failed = False
            if sid in FALLBACKS:
                alternate = collector.collect(FALLBACKS[sid], refresh=refresh)
                attempts.append(alternate)
                topic_search_failed = alternate["verdict"] != "OK"
                selected = (
                    first
                    if topic_search_failed and first["verdict"] == "OK"
                    else alternate
                )
            if selected["verdict"] == "OK":
                level = (
                    "channel_discovery_only"
                    if selected.get("provider") == "transcriptapi-channel"
                    else "rss_catalogue"
                    if feeds
                    else "readable_page"
                )
                if topic_search_failed:
                    level = "generic_homepage_only"
            result = {
                "id": sid,
                "owner_url": url,
                "attempted_at": now,
                "selected_url": selected.get("final_url", selected.get("url")),
                "verdict": selected["verdict"],
                "provider": selected.get("provider"),
                "cache": selected.get("cache"),
                "coverage_level": level,
                "text_chars": len(selected.get("text", "")),
                "evidence_validated": False,
            }
            if feeds:
                result["transcript_archive"] = archive_match(selected, sid, archive)
            if level == "channel_discovery_only":
                result["video_count"] = len(selected.get("data", {}).get("videos", []))
                result["limitation"] = (
                    "Channel metadata only; video contents and captions not inspected."
                )
            if topic_search_failed:
                result["limitation"] = (
                    "Topic search unavailable; a readable homepage is not topic coverage."
                )
            write_json(
                output / f"{sid}-receipt.json",
                {"source": result, "collection_results": attempts},
            )
        except Exception as exc:  # noqa: BLE001 -- no source may disappear from the audit
            result = {
                "id": sid,
                "owner_url": url,
                "attempted_at": now,
                "verdict": "AUDIT_ERROR",
                "error_type": type(exc).__name__,
                "coverage_level": "unavailable",
                "evidence_validated": False,
            }
            write_json(output / f"{sid}-receipt.json", {"source": result})
        results.append(result)
        # Progress is metadata only; no source body or credential values.
        print(
            json.dumps(
                {
                    k: result.get(k)
                    for k in ("id", "verdict", "provider", "cache", "coverage_level")
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    ids = [r["id"] for r in results]
    expected = [r["id"] for r in sources]
    accounting = {
        "input": len(sources),
        "accounted": len(results),
        "unaccounted": len(sources) - len(results),
        "missing_ids": sorted(set(expected) - set(ids)),
        "duplicate_ids": sorted({i for i in ids if ids.count(i) > 1}),
    }
    summary = {
        "created_at": utc_now(),
        "results": results,
        "accounting": accounting,
        "evidence_validated": False,
    }
    write_json(output / "owner-source-results.json", summary)
    if set(expected) == {r["id"] for r in required_sources()}:
        plan = checklist()
        by_id = {r["id"]: r for r in results}
        for row in plan["sources"]:
            found = by_id[row["id"]]
            success = found["verdict"] == "OK"
            row.update(
                status="inspected" if success else "blocked",
                query="Access audit through Collector: " + found["owner_url"],
                attempted_at=found["attempted_at"],
                inspected_urls=[found["selected_url"]] if success else [],
                reason=None if success else found["verdict"],
                findings=[
                    "Coverage level: " + found["coverage_level"],
                    "Receipt: "
                    + row["id"]
                    + "-receipt.json; factual evidence not validated.",
                ],
            )
        write_json(output / "owner-source-coverage.json", plan)
        write_json(output / "owner-source-coverage-validation.json", coverage(plan))
    return summary


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--state", type=Path)
    p.add_argument("--browser", action="store_true")
    p.add_argument(
        "--browser-engine", choices=("playwright", "patchright"), default="playwright"
    )
    p.add_argument("--browser-channel")
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args(argv)
    browser = None
    try:
        if args.browser:
            from source_browser import BrowserPool

            browser = BrowserPool(
                engine=args.browser_engine, channel=args.browser_channel
            )
        try:
            archive = library_root()
        except ValueError:
            archive = None
        result = audit(
            Collector(Store(args.state), browser=browser),
            args.output,
            refresh=args.refresh,
            archive=archive,
        )
        print(
            json.dumps(
                {
                    "accounting": result["accounting"],
                    "readable": sum(r["verdict"] == "OK" for r in result["results"]),
                }
            )
        )
        return int(any(r["verdict"] != "OK" for r in result["results"]))
    finally:
        if browser:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
