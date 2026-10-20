"""Synthetic evidence exercises diagnostics and event-time gates, not game facts."""

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/funmeta/scripts/funmeta.py"
sys.path.insert(0, str(SCRIPT.parent))
from funmeta import validate
from readiness import assess, meta_issues
from test_funmeta import FunmetaV2Fixture


class ReadinessTests(FunmetaV2Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.data.update(readiness_policy=1, meta_context={
            "effective_at": "2026-10-19T17:00:00Z", "source_id": "official",
            "reason": "Synthetic official game pool change"})
        for source in self.data["sources"]:
            if source["kind"] == "meta":
                source.update(data_kind="observed", data_period={
                    "start": "2026-10-19T17:00:00Z", "end": "2026-10-19T18:00:00Z"})
        self.candidate["code_provenance"] = {"kind": "author-export", "source_ids": ["deck"]}

    def result(self):
        return assess(self.data, self.run)

    def global_codes(self):
        return {item["code"] for item in self.result()["global_blockers"]}

    def blockers(self):
        return set(self.result()["candidates"][0]["blocking_checks"])

    def test_complete_records_remain_unapproved_and_do_not_mutate(self):
        before = copy.deepcopy(self.data)
        result = self.result()
        self.assertEqual(result["global_blockers"], [])
        self.assertEqual(result["candidates"][0]["blocking_checks"], [])
        self.assertTrue(result["candidates"][0]["recorded_checks_complete"])
        self.assertFalse(result["export_approved"])
        self.assertEqual(validate(self.data, self.run)["selected_decks"], 1)
        self.assertEqual(self.data, before)

    def test_missing_meta_does_not_hide_code_legality_and_evidence_gaps(self):
        self.data["meta_source_ids"] = []
        self.candidate.update(deck_code="damaged", legality="unverified", explanation_evidence={})
        result = self.result()
        self.assertIn("meta_coverage", {x["code"] for x in result["global_blockers"]})
        self.assertEqual(set(result["candidates"][0]["blocking_checks"]), {
            "deck_code_and_independent_list", "current_legality", "evidence_game_plan",
            "evidence_fun_moment", "evidence_limitations", "evidence_legality"})
        self.assertFalse(result["candidates"][0]["recorded_checks_complete"])

    def test_pending_is_diagnosed_without_becoming_selected_and_reject_is_ignored(self):
        self.candidate["decision"] = "pending"
        self.data["candidates"].append({"id": "rejected", "class": "mage", "decision": "reject"})
        result = self.result()
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["decision"], "pending")
        self.assertEqual(self.candidate["decision"], "pending")
        self.assertFalse(result["export_approved"])

    def test_code_list_mismatch_and_wrong_origin_are_reported_together(self):
        self.candidate["deck_list"]["cards"][0][0] = 99
        self.candidate["code_provenance"] = {"kind": "author-export", "source_id": "deck"}
        self.assertEqual(self.blockers(), {"deck_code_and_independent_list", "code_provenance"})

    def test_fabricated_quote_and_unrelated_binding_do_not_count_as_evidence(self):
        self.data["evidence"].extend([
            {"id": "fabricated", "source_id": "deck", "quote": "not in saved source"},
            {"id": "unrelated", "source_id": "meta-a", "quote": "SYNTHETIC fixture only: meta-a"}])
        self.candidate["explanation_evidence"]["game_plan"] = ["fabricated"]
        self.candidate["explanation_evidence"]["limitations"] = ["unrelated"]
        self.assertEqual(self.blockers(), {"evidence_game_plan", "evidence_limitations"})

    def test_tampered_snapshot_blocks_report_even_with_complete_record_labels(self):
        (self.run / "sources/deck.txt").write_text("changed", encoding="utf-8")
        result = self.result()
        self.assertEqual(result["global_blockers"], [{"code": "source_integrity", "source_id": "deck",
            "message": "Read and hash a nonempty source snapshot inside this run."}])
        self.assertFalse(result["candidates"][0]["recorded_checks_complete"])
        self.assertIn("evidence_game_plan", result["candidates"][0]["blocking_checks"])

    def test_source_escape_is_reported_without_reading_external_file(self):
        self.data["sources"][3]["snapshot"] = "../external.txt"
        self.assertIn("source_integrity", self.global_codes())
        self.assertFalse(self.result()["candidates"][0]["recorded_checks_complete"])

    def test_present_meta_plan_blocks_candidate(self):
        self.candidate["meta_checks"][0]["result"] = "present"
        self.assertEqual(self.blockers(), {"meta_plan_present"})

    def test_missing_or_duplicate_meta_comparison_is_not_absence(self):
        for case in ("missing", "duplicate"):
            with self.subTest(case=case):
                self.candidate["meta_checks"] = ([self.candidate["meta_checks"][0]] if case == "missing" else
                                                [self.candidate["meta_checks"][0]] * 2)
                self.assertIn("meta_comparison", self.blockers())

    def test_publisher_majority_is_visible_without_forcing_source_quotas(self):
        for number in range(2):
            other = copy.deepcopy(self.candidate)
            other.update(id=f"other-{number}", decision="pending")
            self.data["candidates"].append(other)
        self.data["sources"].append({**self.data["sources"][3], "id": "independent", "publisher": "Other Author"})
        self.data["candidates"][-1]["source_ids"] = ["independent"]
        result = self.result()
        self.assertEqual(result["publisher_distribution"], {"deck": ["example", "other-0"], "other author": ["other-1"]})
        self.assertEqual(result["dominant_publisher"], "deck")
        self.assertTrue(any("not an automatic rejection" in message for message in result["warnings"]))
        self.assertEqual(result["global_blockers"], [])

    def test_mirrored_meta_publishers_are_not_independent(self):
        self.data["sources"][2]["publisher"] = " META-A "
        self.assertIn("meta_coverage", self.global_codes())

    def test_period_before_at_and_after_event_boundary(self):
        for case, start, blocked in (
            ("before", "2026-10-19T16:59:59Z", True),
            ("exact", "2026-10-19T17:00:00Z", False),
            ("after", "2026-10-19T17:00:01Z", False),
            ("offset_equivalent", "2026-10-19T19:00:00+02:00", False)):
            with self.subTest(case=case):
                self.data["sources"][1]["data_period"]["start"] = start
                self.assertEqual("meta_before_context" in self.global_codes(), blocked)
                if blocked:
                    with self.assertRaisesRegex(ValueError, "meta_before_context"):
                        validate(self.data, self.run)
                else:
                    self.assertEqual(validate(self.data, self.run)["selected_decks"], 1)

    def test_theorycraft_cannot_substitute_for_observed_table(self):
        self.data["sources"][1]["data_kind"] = "theorycraft"
        self.assertIn("meta_not_observed", self.global_codes())
        with self.assertRaisesRegex(ValueError, "meta_not_observed"):
            validate(self.data, self.run)

    def test_unknown_empty_future_and_timezone_free_periods_are_rejected(self):
        cases = [("missing", None), ("empty", {"start": "2026-10-19T17:00:00Z", "end": "2026-10-19T17:00:00Z"}),
                 ("future", {"start": "2026-10-19T17:00:00Z", "end": "2026-10-20T18:00:00Z"}),
                 ("naive", {"start": "2026-10-19T17:00:00", "end": "2026-10-19T18:00:00Z"})]
        for case, period in cases:
            with self.subTest(case=case):
                self.data["sources"][1]["data_period"] = period
                self.assertIn("meta_period_invalid", self.global_codes())

    def test_context_requires_official_source_and_known_time(self):
        self.data["meta_context"].update(source_id="deck", effective_at=None)
        self.assertTrue({"meta_context_source", "meta_context_time"} <= self.global_codes())
        self.assertFalse(self.result()["candidates"][0]["recorded_checks_complete"])

    def test_legacy_runs_are_readable_without_invented_periods(self):
        self.data.pop("readiness_policy")
        self.data.pop("meta_context")
        for source in self.data["sources"]:
            source.pop("data_period", None)
        self.assertEqual(validate(self.data, self.run)["selected_decks"], 1)
        self.assertTrue(any("Legacy run" in note for note in self.result()["warnings"]))

    def test_invalid_policy_is_not_a_legacy_bypass(self):
        for case, value in (("boolean", True), ("unknown", 2)):
            with self.subTest(case=case):
                self.data["readiness_policy"] = value
                with self.assertRaisesRegex(ValueError, "readiness_policy"):
                    validate(self.data, self.run)

    def test_malformed_meta_ids_return_validation_errors(self):
        for case, value in (("null", None), ("mapping", {"meta-a": True}), ("object_item", [{}])):
            with self.subTest(case=case):
                self.data["meta_source_ids"] = value
                with self.assertRaisesRegex(ValueError, "meta_source_ids"):
                    meta_issues(self.data, {source["id"]: source for source in self.data["sources"]})

    def test_cli_diagnoses_all_gaps_without_touching_input_or_creating_review(self):
        self.data["meta_source_ids"] = []
        selection = self.run / "selection.json"
        selection.write_text(json.dumps(self.data), encoding="utf-8")
        before = {p.name: p.read_bytes() for p in self.run.iterdir() if p.is_file()}
        process = subprocess.run([sys.executable, str(SCRIPT), "assess", str(selection)],
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertIn("meta_coverage", {x["code"] for x in result["global_blockers"]})
        self.assertFalse(result["export_approved"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.run.iterdir() if p.is_file()})

    def test_cli_export_rejects_pre_event_data_even_with_recorded_passing_review(self):
        self.data["sources"][1]["data_period"]["start"] = "2026-10-19T16:59:59Z"
        selection = self.save_review()
        output = self.run / "must-not-export.md"
        process = subprocess.run([sys.executable, str(SCRIPT), "export", str(selection), "--output", str(output)],
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 1)
        self.assertIn("meta_before_context", json.loads(process.stderr)["error"])
        self.assertFalse(output.exists())

    def test_new_run_next_exposes_missing_context_without_creating_facts(self):
        from funmeta import initialize
        selection = initialize(self.run.parent / "new-run", "2026-10-19", "standard")
        before = selection.read_bytes()
        process = subprocess.run([sys.executable, str(SCRIPT), "next", str(selection)],
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertIn("meta_context_time", {item["code"] for item in result["readiness"]["global_blockers"]})
        self.assertEqual(result["suggested_queries"][0]["channel"], "catalog")
        self.assertFalse(result["readiness"]["export_approved"])
        self.assertEqual(selection.read_bytes(), before)
