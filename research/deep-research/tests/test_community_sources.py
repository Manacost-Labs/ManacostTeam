#!/usr/bin/env python3
"""Offline tests for optional read-only source adapters."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse, urlsplit


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/community_sources.py"
SPEC = importlib.util.spec_from_file_location("community_sources", MODULE_PATH)
assert SPEC and SPEC.loader
community_sources = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(community_sources)


class CommunitySourcesTest(unittest.TestCase):
    def test_reddit_posts_are_normalized_and_risk_flags_are_preserved(self) -> None:
        payload = {
            "posts": [
                {
                    "id": "abc123",
                    "title": "Weekly giveaway",
                    "author": "AutoModerator",
                    "subreddit": "hearthstone",
                    "url": "https://reddit.com/r/hearthstone/comments/abc123/test/",
                    "text": "",
                    "upvotes": 42,
                    "comments": 12,
                    "upvote_ratio": 0.9,
                    "created_utc": 1_700_000_000,
                    "is_crosspost": True,
                    "stickied": True,
                }
            ],
            "after": None,
            "listing_status": "unknown",
        }
        result = community_sources.normalize_reddit_posts(
            payload,
            "posts",
            {"subreddit": "hearthstone", "sort": "top", "timeframe": "week"},
        )
        item = result["results"][0]
        self.assertEqual(item["metrics"]["comments"], 12)
        self.assertEqual(item["provider_rank_kind"], "top")
        self.assertEqual(
            set(item["classification_flags"]),
            {"automated", "giveaway", "crosspost", "stickied"},
        )
        self.assertTrue(any("partial" in warning for warning in result["warnings"]))

    def test_reddit_comment_tree_is_flattened_without_claiming_completeness(self) -> None:
        payload = {
            "comments": [
                {
                    "kind": "t1",
                    "data": {
                        "id": "one",
                        "author": "reader",
                        "body": "First",
                        "score": 10,
                        "created_utc": 1_700_000_000,
                        "parent_id": "t3_post1",
                        "replies": {
                            "data": {
                                "children": [
                                    {
                                        "kind": "t1",
                                        "data": {
                                            "id": "two",
                                            "author": "reader2",
                                            "body": "Reply",
                                            "score": 3,
                                            "parent_id": "t1_one",
                                            "replies": "",
                                        },
                                    }
                                ]
                            }
                        },
                    },
                },
                {"kind": "more", "data": {"count": 7, "children": ["x"]}},
            ],
            "listing_status": "truncated",
        }
        result = community_sources.normalize_reddit_comments(payload, "post1")
        self.assertEqual([item["thread"]["depth"] for item in result["results"]], [0, 1])
        self.assertEqual(result["pagination"]["hidden_comment_count"], 7)
        self.assertTrue(any("complete" in warning for warning in result["warnings"]))

    def test_x_search_preserves_metrics_and_provider_rank_semantics(self) -> None:
        payload = {
            "tweets": [
                {
                    "id": "123",
                    "url": "https://x.com/example/status/123",
                    "text": "Patch discussion",
                    "createdAt": "Sun Jan 25 13:05:46 +0000 2026",
                    "likeCount": 8,
                    "replyCount": 2,
                    "retweetCount": 1,
                    "quoteCount": 0,
                    "viewCount": 100,
                    "author": {"id": "u1", "userName": "example", "followers": 50},
                }
            ],
            "has_more": True,
            "next_cursor": "next",
        }
        result = community_sources.normalize_x_search(payload, "hearthstone", "Top")
        item = result["results"][0]
        self.assertEqual(item["provider_rank_kind"], "top")
        self.assertEqual(item["metrics"]["views"], 100)
        self.assertEqual(result["pagination"]["next_cursor"], "next")
        self.assertTrue(any("not a guaranteed" in warning for warning in result["warnings"]))

    def test_tinyfish_search_is_discovery_only(self) -> None:
        payload = {
            "query": "test",
            "page": 0,
            "total_results": 1,
            "results": [
                {
                    "position": 1,
                    "url": "https://example.com/source",
                    "title": "Source",
                    "snippet": "Candidate evidence",
                    "site_name": "example.com",
                }
            ],
        }
        result = community_sources.normalize_tinyfish_search(payload, "test", 0)
        self.assertEqual(result["results"][0]["evidence_status"], "discovery_only")
        self.assertTrue(any("30" in warning for warning in result["warnings"]))

    def test_tinyfish_fetch_flattens_json_document_tree(self) -> None:
        payload = {
            "results": [
                {
                    "url": "https://example.com",
                    "title": "Example",
                    "text": {
                        "type": "document",
                        "children": [
                            {"type": "paragraph", "text": "First"},
                            {"type": "paragraph", "text": "Second"},
                        ],
                    },
                }
            ],
            "errors": [],
        }
        result = community_sources.normalize_tinyfish_fetch(payload, ["https://example.com"])
        self.assertEqual(result["results"][0]["content"], "First\nSecond")

    def test_youtube_search_normalizes_metrics_without_inventing_expertise(self) -> None:
        payload = {
            "query": "hearthstone pro guide",
            "results": [
                {
                    "id": "dQw4w9WgXcQ",
                    "title": "Current patch guide",
                    "channel": "Example Pro",
                    "views": "2.7K views",
                    "duration": "1:02:03",
                }
            ],
        }
        result = community_sources.normalize_youtube_search(
            payload, "hearthstone pro guide", 20
        )
        item = result["results"][0]
        self.assertEqual(item["metrics"]["views"], 2700)
        self.assertEqual(item["metrics"]["duration_seconds"], 3723)
        self.assertEqual(item["expertise"]["status"], "unverified")
        self.assertEqual(item["evidence_status"], "discovery_only")
        scoped = community_sources.normalize_youtube_search(
            payload,
            "hearthstone pro guide",
            20,
            channel_id="@verified-player",
        )
        self.assertEqual(
            scoped["results"][0]["expertise"]["status"],
            "channel_scoped_unverified",
        )

    def test_youtube_video_id_accepts_common_urls_and_rejects_other_hosts(self) -> None:
        expected = "dQw4w9WgXcQ"
        values = (
            expected,
            f"https://www.youtube.com/watch?v={expected}&t=10s",
            f"https://youtu.be/{expected}",
            f"https://www.youtube.com/shorts/{expected}",
            f"https://www.youtube.com/embed/{expected}",
        )
        self.assertEqual(
            [community_sources.youtube_video_id(value) for value in values],
            [expected] * len(values),
        )
        with self.assertRaises(community_sources.ProviderError):
            community_sources.youtube_video_id(
                f"https://example.com/watch?v={expected}"
            )

    def test_youtube_transcript_preserves_timestamped_segments_and_windows(self) -> None:
        payload = {
            "video_id": "dQw4w9WgXcQ",
            "transcript": [
                {"start": 0.0, "duration": 4.0, "text": "Opening"},
                {"start": 7.0, "duration": 5.0, "text": "Mulligan advice"},
                {"start": 33.0, "duration": 4.0, "text": "Matchup advice"},
            ],
        }
        result = community_sources.normalize_youtube_transcript(
            payload, "dQw4w9WgXcQ", language="en"
        )
        item = result["results"][0]
        self.assertEqual(item["segment_count"], 3)
        self.assertEqual(len(item["evidence_windows"]), 2)
        self.assertIn("t=7s", item["segments"][1]["timestamp_url"])
        self.assertEqual(len(item["content_hash"]), 64)
        self.assertEqual(item["evidence_status"], "inspect_segments_before_claim")

    def test_transcriptapi_retries_one_transient_failure_without_leaking_key(
        self,
    ) -> None:
        requests = []
        sleeps = []

        def transport(request, timeout):
            requests.append(request)
            if len(requests) == 1:
                return (
                    503,
                    {},
                    json.dumps(
                        {
                            "detail": "temporary",
                            "retryable": True,
                            "credits_refunded": True,
                        }
                    ).encode(),
                )
            return (
                200,
                {},
                json.dumps(
                    {"video_id": "dQw4w9WgXcQ", "transcript": []}
                ).encode(),
            )

        with patch.dict(
            os.environ,
            {community_sources.TRANSCRIPTAPI_KEY_ENV: "fixture-transcript-secret"},
            clear=False,
        ):
            payload = community_sources.transcriptapi_get_json(
                "/transcript",
                {"video_id": "dQw4w9WgXcQ"},
                transport=transport,
                sleep=sleeps.append,
            )

        query = parse_qs(urlsplit(requests[0].full_url).query)
        headers = dict(requests[0].header_items())
        self.assertEqual(query["video_id"], ["dQw4w9WgXcQ"])
        self.assertEqual(headers["Authorization"], "Bearer fixture-transcript-secret")
        self.assertNotIn("fixture-transcript-secret", requests[0].full_url)
        self.assertNotIn("fixture-transcript-secret", json.dumps(payload))
        self.assertEqual(len(requests), 2)
        self.assertEqual(sleeps, [1.5])

    def test_transcriptapi_does_not_retry_permanent_video_error(self) -> None:
        calls = 0

        def transport(request, timeout):
            nonlocal calls
            calls += 1
            return (
                404,
                {},
                json.dumps(
                    {
                        "error": "TranscriptsDisabled",
                        "retryable": False,
                        "credits_refunded": True,
                    }
                ).encode(),
            )

        with patch.dict(
            os.environ,
            {community_sources.TRANSCRIPTAPI_KEY_ENV: "fixture-transcript-secret"},
            clear=False,
        ):
            with self.assertRaises(community_sources.ProviderError) as raised:
                community_sources.transcriptapi_get_json(
                    "/transcript",
                    {"video_id": "dQw4w9WgXcQ"},
                    transport=transport,
                )
        self.assertEqual(calls, 1)
        self.assertEqual(raised.exception.provider_code, "TranscriptsDisabled")
        self.assertFalse(raised.exception.retryable)
        self.assertTrue(raised.exception.credits_refunded)

    def test_transcriptapi_retries_rate_limit_with_bounded_retry_after(self) -> None:
        calls = 0
        sleeps = []

        def transport(request, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                return (
                    429,
                    {"Retry-After": "120"},
                    json.dumps({"retryable": True}).encode(),
                )
            return (
                200,
                {},
                json.dumps(
                    {"video_id": "dQw4w9WgXcQ", "transcript": []}
                ).encode(),
            )

        with patch.dict(
            os.environ,
            {community_sources.TRANSCRIPTAPI_KEY_ENV: "fixture-transcript-secret"},
            clear=False,
        ):
            community_sources.transcriptapi_get_json(
                "/transcript",
                {"video_id": "dQw4w9WgXcQ"},
                transport=transport,
                sleep=sleeps.append,
            )

        self.assertEqual(calls, 2)
        self.assertEqual(
            sleeps,
            [community_sources.TRANSCRIPTAPI_MAX_RETRY_DELAY_SECONDS],
        )

    def test_public_youtube_transcript_is_explicit_and_preserves_track_metadata(
        self,
    ) -> None:
        def fetcher(video_id, languages):
            self.assertEqual(video_id, "dQw4w9WgXcQ")
            self.assertEqual(languages, ["en"])
            return (
                [{"start": 4.0, "duration": 3.5, "text": "Public caption"}],
                {
                    "language_code": "en",
                    "language": "English (auto-generated)",
                    "is_generated": True,
                },
            )

        result = community_sources.public_youtube_transcript(
            "dQw4w9WgXcQ", language="en", fetcher=fetcher
        )
        item = result["results"][0]
        self.assertEqual(result["provider"], "youtube_public_captions")
        self.assertEqual(result["operation"], "youtube_public_transcript")
        self.assertEqual(result["query_context"]["fallback_role"], "explicit_reserve")
        self.assertEqual(item["caption_provider"], "youtube_public_captions")
        self.assertTrue(item["caption_track"]["is_generated"])
        self.assertTrue(any("not a hidden" in warning for warning in result["warnings"]))

    def test_public_youtube_transcript_redacts_library_failure(self) -> None:
        def fetcher(video_id, languages):
            raise RuntimeError("sensitive upstream details")

        with self.assertRaises(community_sources.ProviderError) as raised:
            community_sources.public_youtube_transcript(
                "dQw4w9WgXcQ", fetcher=fetcher
            )
        self.assertEqual(raised.exception.provider, "youtube_public_captions")
        self.assertNotIn("sensitive", str(raised.exception))

    def test_local_tinyfish_rate_limiter_is_fail_fast(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cache_dir = Path(temp)
            community_sources.reserve_rate_capacity(
                "search", 30, 30, cache_dir=cache_dir, now=1000.0
            )
            with self.assertRaises(community_sources.ProviderError) as raised:
                community_sources.reserve_rate_capacity(
                    "search", 1, 30, cache_dir=cache_dir, now=1000.0
                )
            self.assertEqual(raised.exception.status, 429)
            self.assertIsNotNone(raised.exception.retry_after)

    def test_doctor_reports_presence_without_emitting_secret_values(self) -> None:
        with patch.dict(
            os.environ,
            {
                community_sources.REDDIT_KEY_ENV: "test-reddit-secret",
                community_sources.GETX_KEY_ENV: "test-x-secret",
                community_sources.TRANSCRIPTAPI_KEY_ENV: "test-transcript-secret",
                community_sources.TINYFISH_KEY_ENV: "test-tinyfish-secret",
            },
            clear=False,
        ):
            result = community_sources.doctor()
        rendered = json.dumps(result)
        self.assertTrue(result["redditapi"]["configured"])
        self.assertTrue(result["getxapi"]["configured"])
        self.assertTrue(result["transcriptapi"]["configured"])
        self.assertEqual(
            result["youtube_public_captions"]["optional_dependency"],
            "youtube-transcript-api",
        )
        self.assertTrue(result["tinyfish"]["api_key_configured"])
        self.assertNotIn("test-reddit-secret", rendered)
        self.assertNotIn("test-x-secret", rendered)
        self.assertNotIn("test-transcript-secret", rendered)
        self.assertNotIn("test-tinyfish-secret", rendered)

    def test_tinyfish_rest_search_uses_x_api_key_without_cli(self) -> None:
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"results": [], "total_results": 0}'

        with patch.dict(os.environ, {community_sources.TINYFISH_KEY_ENV: "test-tinyfish-secret"}), \
            patch.object(community_sources.shutil, "which", return_value=None), \
            patch.object(community_sources, "urlopen", return_value=FakeResponse()) as opened:
            payload = community_sources.tinyfish_search("test query", 0, language="en")

        request = opened.call_args.args[0]
        self.assertEqual(request.headers["X-api-key"], "test-tinyfish-secret")
        self.assertIn("query=test+query", request.full_url)
        self.assertEqual(payload["total_results"], 0)

    def test_stats_api_is_read_only_and_keeps_freshness_metadata(self) -> None:
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=None):
                return b'{"data": [{"archetype": "Example"}], "meta": {"stale": false, "fetched_at": "2026-08-30T00:00:00Z"}}'

        arguments = community_sources.build_parser().parse_args(
            [
                "stats-api",
                "--operation",
                "constructed-archetypes",
                "--q",
                "Example",
                "--limit",
                "1",
            ]
        )
        with patch.object(community_sources, "urlopen", return_value=FakeResponse()) as opened:
            result = community_sources.execute(arguments)

        request = opened.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(urlparse(request.full_url).path, "/v1/constructed/archetypes")
        self.assertEqual(
            parse_qs(urlparse(request.full_url).query),
            {"q": ["Example"], "limit": ["1"], "offset": ["0"]},
        )
        self.assertEqual(result["provider"], "koloda_stats_api")
        self.assertEqual(result["results"][0]["api_meta"]["stale"], False)
        self.assertEqual(result["results"][0]["evidence_status"], "first_party_cached_dataset")

    def test_hsguru_source_id_uses_hsguru_meta_route_and_query_aliases(self) -> None:
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=None):
                return b'{"data": {"items": []}, "meta": {"source_id": "hsguru_meta_matrix"}}'

        arguments = community_sources.build_parser().parse_args(
            [
                "stats-api",
                "--operation",
                "hsguru-meta",
                "--source-id",
                "hsguru_meta_standard_legend",
                "--period",
                "past_day",
                "--min-games",
                "100",
            ]
        )
        with patch.object(community_sources, "urlopen", return_value=FakeResponse()) as opened:
            result = community_sources.execute(arguments)

        request = opened.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(urlparse(request.full_url).path, "/v1/hsguru/meta")
        self.assertEqual(
            parse_qs(urlparse(request.full_url).query),
            {
                "format": ["standard"],
                "rank": ["legend"],
                "period": ["past_day"],
                "min_games": ["100"],
            },
        )
        self.assertEqual(result["results"][0]["api_meta"]["source_id"], "hsguru_meta_matrix")

    def test_reads_one_named_metastats_dataset_without_accepting_a_url(self) -> None:
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit=None):
                return b'{"source_id":"metastats_decks","fetched_at":"2026-08-31T16:00:24Z","publication":{"state":"published"},"data":{"tables":[]}}'

        arguments = community_sources.build_parser().parse_args(
            [
                "stats-api",
                "--operation",
                "dataset",
                "--source-id",
                "metastats_decks",
            ]
        )
        with patch.object(community_sources, "urlopen", return_value=FakeResponse()) as opened:
            result = community_sources.execute(arguments)

        request = opened.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(urlparse(request.full_url).path, "/datasets/metastats_decks")
        self.assertEqual(urlparse(request.full_url).query, "")
        self.assertEqual(result["results"][0]["api_meta"]["source_id"], "metastats_decks")
        self.assertEqual(result["results"][0]["data"], {"tables": []})

        invalid = community_sources.build_parser().parse_args(
            [
                "stats-api",
                "--operation",
                "dataset",
                "--source-id",
                "../../admin",
            ]
        )
        with self.assertRaisesRegex(community_sources.ProviderError, "source_id"):
            community_sources.execute(invalid)


if __name__ == "__main__":
    unittest.main()
