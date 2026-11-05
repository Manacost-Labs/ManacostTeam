"""Reader decision -> actual search -> inspected followup; synthetic, offline fixtures."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import plan_queries
import reader_research as reader
import search_coverage
import source_access


class ReaderResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.save(
            "manifest.json", {"depth": "quick", "domain_adapters": ["hearthstone"]}
        )
        self.plan = {
            "reader_questions": [
                {
                    "question_id": "RQ-1",
                    "question": "Когда менять карту?",
                    "priority": "critical",
                    "status": "open",
                    "search_phrases": {
                        "en": "card replacement conditions",
                        "ru": "условия замены карты",
                    },
                }
            ]
        }
        self.save("plan.json", self.plan)

    def save(self, name, value):
        (self.root / name).write_text(
            json.dumps(value, ensure_ascii=False), encoding="utf-8"
        )

    def execute(self, task=None):
        task = task or reader.next_step(self.root)["tasks"][0]
        return reader.execute_search(
            self.root, task["query"]["query_id"], expected_sha256=task["query_sha256"]
        )

    def test_next_is_read_only_and_preserves_question_provenance(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        task = reader.next_step(self.root)
        self.assertEqual(task["status"], "search_required")
        self.assertEqual(task["tasks"][0]["query"]["reader_question_ids"], ["RQ-1"])
        self.assertFalse(task["factual_approval"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_execution_logs_discovery_without_answering_question_or_opening_source(
        self,
    ):
        payload = {
            "provider": "scrape.do",
            "operation": "google-search",
            "results": [
                {
                    "url": "https://example.org/guide",
                    "title": "Fixture",
                    "snippet": "Discovery",
                    "position": 1,
                    "evidence_status": "discovery_only",
                }
            ],
        }
        task = reader.next_step(self.root)["tasks"][0]
        with patch.object(source_access, "search", return_value=payload) as search:
            result = self.execute(task)
            self.assertEqual(result["status"], "executed")
            self.assertEqual(search.call_count, 1)
            with self.assertRaisesRegex(ValueError, "already"):
                self.execute(task)
            self.assertEqual(search.call_count, 1)
        query = json.loads((self.root / "queries.jsonl").read_text().splitlines()[0])
        self.assertEqual(query["result_source_ids"], [])
        self.assertTrue((self.root / query["search_snapshot"]).is_file())
        self.assertEqual(
            json.loads((self.root / "candidates.jsonl").read_text())["decision"],
            "deferred",
        )
        self.assertFalse((self.root / "sources.jsonl").exists())
        self.assertEqual(json.loads((self.root / "plan.json").read_text()), self.plan)

    def test_failed_provider_is_recorded_once_and_never_retried(self):
        task = reader.next_step(self.root)["tasks"][0]
        with patch.object(
            source_access,
            "search",
            side_effect=source_access.AccessError("FIXTURE_BLOCK"),
        ) as search:
            self.assertEqual(self.execute(task)["status"], "blocked")
            with self.assertRaises(ValueError):
                self.execute(task)
            self.assertEqual(search.call_count, 1)

    def test_reddit_uses_existing_primary_adapter_and_hsguru_keeps_site_scope(self):
        self.plan["reader_questions"][0]["target_platform"] = "reddit"
        self.save("plan.json", self.plan)
        with (
            patch.object(
                reader.community,
                "execute",
                return_value={"provider": "redditapi", "results": []},
            ) as reddit,
            patch.object(source_access, "search") as web,
        ):
            result = self.execute()
            self.assertEqual(result["provider"], "redditapi")
            self.assertEqual(reddit.call_args.args[0].command, "reddit-search")
            web.assert_not_called()
        self.assertEqual(
            reader.route(
                {"query": "site:hsguru.com card replacements", "target_platform": "web"}
            )["site"],
            "hsguru.com",
        )
        self.assertEqual(
            reader.route(
                {"query": "site:reddit.com card replacements", "target_platform": "web"}
            )["platform"],
            "reddit",
        )

    def test_scope_conflicts_and_symlink_outputs_do_not_start_a_request(self):
        with self.assertRaises(ValueError):
            reader.route(
                {"query": "site:hsguru.com replacements", "target_platform": "x"}
            )
        with self.assertRaises(ValueError):
            reader.route({"query": "site:reddit.com/r/hearthstone replacements"})
        outside = self.root / "protected.jsonl"
        outside.write_text("keep", encoding="utf-8")
        try:
            (self.root / "queries.jsonl").symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        with (
            patch.object(source_access, "search") as search,
            self.assertRaisesRegex(ValueError, "symlink"),
        ):
            reader.execute_search(self.root, "QRY-0001", expected_sha256="unused")
        search.assert_not_called()
        self.assertEqual(outside.read_text(), "keep")

    def test_empty_budget_or_empty_queue_does_not_mean_evidence_ready(self):
        self.plan["research_budget"] = {"max_queries": 1}
        self.save("plan.json", self.plan)
        with patch.object(
            source_access,
            "search",
            return_value={"provider": "scrape.do", "results": []},
        ):
            self.execute()
        task = reader.next_step(self.root)
        self.assertEqual(task["status"], "unresolved_no_search")
        self.assertFalse(task["factual_approval"])
        self.plan["reader_questions"][0]["status"] = "answered"
        self.save("plan.json", self.plan)
        self.assertFalse(reader.next_step(self.root)["factual_approval"])

    def test_no_plan_returns_a_planning_task_not_a_fabricated_question(self):
        self.save("plan.json", {})
        task = reader.next_step(self.root)
        self.assertEqual(task["status"], "needs_reader_questions")
        self.assertEqual(task["tasks"], [])

    def test_null_budget_uses_the_same_bounded_default_as_the_planner(self):
        self.plan["research_budget"] = {"max_queries": None}
        self.save("plan.json", self.plan)
        task = reader.next_step(self.root)
        self.assertEqual(task["max_queries"], 10)
        self.assertEqual(task["tasks"][0]["command"][-1], "10")

    def test_blocked_search_cli_reports_failure_after_recording(self):
        with (
            patch.object(
                sys,
                "argv",
                [
                    "reader_research.py",
                    "search",
                    str(self.root),
                    "--query-id",
                    "QRY-1",
                    "--query-sha256",
                    "fixture",
                ],
            ),
            patch.object(reader, "execute_search", return_value={"status": "blocked"}),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(reader.main(), 1)

    def test_stale_task_never_spends_a_request(self):
        task = reader.next_step(self.root)["tasks"][0]
        self.plan["reader_questions"][0]["search_phrases"]["en"] = (
            "different replacement question"
        )
        self.save("plan.json", self.plan)
        with (
            patch.object(source_access, "search") as search,
            self.assertRaisesRegex(ValueError, "stale"),
        ):
            self.execute(task)
        search.assert_not_called()
        self.assertFalse((self.root / "queries.jsonl").exists())

    def test_interrupted_attempt_is_visible_and_not_reissued(self):
        self.plan["research_budget"] = {"max_queries": 1}
        self.save("plan.json", self.plan)
        with patch.object(
            source_access, "search", side_effect=RuntimeError("fixture interruption")
        ) as search:
            with self.assertRaises(RuntimeError):
                self.execute()
            task = reader.next_step(self.root)
            self.assertEqual(task["status"], "interrupted_search")
            self.assertEqual(task["tasks"], [])
            self.assertEqual(search.call_count, 1)

    def test_task_is_invalidated_when_owner_lowers_budget(self):
        task = reader.next_step(self.root)["tasks"][0]
        self.plan["research_budget"] = {"max_queries": 1}
        self.save("plan.json", self.plan)
        with (
            patch.object(source_access, "search") as search,
            self.assertRaisesRegex(ValueError, "stale"),
        ):
            reader.execute_search(
                self.root,
                task["query"]["query_id"],
                expected_sha256=task["query_sha256"],
                max_queries=10,
            )
        search.assert_not_called()

    def test_same_phrase_on_web_and_reddit_is_two_different_requests(self):
        second = {
            **self.plan["reader_questions"][0],
            "question_id": "RQ-2",
            "target_platform": "reddit",
        }
        self.plan["reader_questions"].append(second)
        self.save("plan.json", self.plan)
        tasks = reader.next_step(self.root)["tasks"]
        self.assertEqual({t["route"]["platform"] for t in tasks}, {"web", "reddit"})
        with patch.object(
            source_access,
            "search",
            return_value={"provider": "scrape.do", "results": []},
        ):
            self.execute(next(t for t in tasks if t["route"]["platform"] == "web"))
        self.assertIn(
            "reddit",
            {t["route"]["platform"] for t in reader.next_step(self.root)["tasks"]},
        )

    def test_planned_at_changes_do_not_expire_an_unchanged_task(self):
        with patch.object(plan_queries, "utc_now", return_value="2026-11-05T00:00:00Z"):
            task = reader.next_step(self.root)["tasks"][0]
        with (
            patch.object(plan_queries, "utc_now", return_value="2026-11-06T00:00:00Z"),
            patch.object(
                source_access,
                "search",
                return_value={"provider": "scrape.do", "results": []},
            ) as search,
        ):
            self.execute(task)
            self.assertEqual(search.call_count, 1)

    def test_web_success_does_not_hide_pending_reddit_with_identical_words(self):
        from test_search_tools import write_jsonl

        web = {
            "query_id": "QRY-1",
            "query": "same phrase",
            "target_platform": "web",
            "family": "general",
            "pass": "gap",
            "status": "completed",
            "language": "en",
            "result_source_ids": [],
        }
        reddit = {
            **web,
            "query_id": "QRY-2",
            "target_platform": "reddit",
            "family": "reddit",
            "status": "planned",
        }
        write_jsonl(self.root / "queries.jsonl", [web])
        write_jsonl(self.root / "query-plan.jsonl", [reddit])
        report = search_coverage.analyze(self.root)
        self.assertIn("QRY-2", report["plan"]["unexecuted_ids"])
        self.assertIn("QRY-2", report["plan"]["unresolved_direction_ids"])

    def test_inspected_source_adds_a_followup_with_parent_and_original_venue(self):
        from test_search_tools import source, write_jsonl

        with patch.object(
            source_access,
            "search",
            return_value={"provider": "scrape.do", "results": []},
        ):
            record = self.execute()
        self.plan["reader_questions"][0].update(
            status="answered", target_platform="reddit"
        )
        self.save("plan.json", self.plan)
        record.update(
            result_source_ids=["SRC-1"],
            observations={
                "summary": "Synthetic source adds an exception",
                "followup_questions": [
                    {
                        "question": "Что без второго ресурса?",
                        "parent_question_id": "RQ-1",
                        "why_it_matters": "The condition may change the decision",
                        "search_phrases": {
                            "en": "replacement without second resource",
                            "ru": "замена без второго ресурса",
                        },
                    }
                ],
            },
        )
        write_jsonl(self.root / "queries.jsonl", [record])
        write_jsonl(
            self.root / "sources.jsonl",
            [source("SRC-1", "https://example.org/a", "L1")],
        )
        task = reader.next_step(self.root)["tasks"][0]
        self.assertEqual(task["query"]["origin_source_ids"], ["SRC-1"])
        self.assertEqual(task["query"]["reader_question_ids"], ["RQ-1"])
        self.assertEqual(task["route"]["platform"], "reddit")
        record["observations"]["followup_questions"].append(
            {
                **record["observations"]["followup_questions"][0],
                "target_platform": "web",
            }
        )
        write_jsonl(self.root / "queries.jsonl", [record])
        self.assertEqual(
            {t["route"]["platform"] for t in reader.next_step(self.root)["tasks"]},
            {"reddit", "web"},
        )


if __name__ == "__main__":
    unittest.main()
