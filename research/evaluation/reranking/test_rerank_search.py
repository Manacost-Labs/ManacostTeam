"""Contract tests run without ML packages, network access or model weights."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import rerank_search as ranking


def fixture() -> dict:
    return {
        "provider": "scrape.do",
        "operation": "google-search",
        "query": "игровая редактура",
        "language": "ru",
        "country": "de",
        "start": 10,
        "results": [
            {
                "url": f"https://example.org/{i}",
                "title": f"Материал {i}",
                "snippet": f"Условия {i}",
                "position": i + 11,
                "evidence_status": "discovery_only",
                "custom": {"source": i},
            }
            for i in range(3)
        ],
        "out_of_scope_results": [{"url": "https://outside.example/", "position": 1}],
        "diagnostics": {"route": "fixture", "nested": ["must survive"]},
    }


def raw(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class RerankingContract(unittest.TestCase):
    def test_ranking_keeps_every_result_and_provenance(self):
        payload = fixture()
        original = copy.deepcopy(payload)
        blob = raw(payload)
        scorer = MagicMock(return_value=[-8.0, 4.0, 1.0])
        result = ranking.rerank(blob, scorer)
        self.assertEqual(payload, original)
        self.assertEqual([r["position"] for r in result["results"]], [12, 13, 11])
        for key in payload.keys() - {"results"}:
            self.assertEqual(result[key], payload[key])
        for row in result["results"]:
            before = next(r for r in payload["results"] if r["url"] == row["url"])
            self.assertEqual({k: row[k] for k in before}, before)
        self.assertEqual(
            result["reranking"]["input_sha256"], hashlib.sha256(blob).hexdigest()
        )
        self.assertEqual(
            scorer.call_args.args[0][0], (payload["query"], "Материал 0\nУсловия 0")
        )

    def test_ties_preserve_input_order(self):
        result = ranking.rerank(raw(fixture()), lambda _: [1.0, 1.0, 1.0])
        self.assertEqual([r["position"] for r in result["results"]], [11, 12, 13])

    def test_bounded_prefix_retains_unscored_tail(self):
        payload = fixture()
        result = ranking.rerank(raw(payload), lambda _: [0.0, 2.0], max_candidates=2)
        self.assertEqual([r["position"] for r in result["results"]], [12, 11, 13])
        self.assertEqual(result["results"][-1], payload["results"][-1])
        self.assertEqual(result["reranking"]["unscored_count"], 1)

    def test_bad_scores_fail_without_output(self):
        for scores in (
            [1.0],
            [float("nan"), 1, 2],
            [float("inf"), 1, 2],
            [True, 1, 2],
            ["3", 1, 2],
        ):
            with self.subTest(scores=scores), self.assertRaises(ValueError):
                ranking.rerank(raw(fixture()), lambda _, scores=scores: scores)

    def test_invalid_input_is_rejected_before_model(self):
        bad = []
        for field, value in (
            ("query", ""),
            ("results", {}),
            ("provider", "other"),
            ("operation", "fetch"),
        ):
            p = fixture()
            p[field] = value
            bad.append(p)
        for field, value in (
            ("title", 42),
            ("evidence_status", "verified"),
            ("url", ""),
            ("rerank_score", 1),
        ):
            p = fixture()
            p["results"][0][field] = value
            bad.append(p)
        p = fixture()
        p["results"][0].update(title="", snippet="")
        bad.append(p)
        p = fixture()
        p["reranking"] = {}
        bad.append(p)
        for payload in bad:
            scorer = MagicMock()
            with (
                self.subTest(payload=payload),
                self.assertRaises((ValueError, TypeError)),
            ):
                ranking.rerank(raw(payload), scorer)
            scorer.assert_not_called()

    def test_empty_search_does_not_load_model(self):
        payload = fixture()
        payload["results"] = []
        scorer = MagicMock()
        self.assertEqual(ranking.rerank(raw(payload), scorer)["results"], [])
        scorer.assert_not_called()

    def test_actual_source_access_normalizer_preserves_scope_and_nullable_fields(self):
        scripts = Path(__file__).resolve().parents[2] / "deep-research" / "scripts"
        with patch.object(sys, "path", [str(scripts), *sys.path]):
            access = importlib.import_module("source_access")
        provider_response = {
            "organic_results": [
                {
                    "link": "https://hsguru.com/one",
                    "title": "Только заголовок",
                    "position": 2,
                },
                {
                    "link": "https://hsguru.com/two",
                    "snippet": "Только сниппет",
                    "position": 3,
                },
                {
                    "link": "https://outside.example/",
                    "title": "Вне домена",
                    "position": 1,
                },
            ],
            "search_information": {"query_displayed": "rewritten"},
        }
        with patch.object(
            access, "request", return_value=(raw(provider_response), {"credits": "1"})
        ):
            payload = access.search("статистика", site="hsguru.com", language="ru")
        scorer = MagicMock(return_value=[-1.0, 2.0])
        result = ranking.rerank(raw(payload), scorer)
        self.assertEqual(
            scorer.call_args.args[0],
            [
                ("site:hsguru.com статистика", "Только заголовок"),
                ("site:hsguru.com статистика", "Только сниппет"),
            ],
        )
        self.assertEqual(
            result["out_of_scope_results"], payload["out_of_scope_results"]
        )
        self.assertEqual(result["search_information"], payload["search_information"])
        self.assertEqual(result["diagnostics"], payload["diagnostics"])
        self.assertIsNone(result["results"][0]["title"])
        self.assertIsNone(result["results"][1]["snippet"])
        self.assertEqual([row["position"] for row in result["results"]], [3, 2])

    def test_bad_candidate_limit(self):
        for limit in (0, -1, 101):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                ranking.rerank(raw(fixture()), MagicMock(), max_candidates=limit)

    def test_model_loading_is_pinned_local_and_safetensors(self):
        encoder = MagicMock()
        encoder.return_value.predict.return_value = [-3, 2]
        identity = MagicMock()
        with patch.dict(
            sys.modules,
            {
                "sentence_transformers": MagicMock(CrossEncoder=encoder),
                "torch.nn": MagicMock(Identity=identity),
            },
        ):
            for download in (False, True):
                self.assertEqual(
                    ranking.score_bge(
                        [("q", "a"), ("q", "b")], allow_download=download, batch_size=2
                    ),
                    [-3.0, 2.0],
                )
                options = encoder.call_args.kwargs
                self.assertEqual(options["local_files_only"], not download)
                self.assertEqual(options["revision"], ranking.REVISION)
                self.assertFalse(options["trust_remote_code"])
                self.assertEqual(options["model_kwargs"], {"use_safetensors": True})
                self.assertEqual(options["device"], "cpu")

    def test_cli_protects_input_and_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "search.json"
            source.write_bytes(raw(fixture()))
            destination = Path(directory) / "existing.json"
            destination.write_text("keep me", encoding="utf-8")
            before = source.read_bytes()
            for output in (source, destination):
                with patch.object(ranking, "score_bge") as scorer:
                    self.assertEqual(
                        ranking.main(["--input", str(source), "--output", str(output)]),
                        2,
                    )
                    scorer.assert_not_called()
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(destination.read_text(encoding="utf-8"), "keep me")

    def test_cli_failed_model_never_creates_report(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "search.json"
            source.write_bytes(raw(fixture()))
            output = Path(directory) / "new.json"
            with patch.object(
                ranking, "score_bge", side_effect=OSError("weights unavailable")
            ):
                self.assertEqual(
                    ranking.main(["--input", str(source), "--output", str(output)]), 2
                )
            self.assertFalse(output.exists())

    def test_cli_default_has_no_download_and_leaves_ledgers_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "search.json", root / "ranked.json"
            source.write_bytes(raw(fixture()))
            ledger = root / "candidates.jsonl"
            ledger.write_text("protected ledger", encoding="utf-8")
            with (
                patch.object(
                    ranking, "score_bge", return_value=[0.0, 1.0, -1.0]
                ) as scorer,
                patch.object(ranking, "version", return_value="test"),
            ):
                self.assertEqual(
                    ranking.main(["--input", str(source), "--output", str(output)]), 0
                )
                self.assertFalse(scorer.call_args.kwargs["allow_download"])
            self.assertEqual(ledger.read_text(encoding="utf-8"), "protected ledger")
            self.assertEqual(source.read_bytes(), raw(fixture()))
            self.assertEqual(
                json.loads(output.read_text())["results"][0]["position"], 12
            )

    @unittest.skipUnless(
        os.environ.get("MANACOST_BGE_LIVE_TEST") == "1", "opt-in real cached weights"
    )
    def test_real_cached_model_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = (
                Path(directory) / "search.json",
                Path(directory) / "ranked.json",
            )
            source.write_bytes(raw(fixture()))
            before = source.read_bytes()
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(ranking.__file__)),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=180,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(output.read_text())
            self.assertEqual(result["reranking"]["scored_count"], 3)
            self.assertFalse(result["reranking"]["runtime"]["allow_download"])
            self.assertEqual(source.read_bytes(), before)
            self.assertTrue(
                all(isinstance(r["rerank_score"], float) for r in result["results"])
            )


if __name__ == "__main__":
    unittest.main()
