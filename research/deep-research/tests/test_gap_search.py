"""Breadth targets and actual work queues for the next research pass."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import platform_coverage


class GapSearchTests(unittest.TestCase):
    def records(self):
        queries = [
            {
                "query_id": "QRY-0001",
                "family": "youtube",
                "language": "en",
                "status": "completed",
                "executed_at": "2026-10-03",
                "deliverable_section_ids": ["SEC-1"],
                "result_source_ids": ["SRC-1", "SRC-2"],
            }
        ]
        sources = [
            {
                "source_id": "SRC-1",
                "url": "https://youtu.be/demo",
                "access_integrity": "transcript",
            },
            {
                "source_id": "SRC-2",
                "url": "https://youtube.com/watch?v=demo&t=120",
                "access_integrity": "transcript",
            },
        ]
        return queries, sources

    def test_share_variants_cannot_satisfy_a_breadth_target(self):
        queries, sources = self.records()
        report = platform_coverage.analyze_records(
            queries,
            sources,
            required=["youtube"],
            min_inspected={"youtube": 2},
            sections=["SEC-1"],
            languages=["en"],
        )
        self.assertEqual(report["verdict"], "partial")
        gap = report["gap_details"][0]
        self.assertEqual(
            (gap["reason"], gap["inspected_sources"], gap["minimum_inspected"]),
            ("insufficient_inspections", 1, 2),
        )
        sources[1]["url"] = "https://youtu.be/another"
        self.assertEqual(
            platform_coverage.analyze_records(
                queries,
                sources,
                required=["youtube"],
                min_inspected={"youtube": 2},
            )["verdict"],
            "covered",
        )

    def test_breadth_targets_are_validated(self):
        for target in [{"unknown": 2}, {"x": 0}, {"x": True}, {"x": "2"}]:
            with self.subTest(target=target), self.assertRaises(ValueError):
                platform_coverage.analyze_records(
                    [], [], required=["x"], min_inspected=target
                )

    def test_executed_and_skipped_statuses_from_the_bundle_contract_are_supported(self):
        queries, sources = self.records()
        queries[0]["status"] = "executed"
        self.assertEqual(
            platform_coverage.analyze_records(
                queries,
                sources,
                required=["youtube"],
            )["verdict"],
            "covered",
        )
        queries[0]["status"] = "skipped"
        self.assertEqual(
            platform_coverage.analyze_records(
                queries,
                sources,
                required=["youtube"],
            )["verdict"],
            "partial",
        )

    def test_target_failure_is_not_hidden_by_unrelated_scope_gaps(self):
        queries, sources = self.records()
        report = platform_coverage.analyze_records(
            queries,
            sources,
            required=["youtube"],
            min_inspected={"youtube": 2},
            sections=["SEC-1", "SEC-2"],
            languages=["en"],
        )
        self.assertEqual(
            {gap["section_id"] for gap in report["gap_details"]}, {"SEC-1", "SEC-2"}
        )

    def bundle(self, root):
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "main_question": "Hearthstone strategy",
                    "depth": "deep",
                    "as_of": "2026-10-03",
                    "coverage_contract_version": "1.0",
                    "current_context": {"patch": "36.6"},
                }
            ),
            encoding="utf-8",
        )
        (root / "plan.json").write_text(
            json.dumps(
                {
                    "deliverable_outline": [
                        {
                            "section_id": "SEC-1",
                            "working_title": "Hearthstone mulligan",
                        },
                        {
                            "section_id": "SEC-2",
                            "working_title": "Hearthstone matchups",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        query = {
            "query_id": "QRY-0001",
            "family": "youtube",
            "target_platform": "youtube",
            "language": "en",
            "query": "site:youtube.com Hearthstone mulligan mistakes",
            "topic": "Hearthstone mulligan",
            "status": "planned",
            "pass": "discovery",
            "deliverable_section_ids": ["SEC-1"],
        }
        (root / "query-plan.jsonl").write_text(
            json.dumps(query) + "\n", encoding="utf-8"
        )
        return query

    def run_plan(self, root, *args):
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "plan_queries.py"),
                str(root),
                "--coverage-gaps",
                "--json",
                *args,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_gap_queue_reuses_pending_ids_and_includes_unsearched_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pending = self.bundle(root)
            result = self.run_plan(root)
            self.assertEqual(result.returncode, 0, result.stderr)
            records = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(
                sum(r["query_id"] == pending["query_id"] for r in records), 1
            )
            self.assertEqual(
                {s for r in records for s in r["deliverable_section_ids"]},
                {"SEC-1", "SEC-2"},
            )
            self.assertTrue(
                all(
                    r["status"] == "planned" and r["coverage_gap_reason"]
                    for r in records
                )
            )
            self.assertEqual(len({r["query_id"] for r in records}), len(records))
            self.assertEqual(
                (root / "query-plan.jsonl").read_text(encoding="utf-8"),
                json.dumps(pending) + "\n",
            )

    def test_covered_lane_is_excluded_and_completed_queries_are_not_replanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pending = self.bundle(root)
            completed = {
                **pending,
                "status": "completed",
                "executed_at": "2026-10-03",
                "result_source_ids": ["SRC-1"],
            }
            (root / "queries.jsonl").write_text(
                json.dumps(completed) + "\n", encoding="utf-8"
            )
            (root / "sources.jsonl").write_text(
                json.dumps(
                    {
                        "source_id": "SRC-1",
                        "url": "https://youtu.be/demo",
                        "access_integrity": "transcript",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = self.run_plan(root, "--family", "youtube")
            self.assertEqual(result.returncode, 0, result.stderr)
            records = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertTrue(records)
            self.assertTrue(
                all(r["deliverable_section_ids"] == ["SEC-2"] for r in records)
            )
            result = self.run_plan(
                root,
                "--section",
                "SEC-1",
                "--family",
                "youtube",
                "--min-inspected",
                "youtube=2",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            records = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertTrue(records)
            self.assertTrue(all(r["query_id"] != pending["query_id"] for r in records))
            self.assertTrue(
                all(
                    r["coverage_gap_reason"] == "insufficient_inspections"
                    for r in records
                )
            )

    def test_gap_apply_is_idempotent_and_json_output_remains_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.bundle(root)
            first = self.run_plan(root, "--apply")
            self.assertEqual(first.returncode, 0, first.stderr)
            snapshot = (root / "query-plan.jsonl").read_bytes()
            second = self.run_plan(root, "--apply")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual((root / "query-plan.jsonl").read_bytes(), snapshot)
            first_ids = {
                json.loads(line)["query_id"] for line in first.stdout.splitlines()
            }
            second_ids = {
                json.loads(line)["query_id"] for line in second.stdout.splitlines()
            }
            self.assertEqual(first_ids, second_ids)

    def test_explicit_platform_filter_stays_scoped_in_russian(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.bundle(root)
            result = self.run_plan(root, "--family", "youtube", "--language", "ru")
            self.assertEqual(result.returncode, 0, result.stderr)
            records = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertTrue(records)
            self.assertTrue(
                all(
                    r["target_platform"] == "youtube" and r["language"] == "ru"
                    for r in records
                )
            )

    def test_invalid_target_does_not_write_a_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.bundle(root)
            snapshot = (root / "query-plan.jsonl").read_bytes()
            result = self.run_plan(root, "--apply", "--min-inspected", "youtube=0")
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual((root / "query-plan.jsonl").read_bytes(), snapshot)
