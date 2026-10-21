"""Focused behavioral tests for the durable source/transcript library."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import source_library as library


class SourceLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.metadata = {
            "source_url": "https://coinconcede.com/episode/",
            "title": "Episode",
        }
        self.payload = {
            "provider": "publisher",
            "segments": [
                {"start": 1, "end": 5, "text": "Mulligan advice with conditions."}
            ],
        }

    def cache(self, producer, **kwargs):
        return library.cached_transcript(
            self.root,
            "coin-concede",
            "guid-one",
            "en",
            producer,
            metadata=self.metadata,
            **kwargs,
        )

    def test_owner_registry_contains_all_39_exact_urls(self):
        records = library.required_sources()
        urls = {u for item in records for u in item["owner_urls"]}
        self.assertEqual(len(records), 39)
        expected_handles = {
            "HearthTech7354",
            "BreadandButterHs",
            "Shadybunny",
            "xqn_thesad",
            "JeefHS",
            "guddumpog",
            "Shadybunny2",
            "RduHS",
            "Slyders_HS",
            "dogdogtwitch",
            "Sevel07",
            "guddummit",
            "AsmodaiTV",
            "RechotGames/videos",
            "ZeddyHearthstone",
            "MarkMcKz",
            "KrisOFiveHearthstone",
            "ThijsTCG",
            "FunkiMonki",
            "HearthstoneMathematics",
            "ChumpHS",
            "RegisHearthbin",
            "Warshack",
        }
        expected_sites = {
            "https://www.hearthstone-decks.com/",
            "https://hearthstone.judgehype.com/",
            "https://hs.blizzard.cn/",
            "https://www.ptt.cc/bbs/Hearthstone/index.html",
            "https://forum.gamer.com.tw/B.php?bsn=24044",
            "https://outof.games/realms/hearthstone/",
            "https://www.hearthpwn.com/decks",
            "https://www.hearthpwn.com/forums",
            "https://www.bilibili.com/",
            "https://note.com/",
            "https://coinconcede.com/episodes/",
            "https://www.borntobewildhs.com/podcast",
            "https://beerbrick.com/category/deck/",
            "https://hs.inven.co.kr/",
            "https://hearthstonecommute.libsyn.com/",
            "https://www.vicioussyndicate.com/data-reaper-podcast/",
        }
        self.assertEqual(
            urls,
            expected_sites
            | {f"https://www.youtube.com/@{h}" for h in expected_handles},
        )

    def test_planned_or_missing_attempts_never_count_as_completed(self):
        plan = library.checklist()
        report = library.coverage(plan)
        self.assertEqual(len(report["pending"]), 39)
        self.assertFalse(report["checklist_complete"])
        plan["sources"][0]["status"] = "inspected"
        report = library.coverage(plan)
        self.assertTrue(report["invalid"])
        self.assertFalse(report["evidence_validated"])

    def test_all_outcomes_require_real_attempt_and_reason_or_material(self):
        plan = library.checklist()
        for item in plan["sources"]:
            item.update(
                status="blocked",
                query="topic query",
                attempted_at="2026-10-21T10:00:00Z",
                reason="HTTP 403",
            )
        self.assertTrue(library.coverage(plan)["checklist_complete"])
        plan["sources"][0].update(status="inspected", reason=None)
        self.assertTrue(library.coverage(plan)["invalid"])
        plan["sources"][0]["inspected_urls"] = ["https://example.com/article"]
        self.assertTrue(library.coverage(plan)["checklist_complete"])
        plan["sources"].append(plan["sources"][0])
        self.assertTrue(library.coverage(plan)["invalid"])

    def test_second_run_uses_archive_without_calling_producer(self):
        producer = Mock(return_value=self.payload)
        first = self.cache(producer)
        second = self.cache(producer)
        producer.assert_called_once_with()
        self.assertEqual(first["cache"], "MISS")
        self.assertEqual(second["cache"], "HIT")
        self.assertEqual(
            second["record"]["segments"][0]["text"], self.payload["segments"][0]["text"]
        )
        self.assertEqual(second["record"]["metadata"], self.metadata)

    def test_cached_youtube_alias_does_not_contact_any_provider(self):
        envelope = {
            "provider": "transcriptapi",
            "results": [{"segments": self.payload["segments"]}],
        }
        with (
            patch.object(library, "transcriptapi_get_json", return_value={}) as request,
            patch.object(
                library, "normalize_youtube_transcript", return_value=envelope
            ),
        ):
            first = library.youtube_transcript(
                self.root, "https://youtu.be/abcdefghijk?t=20"
            )
            second = library.youtube_transcript(
                self.root, "https://www.youtube.com/watch?v=abcdefghijk"
            )
        request.assert_called_once()
        self.assertEqual(first["path"], second["path"])
        self.assertEqual(second["cache"], "HIT")

    def test_audio_cache_survives_missing_audio_and_missing_runtime(self):
        self.cache(lambda: self.payload)
        with patch.object(
            library, "local_transcription", side_effect=AssertionError("ASR called")
        ):
            code = library.main(
                [
                    "--library",
                    str(self.root),
                    "transcribe",
                    "--series",
                    "coin-concede",
                    "--episode-id",
                    "guid-one",
                    "--language",
                    "en",
                    "--source-url",
                    self.metadata["source_url"],
                    "--audio",
                    str(self.root / "absent.mp3"),
                ]
            )
        self.assertEqual(code, 0)

    def test_explicit_refresh_preserves_previous_version(self):
        first = self.cache(lambda: self.payload)
        newer = {
            "provider": "publisher",
            "segments": [{"start": 2, "end": 9, "text": "Corrected."}],
        }
        updated = self.cache(lambda: newer, refresh=True)
        revisions = list((self.root / "revisions").glob("*.json"))
        self.assertEqual(len(revisions), 1)
        self.assertEqual(
            library.read_archive(revisions[0])["record_sha256"],
            first["record"]["record_sha256"],
        )
        self.assertEqual(updated["cache"], "REFRESH")
        self.assertEqual(
            library.read_archive(Path(updated["path"]))["segments"][0]["text"],
            "Corrected.",
        )

    def test_failed_refresh_preserves_existing_archive(self):
        first = self.cache(lambda: self.payload)
        original = Path(first["path"]).read_bytes()
        with self.assertRaises(ValueError):
            self.cache(lambda: {"provider": "publisher", "segments": []}, refresh=True)
        self.assertEqual(Path(first["path"]).read_bytes(), original)
        self.assertFalse(list(self.root.glob(".*.lock")))

    def test_corrupted_archive_does_not_trigger_paid_retry(self):
        first = self.cache(lambda: self.payload)
        path = Path(first["path"])
        modified = json.loads(path.read_text(encoding="utf-8"))
        modified["segments"][0]["text"] = "Changed"
        path.write_text(json.dumps(modified), encoding="utf-8")
        producer = Mock(side_effect=AssertionError("must not call provider"))
        with self.assertRaises(ValueError):
            self.cache(producer)
        producer.assert_not_called()

    def test_empty_or_invalid_transcript_is_never_cached(self):
        cases = [
            [],
            [{"start": -1, "end": 1, "text": "Text"}],
            [{"start": 0, "end": float("nan"), "text": "Text"}],
            [{"start": 4, "end": 1, "text": "Text"}],
            [{"start": 0, "end": 1, "text": " "}],
        ]
        for case_index, segments in enumerate(cases):
            with self.subTest(case=case_index):
                with self.assertRaises(ValueError):
                    self.cache(
                        lambda segments=segments: {
                            "provider": "publisher",
                            "segments": segments,
                        }
                    )
                self.assertFalse(list(self.root.glob("*.json")))

    def test_concurrent_episode_lock_prevents_provider_call(self):
        key = library.archive_key("coin-concede", "guid-one", "en")
        (self.root / f".{key}.lock").mkdir()
        producer = Mock()
        with self.assertRaises(ValueError):
            self.cache(producer)
        producer.assert_not_called()

    def test_search_preserves_exact_text_timestamps_and_source(self):
        self.cache(lambda: self.payload)
        matches = library.search_archive(self.root, "MULLIGAN")
        self.assertEqual(
            matches[0]["metadata"]["source_url"], self.metadata["source_url"]
        )
        self.assertEqual(
            matches[0]["segments"],
            [{"start": 1.0, "end": 5.0, "text": "Mulligan advice with conditions."}],
        )
        self.assertEqual(library.search_archive(self.root, "not present"), [])

    def test_rss_keeps_guid_date_enclosure_and_publisher_transcript(self):
        rss = b"""<rss xmlns:podcast="https://podcastindex.org/namespace/1.0"><channel><item>
        <title>Episode 568</title><guid>stable-guid</guid><link>https://example.com/568</link>
        <pubDate>Mon, 19 Oct 2026 10:00:00 GMT</pubDate>
        <enclosure url="https://example.com/568.mp3" type="audio/mpeg"/>
        <podcast:transcript url="https://example.com/568.vtt" type="text/vtt" language="en"/>
        </item></channel></rss>"""
        item = library.parse_feed(rss, "https://example.com/rss")[0]
        self.assertEqual(item["episode_id"], "stable-guid")
        self.assertEqual(item["audio_url"], "https://example.com/568.mp3")
        self.assertEqual(item["publisher_transcripts"][0]["type"], "text/vtt")
        self.assertEqual(item["status"], "discovery_only")
        self.assertEqual(item["published_at"], "Mon, 19 Oct 2026 10:00:00 GMT")

    def test_atom_and_empty_feed_remain_discovery(self):
        atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>stable-id</id>
        <title>Episode</title><link href="https://example.com/episode"/>
        <link rel="enclosure" href="https://example.com/audio.mp3"/>
        <published>2026-10-21T00:00:00Z</published></entry></feed>"""
        item = library.parse_feed(atom, "https://example.com/atom")[0]
        self.assertEqual(item["source_url"], "https://example.com/episode")
        self.assertEqual(item["audio_url"], "https://example.com/audio.mp3")
        self.assertEqual(item["episode_id"], "stable-id")
        self.assertEqual(
            library.parse_feed(b"<rss><channel/></rss>", "https://example.com/rss"), []
        )

    def test_source_host_and_credential_guards_before_network(self):
        with patch("chinese_hearthstone.ScrapeDoClient") as client:
            for case_index, (sid, url) in enumerate(
                [
                    ("unknown", "https://example.com/"),
                    ("hearthpwn-decks", "https://hearthpwn.com.attacker.example/"),
                    ("hearthpwn-decks", "https://www.hearthpwn.com/?token=secret"),
                    ("hearthpwn-decks", "https://user:password@www.hearthpwn.com/"),
                ]
            ):
                with self.subTest(case=case_index), self.assertRaises(ValueError):
                    library.fetch_source(sid, url)
            client.assert_not_called()

    def test_metadata_and_language_identity_prevent_false_cache_hits(self):
        first = self.cache(lambda: self.payload)
        other = library.cached_transcript(
            self.root,
            "coin-concede",
            "guid-one",
            "fr",
            lambda: self.payload,
            metadata=self.metadata,
        )
        self.assertNotEqual(first["path"], other["path"])
        producer = Mock()
        with self.assertRaises(ValueError):
            library.cached_transcript(self.root, "series", "guid", "en", producer)
        producer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
