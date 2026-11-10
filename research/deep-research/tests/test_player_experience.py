"""Synthetic player experience provenance and coverage checks."""
import copy
import importlib
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sem = importlib.import_module("claim_semantics")
handoff_tests = importlib.import_module("test_editorial_handoff")
contract_tests = importlib.import_module("test_claim_semantics")


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.claims = {"C": {"supporting_evidence_ids": ["E"]}}
        self.evidence = {"E": {"source_id": "S", "relationship": "supports", "claim_ids": ["C"], "quote": "Synthetic answer"}}
        self.sources = {"S": {"source_type": "author_note", "access_integrity": "full_text", "fingerprint_status": "verified", "snapshot_path": "answer.txt"}}
        self.card = {"card_id": "X", "kind": "observed", "status": "supported", "advice_form": "threshold", "first_person": True, "condition": "synthetic condition", "reason": "причина не названа", "threshold": {"value": 4, "unit": "cards"}, "fields": {"action": {"text": "Synthetic action", "claim_ids": ["C"], "evidence_refs": ["E"]}}, "experience_source": {"kind": "author_note", "source_id": "S", "evidence_id": "E", "author": "Synthetic", "date": "2026-01-01", "quote": "Synthetic answer"}}

    def errors(self):
        return sem.experience_errors(self.card, self.claims, self.evidence, self.sources)

    def test_author_requires_identity_date_quote_and_link(self):
        self.assertEqual(self.errors(), [])
        for key in ("author", "date", "quote", "source_id", "evidence_id"):
            original = self.card["experience_source"].pop(key)
            self.assertTrue(self.errors(), key)
            self.card["experience_source"][key] = original
        self.card["first_person"] = False
        self.assertTrue(self.errors())

    def test_forms_require_shape_and_legacy_is_untouched(self):
        self.card["threshold"] = {"unit": "cards"}
        self.assertTrue(self.errors())
        self.card.update(advice_form="order", steps=[])
        self.assertTrue(self.errors())
        self.card["steps"] = ["first", "second"]
        self.assertEqual(self.errors(), [])
        self.card.update(advice_form="skill_gated", audience="novice")
        self.assertEqual(self.errors(), [])
        del self.card["audience"]
        self.assertTrue(self.errors())
        self.assertEqual(sem.experience_errors({}, {}, {}, {}), [])

    def test_transcript_and_replay_need_real_source_and_locator(self):
        self.card.update(advice_form="trap", first_person=False)
        self.card["experience_source"] = {"kind": "transcript", "source_id": "S", "evidence_id": "E"}
        self.assertTrue(self.errors())
        self.sources["S"] = {"source_type": "video", "access_integrity": "transcript", "url": "https://example.org/video"}
        self.assertEqual(self.errors(), [])
        self.card["experience_source"] = {"kind": "xml_replay", "source_id": "S", "evidence_id": "E", "result_ref": "result.txt", "turn": 5, "action": "synthetic move"}
        self.sources["S"] = {"source_type": "xml_replay", "fingerprint_status": "verified", "snapshot_path": "result.txt"}
        self.assertEqual(self.errors(), [])
        self.card["experience_source"]["result_ref"] = "other.txt"
        self.assertTrue(self.errors())

    def test_coverage_groups_forms_and_reports_empty(self):
        plan = {"profile": "constructed-guide", "chapters": [{"decision_cards": [self.card]}]}
        result = sem.experience_coverage(plan, self.claims, self.evidence, self.sources)
        self.assertEqual(result["counts"]["threshold"], 1)
        self.assertNotIn("threshold", result["missing_forms"])
        plan["chapters"] = []
        self.assertEqual(sem.experience_coverage(plan, {}, {}, {})["gaps"], [sem.MASTERY_GAP])


class ExperienceHandoffTests(unittest.TestCase):
    setUp = handoff_tests.EditorialHandoffTests.setUp
    update_reviewed_record = handoff_tests.EditorialHandoffTests.update_reviewed_record
    def test_handoff_grouping_and_empty_gap(self):
        self.plan["profile"] = "constructed-guide"
        handoff, report = self.compile_experience()
        self.assertEqual(handoff["experience_coverage"]["counts"]["trap"], 1)
        self.assertTrue(handoff["experience_by_form"]["trap"][0]["first_person"])
        self.plan["chapters"][0]["decision_cards"] = []
        handoff, report = importlib.import_module("editorial_handoff").compile_handoff(self.root, self.plan)
        self.assertIn(sem.MASTERY_GAP, report["blocking"])
        self.assertTrue(any(x["question"] == sem.MASTERY_GAP for x in report["gap_queue"]))

    def compile_experience(self):
        self.update_reviewed_record("sources", source_type="author_note", fingerprint_status="verified")
        self.plan["chapters"][0]["decision_cards"] = [{"card_id": "X", "question": "Synthetic?", "kind": "observed", "status": "supported", "advice_form": "trap", "first_person": True, "condition": "synthetic condition", "reason": "причина не названа", "experience_source": {"kind": "author_note", "source_id": "SRC-1", "evidence_id": "EVD-1", "author": "Synthetic", "date": "2026-01-01", "quote": "Совет с условием."}, "fields": {"action": {"text": "Synthetic", "claim_ids": ["CLM-1"], "evidence_refs": ["EVD-1"]}}}]
        return importlib.import_module("editorial_handoff").compile_handoff(self.root, self.plan)


class ExperienceValidatorTests(unittest.TestCase):
    setUp = contract_tests.BundleClaimContractTests.setUp
    change = contract_tests.BundleClaimContractTests.change
    validate = contract_tests.BundleClaimContractTests.validate
    def test_validator_rejects_unsupported_experience(self):
        plan = {"chapters": [{"decision_cards": [{"card_id": "X", "advice_form": "order", "first_person": False, "condition": "synthetic", "reason": "причина не названа", "fields": {"action": {"text": "synthetic"}}}]}]}
        (self.root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        result = self.validate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("experience_source required", result.stdout)
        self.assertIn("order requires steps", result.stdout)
