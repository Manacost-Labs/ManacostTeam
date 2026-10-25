#!/usr/bin/env python3
"""Scheduled refresh of the durable source catalog."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import library_refresh  # noqa: E402


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class LibraryRefreshTest(unittest.TestCase):
    class Collector:
        def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
            self.responses = responses

        def collect(self, url: str, contract: Any, **options: Any) -> dict[str, Any]:
            return self.responses[url]

    def test_feeds_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "feeds.json"
            path.write_text(json.dumps({"feeds": [{"id": "x", "kind": "html_links", "url": "https://a.example/"}]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "canary and link_pattern"):
                library_refresh.load_feeds(path)
        self.assertGreaterEqual(len(library_refresh.load_feeds(library_refresh.FEEDS_FILE)), 10)

    def test_refresh_appends_only_new_items_and_queues_recent_episodes(self) -> None:
        recent = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        rss = (
            "<rss><channel><title>Pod</title>"
            f"<item><title>New</title><guid>ep-2</guid><pubDate>{recent}</pubDate><link>https://pod.example/2</link>"
            "<enclosure url='https://pod.example/2.mp3' type='audio/mpeg'/></item>"
            "<item><title>Old</title><guid>ep-1</guid><pubDate>Mon, 05 Jan 2015 10:00:00 +0000</pubDate></item>"
            "</channel></rss>"
        )
        feeds = [
            {"id": "pod", "kind": "rss", "url": "https://pod.example/rss", "series": "pod", "source_class": "podcast"},
            {"id": "news", "kind": "blizzard_articles", "url": "https://news.example/list", "source_class": "official"},
            {"id": "stats", "kind": "json_snapshot", "url": "https://stats.example/v1", "source_class": "statistics"},
            {"id": "down", "kind": "rss", "url": "https://down.example/rss"},
        ]
        collector = self.Collector({
            "https://pod.example/rss": {"verdict": "OK", "text": rss},
            "https://news.example/list": {"verdict": "OK", "data": [{"id": 24301454, "title": "37.0 Patch Notes", "publish": 1791824100000}]},
            "https://stats.example/v1": {"verdict": "STALE_LKG", "data": {"data": [1]}, "source_freshness": {"stale": True}},
            "https://down.example/rss": {"verdict": "BLOCKED", "attempts": [{"route": "direct", "verdict": "BLOCKED", "http_status": 403}]},
        })
        since = datetime.now(timezone.utc) - timedelta(days=14)
        with tempfile.TemporaryDirectory() as temp:
            catalog = Path(temp)
            archived = lambda series, episode: False  # noqa: E731
            reports = [library_refresh.refresh_feed(feed, collector, catalog, ttl=0, refresh=False, archived=archived, queue_since=since)
                       for feed in feeds]
            self.assertEqual([report["new_items"] for report in reports], [2, 1, 1, 0])
            self.assertEqual(reports[0]["queued_transcripts"], 1)
            self.assertEqual(reports[3]["verdict"], "BLOCKED")
            queue = read_jsonl(catalog / "transcript-queue.jsonl")
            self.assertEqual(queue[0]["item_id"], "ep-2")
            self.assertIn("source_library.py transcribe --series pod", queue[0]["command"])
            news = read_jsonl(catalog / "news.jsonl")
            self.assertEqual(news[0]["url"], "https://hearthstone.blizzard.com/en-us/news/24301454")
            self.assertEqual(news[0]["evidence_status"], "discovery_only")
            self.assertTrue(read_jsonl(catalog / "stats.jsonl")[0]["stale"])
            again = [library_refresh.refresh_feed(feed, collector, catalog, ttl=0, refresh=False, archived=archived, queue_since=since)
                     for feed in feeds[:3]]
            self.assertEqual([report["new_items"] for report in again], [0, 0, 0])

    def test_listing_links_follow_the_pattern(self) -> None:
        html = '<a href="https://hs.blizzard.cn/news/24301454/">a</a><a href="https://hs.blizzard.cn/news/20261020/40864_1317041.html">b</a><a href="https://wow.blizzard.cn/x">c</a>'
        pattern = json.loads(library_refresh.FEEDS_FILE.read_text(encoding="utf-8"))["feeds"][1]["link_pattern"]
        self.assertEqual([item["url"] for item in library_refresh.parse_links(html, pattern)],
                         ["https://hs.blizzard.cn/news/24301454/", "https://hs.blizzard.cn/news/20261020/40864_1317041.html"])


if __name__ == "__main__":
    unittest.main()
