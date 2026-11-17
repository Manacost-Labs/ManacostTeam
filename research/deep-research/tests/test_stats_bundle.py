#!/usr/bin/env python3
"""Offline tests for the Koloda statistics bundle (no live network)."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
MODULE_PATH = ROOT / "scripts/community_sources.py"
SPEC = importlib.util.spec_from_file_location("community_sources_bundle", MODULE_PATH)
assert SPEC and SPEC.loader
community_sources = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(community_sources)


class FakeResponse:
    status = 200

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=None):
        return self.body


def endpoint_body(count: int, rows: int, *, stale: bool = False) -> bytes:
    return json.dumps(
        {
            "data": [{"card_id": f"BG_{index}", "name_ru": "Существо"} for index in range(rows)],
            "meta": {
                "source_id": "hsreplay_battlegrounds_minions",
                "fetched_at": "2026-11-16T02:45:09Z",
                "stale": stale,
                "count": count,
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")


def dataset_body(source_id: str) -> bytes:
    return json.dumps(
        {
            "source_id": source_id,
            "fetched_at": "2026-11-17T17:00:12Z",
            "data": {"source_id": source_id, "structured": {"type": "x"}},
        }
    ).encode("utf-8")


class StatsBundleTest(unittest.TestCase):
    def run_bundle(self, mode: str, responder):
        requests = []

        def fake_urlopen(request, timeout=None):
            requests.append(request)
            return responder(request.full_url)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "bundle"
            arguments = community_sources.build_parser().parse_args(
                ["stats-bundle", "--mode", mode, "--output", str(output)]
            )
            with patch.object(community_sources, "urlopen", side_effect=fake_urlopen):
                manifest = community_sources.execute(arguments)
            files = {path.name: path.read_bytes() for path in output.iterdir()}
        return manifest, files, requests

    def test_battlegrounds_bundle_saves_canonical_set_with_hashes(self) -> None:
        def responder(url: str) -> FakeResponse:
            path = urlsplit(url).path
            if path.startswith("/datasets/"):
                return FakeResponse(dataset_body(path.removeprefix("/datasets/")))
            return FakeResponse(endpoint_body(count=3, rows=3, stale=path.endswith("minions")))

        manifest, files, requests = self.run_bundle("battlegrounds", responder)

        self.assertTrue(all(request.method == "GET" for request in requests))
        self.assertEqual(
            [urlsplit(request.full_url).path for request in requests],
            [
                "/v1/battlegrounds/minions",
                "/v1/battlegrounds/heroes",
                "/datasets/firestone_battlegrounds_cards",
                "/datasets/firestone_battlegrounds_comps",
                "/datasets/hsreplay_battlegrounds_trinkets_all_current_battlegrounds_patch",
                "/datasets/hsreplay_battlegrounds_trinkets_top_1_percent_current_battlegrounds_patch",
            ],
        )
        self.assertEqual(parse_qs(urlsplit(requests[0].full_url).query), {"limit": ["500"]})
        self.assertEqual(urlsplit(requests[2].full_url).query, "")
        self.assertEqual(manifest["mode"], "battlegrounds")
        self.assertEqual(manifest["failures"], [])
        self.assertIn(community_sources.STATS_BUNDLE_MANIFEST, files)
        saved = json.loads(files[community_sources.STATS_BUNDLE_MANIFEST].decode("utf-8"))
        self.assertEqual(saved["files"], manifest["files"])
        for entry in manifest["files"]:
            body = files[entry["path"]]
            self.assertEqual(entry["sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(entry["bytes"], len(body))
            # A sources.json row is the entry plus the file text; the hash must survive.
            text = body.decode("utf-8")
            self.assertEqual(entry["sha256"], hashlib.sha256(text.encode("utf-8")).hexdigest())
            self.assertEqual(entry["access"], "public")
            self.assertEqual(entry["source"], "api.kolodahearthstone.com")
            self.assertTrue(entry["id"].startswith("koloda-"))
            self.assertTrue(entry["retrieved_at"])
        minions = manifest["files"][0]
        self.assertEqual(minions["path"], "battlegrounds-minions.json")
        self.assertIs(minions["api_stale"], True)
        self.assertEqual(minions["api_fetched_at"], "2026-11-16T02:45:09Z")
        self.assertEqual(minions["rows"], 3)
        self.assertTrue(any("stale" in warning for warning in manifest["warnings"]))
        cards = manifest["files"][2]
        self.assertEqual(cards["path"], "firestone_battlegrounds_cards.json")
        self.assertEqual(cards["api_source_id"], "firestone_battlegrounds_cards")
        self.assertIsNone(cards["api_stale"])

    def test_ladder_bundle_uses_rank_pairs(self) -> None:
        def responder(url: str) -> FakeResponse:
            return FakeResponse(dataset_body(urlsplit(url).path.removeprefix("/datasets/")))

        manifest, _files, _requests = self.run_bundle("wild", responder)
        self.assertEqual(
            [entry["name"] for entry in manifest["files"]],
            [
                "hsguru_meta_wild_diamond_4to1",
                "hsguru_meta_wild_legend",
                "hsguru_meta_wild_top_5k",
                "hsguru_meta_wild_top_legend",
            ],
        )

    def test_truncated_endpoint_is_reported(self) -> None:
        def responder(url: str) -> FakeResponse:
            path = urlsplit(url).path
            if path.startswith("/datasets/"):
                return FakeResponse(dataset_body(path.removeprefix("/datasets/")))
            return FakeResponse(endpoint_body(count=700, rows=500))

        manifest, _files, _requests = self.run_bundle("arena", responder)
        self.assertTrue(any("truncated" in warning for warning in manifest["warnings"]))

    def test_partial_failure_is_kept_in_manifest(self) -> None:
        def responder(url: str) -> FakeResponse:
            path = urlsplit(url).path
            if path.endswith("heartharena_tierlist"):
                raise URLError("offline")
            if path.endswith("firestone_arena_cards_normal"):
                return FakeResponse(b"<html>blocked</html>")
            if path.startswith("/datasets/"):
                return FakeResponse(dataset_body(path.removeprefix("/datasets/")))
            return FakeResponse(endpoint_body(count=1, rows=1))

        manifest, files, _requests = self.run_bundle("arena", responder)
        self.assertEqual(
            sorted(failure["name"] for failure in manifest["failures"]),
            ["firestone_arena_cards_normal", "heartharena_tierlist"],
        )
        self.assertNotIn("heartharena_tierlist.json", files)
        self.assertNotIn("firestone_arena_cards_normal.json", files)
        self.assertEqual(len(manifest["files"]), 2)

    def test_all_failures_raise_provider_error(self) -> None:
        def responder(_url: str) -> FakeResponse:
            raise URLError("offline")

        with self.assertRaises(community_sources.ProviderError):
            self.run_bundle("standard", responder)

    def test_oversized_response_is_rejected(self) -> None:
        with patch.object(community_sources, "STATS_BUNDLE_MAX_RESPONSE_BYTES", 10):
            with patch.object(
                community_sources, "urlopen", return_value=FakeResponse(b"x" * 11)
            ):
                with self.assertRaisesRegex(community_sources.ProviderError, "too large"):
                    community_sources.stats_api_get_bytes(
                        "https://api.kolodahearthstone.com/v1/health", max_bytes=10
                    )

    def test_unknown_mode_is_rejected_by_parser(self) -> None:
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            community_sources.build_parser().parse_args(
                ["stats-bundle", "--mode", "duels", "--output", "x"]
            )


if __name__ == "__main__":
    unittest.main()
