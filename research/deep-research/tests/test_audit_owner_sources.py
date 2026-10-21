"""The owner audit accounts for access scope without claiming video inspection."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_owner_sources as audit
from source_library import required_sources


class OwnerAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fake(self, url, *args, **kwargs):
        channel = "youtube.com/" in url
        feed = url.endswith(("/rss", ".xml"))
        return {
            "verdict": "OK",
            "url": url,
            "final_url": url,
            "provider": "transcriptapi-channel"
            if channel
            else "native"
            if feed
            else "scrape-super",
            "cache": "HIT",
            "text": "<rss><channel><item><title>Episode</title><guid>one</guid></item></channel></rss>"
            if feed
            else "Public content",
            "data": {"videos": [{"id": "one"}]} if channel else {},
        }

    def test_every_registered_source_has_one_receipt_and_explicit_scope(self):
        client = Mock()
        client.collect.side_effect = self.fake
        with redirect_stdout(io.StringIO()):
            result = audit.audit(client, self.root)
        self.assertEqual(
            result["accounting"],
            {
                "input": 39,
                "accounted": 39,
                "unaccounted": 0,
                "missing_ids": [],
                "duplicate_ids": [],
            },
        )
        self.assertEqual(
            {r["id"] for r in result["results"]}, {r["id"] for r in required_sources()}
        )
        self.assertEqual(len(list(self.root.glob("*-receipt.json"))), 39)
        channels = [
            r
            for r in result["results"]
            if r["coverage_level"] == "channel_discovery_only"
        ]
        self.assertEqual(len(channels), 23)
        self.assertTrue(
            all("captions not inspected" in r["limitation"] for r in channels)
        )
        self.assertTrue(all(not r["evidence_validated"] for r in result["results"]))
        self.assertTrue(
            json.loads(
                (self.root / "owner-source-coverage-validation.json").read_text(
                    encoding="utf8"
                )
            )["checklist_complete"]
        )

    def test_adapter_error_is_accounted_without_disclosing_exception_text(self):
        sources = [
            {"id": "one", "owner_urls": ["https://a.example/"]},
            {"id": "two", "owner_urls": ["https://b.example/"]},
        ]
        client = Mock()
        client.collect.side_effect = [
            RuntimeError("secret exception"),
            self.fake("https://b.example/"),
        ]
        with redirect_stdout(io.StringIO()):
            result = audit.audit(client, self.root, sources=sources)
        self.assertEqual(result["accounting"]["unaccounted"], 0)
        self.assertEqual(result["results"][0]["verdict"], "AUDIT_ERROR")
        self.assertEqual(result["results"][1]["verdict"], "OK")
        self.assertNotIn("secret exception", json.dumps(result))
        self.assertTrue((self.root / "one-receipt.json").exists())

    def test_bilibili_search_fallback_keeps_original_source_identity(self):
        source = {"id": "bilibili", "owner_urls": ["https://www.bilibili.com/"]}
        client = Mock()
        client.collect.side_effect = [
            {"verdict": "BLOCKED"},
            self.fake(audit.FALLBACKS["bilibili"]),
        ]
        with redirect_stdout(io.StringIO()):
            result = audit.audit(client, self.root, sources=[source])
        row = result["results"][0]
        self.assertEqual(row["owner_url"], source["owner_urls"][0])
        self.assertEqual(row["selected_url"], audit.FALLBACKS["bilibili"])
        self.assertEqual(
            len(
                json.loads(
                    (self.root / "bilibili-receipt.json").read_text(encoding="utf8")
                )["collection_results"]
            ),
            2,
        )

    def test_podcast_archive_is_checked_by_identity_without_rewriting(self):
        archive = self.root / "archive"
        archive.mkdir()
        path = archive / "one.json"
        original = json.dumps(
            {"series": "podcast", "episode_id": "one", "archive_key": "stable"}
        ).encode()
        path.write_bytes(original)
        result = audit.archive_match(
            self.fake("https://podcast.example/rss"), "podcast", archive
        )
        self.assertEqual(result["status"], "PRESENT")
        self.assertEqual(result["archive_key"], "stable")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(
            audit.archive_match(
                self.fake("https://podcast.example/rss"), "different", archive
            )["status"],
            "NOT_ARCHIVED",
        )

    def test_generic_homepage_does_not_hide_failed_topic_search(self):
        source = {"id": "bilibili", "owner_urls": ["https://www.bilibili.com/"]}
        client = Mock()
        client.collect.side_effect = [
            self.fake(source["owner_urls"][0]),
            {"verdict": "BLOCKED"},
        ]
        with redirect_stdout(io.StringIO()):
            result = audit.audit(client, self.root, sources=[source])
        self.assertEqual(
            result["results"][0]["coverage_level"], "generic_homepage_only"
        )
        self.assertIn("not topic coverage", result["results"][0]["limitation"])


if __name__ == "__main__":
    unittest.main()
