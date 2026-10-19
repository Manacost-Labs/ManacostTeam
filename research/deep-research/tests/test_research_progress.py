"""Reader-question planning and truthful progress/freshness regressions."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import freshness_check
import plan_queries
import search_coverage
from test_search_tools import executed_query, source, write_jsonl, run, PLAN


class ResearchProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = {"research_id": "test", "main_question": "When to switch?", "depth": "quick", "as_of": "2026-10-19"}
        self.save("manifest.json", self.manifest)

    def save(self, name, value):
        (self.root / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def test_failed_blocked_skipped_do_not_cover_families_or_saturate(self):
        queries = [dict(executed_query(f"QRY-{i}", family, f"q{i}", []), status=status)
                   for i, (family, status) in enumerate(zip(["primary", "counterargument", "freshness"], ["failed", "blocked", "skipped"]))]
        write_jsonl(self.root / "queries.jsonl", queries)
        report = search_coverage.analyze(self.root)
        self.assertEqual(report["branches"]["__all__"]["families_present"], [])
        self.assertEqual(report["queries"]["attempted"], 2)
        self.assertEqual(report["queries"]["studied"], 0)
        self.assertFalse(report["saturation"]["__all__"]["saturated"])

    def test_no_results_and_repeated_sources_do_not_create_saturation(self):
        write_jsonl(self.root / "sources.jsonl", [source("SRC-1", "https://example.org/a", "L1")])
        queries = [executed_query(f"QRY-{i}", "primary", f"q{i}", ["SRC-1"]) for i in range(5)]
        queries.extend(dict(executed_query(f"QRY-{i}", "freshness", f"q{i}", []), status="no_results") for i in range(5, 9))
        write_jsonl(self.root / "queries.jsonl", queries)
        report = search_coverage.analyze(self.root)
        self.assertEqual(report["saturation"]["__all__"]["trailing_zero_yield"], 1)
        self.assertFalse(report["saturation"]["__all__"]["saturated"])

    def test_three_distinct_studied_materials_can_exhaust_a_branch(self):
        write_jsonl(self.root / "sources.jsonl", [source(f"SRC-{i}", f"https://example.org/{i}", f"L{i}") for i in range(3)])
        write_jsonl(self.root / "queries.jsonl", [executed_query(f"QRY-{i}", family, f"q{i}", [f"SRC-{i}"]) for i, family in enumerate(["primary", "counterargument", "freshness"])])
        report = search_coverage.analyze(self.root)
        self.assertTrue(report["saturation"]["__all__"]["saturated"])
        self.assertEqual(report["completion_status"], "search_exhausted")
        write_jsonl(self.root / "query-plan.jsonl", [{"query_id": "QRY-9", "query": "another promising direction", "status": "planned"}])
        self.assertFalse(search_coverage.analyze(self.root)["saturation"]["__all__"]["saturated"])

    def test_failed_planned_direction_remains_pending_until_successful_retry(self):
        write_jsonl(self.root / "sources.jsonl", [source(f"SRC-{i}", f"https://example.org/{i}", f"L{i}") for i in range(3)])
        queries = [executed_query(f"QRY-{i}", family, f"q{i}", [f"SRC-{i}"]) for i, family in enumerate(["primary", "counterargument", "freshness"])]
        planned = {"query_id": "QRY-9", "query": "promising unresolved direction", "family": "primary", "status": "planned"}
        write_jsonl(self.root / "query-plan.jsonl", [planned])
        for failure in ("failed", "blocked"):
            with self.subTest(status=failure):
                write_jsonl(self.root / "queries.jsonl", queries + [{**planned, "status": failure, "executed_at": "2026-10-19"}])
                report = search_coverage.analyze(self.root)
                self.assertFalse(report["saturation"]["__all__"]["saturated"])
                self.assertEqual(report["completion_status"], "incomplete")
                self.assertIn("QRY-9", report["saturation"]["__all__"]["pending_query_ids"])
        write_jsonl(self.root / "queries.jsonl", queries + [{**planned, "status": "failed", "executed_at": "2026-10-18"}, {**planned, "query_id": "QRY-10", "status": "no_results", "executed_at": "2026-10-19"}])
        self.assertTrue(search_coverage.analyze(self.root)["saturation"]["__all__"]["saturated"])

    def test_unsupported_novelty_and_failed_challenge_are_not_credit(self):
        query = dict(executed_query("QRY-1", "counterargument", "counterclaim", ["SRC-1"]), status="failed")
        query["observations"] = {"novelty": [{"kind": "condition", "summary": "Unverified", "evidence_ids": ["EVD-1"]}]}
        write_jsonl(self.root / "sources.jsonl", [source("SRC-1", "https://example.org/a", "L1")])
        write_jsonl(self.root / "queries.jsonl", [query])
        write_jsonl(self.root / "evidence.jsonl", [{"evidence_id": "EVD-1", "source_id": "SRC-1"}])
        write_jsonl(self.root / "claims.jsonl", [{"claim_id": "CLM-1", "importance": "critical", "status": "supported", "challenge_search": {"query_ids": ["QRY-1"], "result": "none_found"}}])
        report = search_coverage.analyze(self.root)
        self.assertEqual(report["useful_yield_by_query"]["QRY-1"], 0)
        self.assertEqual(report["claims"]["with_challenge"], 0)
        self.assertTrue(any("novelty" in error for error in report["findings"]["errors"]))

    def test_exception_and_counterevidence_are_useful_without_new_claim(self):
        sources = [source(f"SRC-{i}", f"https://example.org/{i}", f"L{i}") for i in range(4)]
        queries = [executed_query(f"QRY-{i}", "primary", f"q{i}", [f"SRC-{i}"]) for i in range(4)]
        evidence = [{"evidence_id": "EVD-1", "source_id": "SRC-3", "relationship": "challenging", "claim_ids": ["CLM-1"]}]
        queries[-1]["observations"] = {"summary": "The rule has an exception.", "novelty": [{"kind": "exception", "summary": "Does not apply without both cards", "evidence_ids": ["EVD-1"]}]}
        write_jsonl(self.root / "sources.jsonl", sources)
        write_jsonl(self.root / "queries.jsonl", queries)
        write_jsonl(self.root / "evidence.jsonl", evidence)
        write_jsonl(self.root / "claims.jsonl", [{"claim_id": "CLM-1", "status": "supported_with_conditions", "challenging_evidence_ids": ["EVD-1"]}])
        report = search_coverage.analyze(self.root)
        self.assertGreater(report["useful_yield_by_query"]["QRY-3"], 0)
        self.assertEqual(report["saturation"]["__all__"]["trailing_zero_yield"], 0)

    def test_open_reader_question_keeps_result_incomplete(self):
        self.save("plan.json", {"reader_questions": [{"question_id": "RQ-1", "question": "When is switching wrong?", "status": "partial", "priority": "critical", "gap": "Exception unknown"}]})
        report = search_coverage.analyze(self.root)
        self.assertEqual(report["completion_status"], "incomplete")
        self.assertEqual(report["reader_questions"]["unresolved"][0]["gap"], "Exception unknown")

    def test_requested_language_cannot_disappear_with_pending_translation(self):
        self.manifest["required_query_languages"] = ["en", "ru"]
        self.save("manifest.json", self.manifest)
        write_jsonl(self.root / "queries.jsonl", [executed_query("QRY-1", "primary", "first query", [])])
        report = search_coverage.analyze(self.root)
        self.assertEqual(report["queries"]["missing_languages"], ["ru"])
        self.assertTrue(any("required query languages" in item for item in report["findings"]["errors"]))

    def test_multilingual_planning_requires_real_translations_and_links_entity(self):
        self.manifest["main_question"] = "Переход в новую сборку"
        self.save("manifest.json", self.manifest)
        missing = run(PLAN, str(self.root), "--language", "en", "--json")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("search_phrases", missing.stderr)
        self.save("plan.json", {"query_localization": {"topics": {"__all__": {"en": "changing composition", "ru": "переход в новую сборку"}}, "entities": [{"entity_id": "CARD-1", "names": {"en": ["Example Card"], "ru": ["Пример карты"]}}]}})
        result = run(PLAN, str(self.root), "--language", "en", "--language", "ru", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(all("переход" not in r["query"] for r in records if r["language"] == "en"))
        self.assertTrue(any(r.get("entity_id") == "CARD-1" and "Пример карты" in r["query"] for r in records))

    def test_legacy_entity_cannot_bypass_english_localization(self):
        result = run(PLAN, str(self.root), "--language", "en", "--entity", "Бранн", "--json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("entity", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_adaptive_queue_is_grounded_deduplicated_and_budgeted(self):
        self.save("plan.json", {"reader_questions": [{"question_id": "RQ-1", "question": "When to switch?", "status": "partial", "priority": "critical", "search_phrases": {"en": "composition switch conditions"}}], "research_budget": {"max_queries": 3}})
        query = executed_query("QRY-0001", "primary", "first search", ["SRC-1"])
        question = {"question": "What if one card is missing?", "parent_question_id": "RQ-1", "why_it_matters": "Could reverse advice", "search_phrases": {"en": "switch missing second card"}, "priority": "critical"}
        query["observations"] = {"summary": "Two cards needed", "followup_questions": [question, dict(question)]}
        write_jsonl(self.root / "queries.jsonl", [query])
        write_jsonl(self.root / "sources.jsonl", [source("SRC-1", "https://example.org/a", "L1")])
        result = run(PLAN, str(self.root), "--question-gaps", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(records), 2)
        self.assertEqual(sum(r["query"] == "switch missing second card" for r in records), 1)
        followup = next(r for r in records if r["query"] == "switch missing second card")
        self.assertEqual(followup["reader_question_id"], "RQ-1")
        self.assertEqual(followup["origin_query_id"], "QRY-0001")
        self.assertEqual(followup["origin_source_ids"], ["SRC-1"])
        first = run(PLAN, str(self.root), "--question-gaps", "--json", "--apply")
        self.assertEqual(first.returncode, 0, first.stderr)
        before = (self.root / "query-plan.jsonl").read_bytes()
        again = run(PLAN, str(self.root), "--question-gaps", "--json", "--apply")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual((self.root / "query-plan.jsonl").read_bytes(), before)
        self.assertEqual(len(again.stdout.splitlines()), 2)
        report = search_coverage.analyze(self.root)
        self.assertEqual(report["reader_questions"]["followups"], 1)
        self.assertEqual(report["completion_status"], "incomplete")
        query["status"] = "blocked"
        write_jsonl(self.root / "queries.jsonl", [query])
        failed = run(PLAN, str(self.root), "--question-gaps", "--json")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("inspected", failed.stderr)

    def test_followup_inherits_critical_priority_before_budget(self):
        questions = [
            {"question_id": "R-1", "question": "When?", "status": "answered", "priority": "critical"},
            {"question_id": "R-2", "question": "Background?", "priority": "material", "search_phrases": {"en": "background"}},
        ]
        query = executed_query("QRY-0001", "primary", "first", ["SRC-1"])
        query["observations"] = {"summary": "A limit changes the answer", "followup_questions": [
            {"question": "What is the limit?", "parent_question_id": "R-1", "why_it_matters": "Changes the action", "search_phrases": {"en": "action limit"}}
        ]}
        records = plan_queries.question_queue({"reader_questions": questions}, [query], [source("SRC-1", "https://example.org/a", "L1")], [], ["en"], [])
        chosen = plan_queries.apply_budget(records, [query], [], 2)
        self.assertEqual(chosen[0]["query"], "action limit")
        self.assertEqual(chosen[0]["priority"], "critical")
        self.assertEqual(chosen[0]["origin_source_ids"], ["SRC-1"])

    def test_shared_query_retains_both_reader_questions(self):
        questions = [{"question_id": q, "question": q, "section_id": s, "search_phrases": {"en": "same evidence query"}} for q, s in [("R-1", "CH-1"), ("R-2", "CH-2")]]
        records = plan_queries.question_queue({"reader_questions": questions}, [], [], [], ["en"], [])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["reader_question_ids"], ["R-1", "R-2"])
        self.assertEqual(records[0]["deliverable_section_ids"], ["CH-1", "CH-2"])
        self.assertEqual(records[0]["status"], "planned")

    def test_pending_query_preserves_previous_provenance(self):
        old = {"query_id": "QRY-0001", "query": "same evidence query", "status": "planned", "planned_at": "earlier", "reader_question_id": "R-old", "deliverable_section_ids": ["CH-old"], "origin_query_id": "QRY-origin", "origin_source_ids": ["SRC-old"]}
        plan = {"reader_questions": [{"question_id": "R-new", "question": "New?", "section_id": "CH-new", "search_phrases": {"en": old["query"]}}]}
        row = plan_queries.question_queue(plan, [], [], [old], ["en"], [])[0]
        self.assertEqual(row["query_id"], old["query_id"])
        self.assertEqual(row["reader_question_id"], "R-old")
        self.assertEqual(row["reader_question_ids"], ["R-old", "R-new"])
        self.assertEqual(row["deliverable_section_ids"], ["CH-old", "CH-new"])
        self.assertEqual(row["origin_query_ids"], ["QRY-origin"])
        self.assertEqual(row["origin_source_ids"], ["SRC-old"])
        self.assertNotIn("reader_question_ids", old)

    def test_pending_critical_priority_survives_new_contextual_question(self):
        old = {"query_id": "QRY-0001", "query": "critical search", "status": "planned", "priority": "critical", "reader_question_id": "R-old", "planned_at": "earlier"}
        plan = {"reader_questions": [
            {"question_id": "R-material", "question": "Background", "search_phrases": {"en": "background"}},
            {"question_id": "R-new", "question": "Related context", "priority": "contextual", "search_phrases": {"en": old["query"]}},
        ]}
        records = plan_queries.question_queue(plan, [], [], [old], ["en"], [])
        chosen = plan_queries.apply_budget(records, [], [old], 1)
        self.assertEqual(chosen[0]["priority"], "critical")
        self.assertEqual(chosen[0]["query_id"], "QRY-0001")
        self.save("plan.json", plan)
        write_jsonl(self.root / "query-plan.jsonl", [old])
        write_jsonl(self.root / "queries.jsonl", [])
        before = (self.root / "queries.jsonl").read_bytes()
        result = run(PLAN, str(self.root), "--question-gaps", "--language", "en", "--max-queries", "1", "--json", "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        persisted = json.loads((self.root / "query-plan.jsonl").read_text())
        self.assertEqual(persisted["reader_question_ids"], ["R-old", "R-new"])
        self.assertEqual(persisted["priority"], "critical")
        self.assertEqual((self.root / "queries.jsonl").read_bytes(), before)

    def timeline(self, checked="2026-10-19"):
        value = {"timeline_version": "1.0", "checked_at": checked, "official_checks": [{"checked_at": checked, "source_url": "https://hearthstone.blizzard.com/en-us/news", "modes": ["battlegrounds"], "through": "2026-10-19", "result": "no_later_relevant_changes"}], "patches": [{"version": "36.1", "released": "2026-09-01", "modes": ["battlegrounds"], "source_url": "https://hearthstone.blizzard.com/en-us/news/1"}, {"version": "36.2", "released": "2026-10-01", "modes": ["battlegrounds"], "source_url": "https://hearthstone.blizzard.com/en-us/news/2"}]}
        self.save("timeline.json", value)
        self.manifest["current_context"] = {"patch": "36.2", "mode": "battlegrounds"}
        self.save("manifest.json", self.manifest)
        return self.root / "timeline.json"

    def test_old_registry_does_not_confirm_current_state(self):
        path = self.timeline("2026-09-01")
        report = freshness_check.analyze(self.root, path, None)
        self.assertTrue(any("registry" in item for item in report["findings"]["errors"]))
        self.assertEqual(report["freshness_status"], "unverified")

    def test_future_registry_and_official_check_dates_cannot_verify(self):
        path = self.timeline()
        original = json.loads(path.read_text())
        for target in ("registry", "official_check", "both"):
            with self.subTest(target=target):
                data = json.loads(json.dumps(original))
                if target in {"registry", "both"}:
                    data["checked_at"] = "2099-01-01"
                if target in {"official_check", "both"}:
                    data["official_checks"][0]["checked_at"] = "2099-01-01"
                self.save("timeline.json", data)
                report = freshness_check.analyze(self.root, path, None)
                self.assertEqual(report["freshness_status"], "unverified")
                self.assertTrue(any("future" in error for error in report["findings"]["errors"]))

    def test_historical_question_uses_question_date_not_access_date(self):
        path = self.timeline()
        self.manifest["temporal_scope"] = {"mode": "historical", "as_of": "2026-09-15"}
        self.manifest["current_context"]["patch"] = "36.1"
        self.save("manifest.json", self.manifest)
        report = freshness_check.analyze(self.root, path, None)
        self.assertEqual(report["latest_patch"]["version"], "36.1")
        self.assertEqual(report["findings"]["errors"], [])

    def test_recent_access_does_not_refresh_old_content(self):
        path = self.timeline()
        write_jsonl(self.root / "sources.jsonl", [{"source_id": "SRC-1", "published_at": "2026-09-01", "accessed_at": "2026-10-19", "freshness_status": "CURRENT"}])
        report = freshness_check.analyze(self.root, path, None)
        self.assertEqual(report["source_dates"]["SRC-1"]["content_date"], "2026-09-01")
        self.assertIn("SRC-1", " ".join(report["findings"]["errors"]))

    def test_likely_current_label_cannot_hide_content_predating_change(self):
        path = self.timeline()
        write_jsonl(self.root / "sources.jsonl", [{"source_id": "SRC-1", "published_at": "2026-09-01", "accessed_at": "2026-10-19", "freshness_status": "LIKELY_CURRENT"}])
        report = freshness_check.analyze(self.root, path, None)
        self.assertEqual(report["freshness_status"], "unverified")
        self.assertIn("SRC-1", " ".join(report["findings"]["errors"]))

    def test_new_publication_does_not_refresh_old_statistical_window(self):
        path = self.timeline()
        write_jsonl(self.root / "sources.jsonl", [{"source_id": "SRC-1", "source_type": "statistics", "published_at": "2026-10-18", "patch": "36.2", "freshness_status": "CURRENT", "statistical_context": {"time_window": {"start": "2026-09-01", "end": "2026-09-15"}}}])
        report = freshness_check.analyze(self.root, path, None)
        self.assertTrue(any("data window" in error for error in report["findings"]["errors"]))

    def test_statistical_window_straddling_change_is_not_current(self):
        path = self.timeline()
        write_jsonl(self.root / "sources.jsonl", [{"source_id": "SRC-1", "source_type": "statistics", "patch": "36.2", "freshness_status": "CURRENT", "statistical_context": {"time_window": {"start": "2026-09-15", "end": "2026-10-15"}}}])
        report = freshness_check.analyze(self.root, path, None)
        self.assertTrue(any("data window" in error for error in report["findings"]["errors"]))

    def test_free_text_patch_does_not_bypass_freshness(self):
        path = self.timeline()
        write_jsonl(self.root / "sources.jsonl", [{"source_id": "SRC-1", "patch": "latest", "freshness_status": "CURRENT"}])
        report = freshness_check.analyze(self.root, path, None)
        self.assertTrue(any("unverified patch" in error for error in report["findings"]["errors"]))

    def test_subject_specific_change_does_not_invalidate_unaffected_source(self):
        path = self.timeline()
        data = json.loads(path.read_text())
        data["patches"][1]["subjects"] = ["other-card"]
        self.save("timeline.json", data)
        write_jsonl(self.root / "sources.jsonl", [{"source_id": "SRC-1", "patch": "36.1", "freshness_status": "CURRENT", "freshness_subjects": ["our-card"]}])
        report = freshness_check.analyze(self.root, path, None)
        self.assertEqual(report["findings"]["errors"], [])
        self.assertEqual(report["source_dates"]["SRC-1"]["latest_relevant_balance_patch"], "36.1")

    def test_compatible_label_requires_a_recorded_official_review(self):
        path = self.timeline()
        write_jsonl(self.root / "sources.jsonl", [{"source_id": "SRC-1", "patch": "36.1", "freshness_status": "VERSION_COMPATIBLE"}])
        report = freshness_check.analyze(self.root, path, None)
        self.assertTrue(any("freshness_review" in error for error in report["findings"]["errors"]))


if __name__ == "__main__":
    unittest.main()
