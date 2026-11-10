"""Synthetic-only checks for claim semantics and strategy-decision coverage."""

import copy
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
semantics = importlib.import_module("claim_semantics")
search_coverage = importlib.import_module("search_coverage")
fixtures = importlib.import_module("test_research_run")


class ClaimSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.claim = {"claim_id": "CLM-1", "status": "supported",
                      "supporting_evidence_ids": ["EVD-1"]}
        self.evidence = {"EVD-1": {"source_id": "SRC-1", "relationship": "supports",
                                   "claim_ids": ["CLM-1"], "evidence_type": "game_rule",
                                   "locator": {"timestamp": "12:34"}}}
        self.sources = {"SRC-1": {"url": "https://example.org/synthetic",
                                  "source_type": "official",
                                  "access_integrity": "inspected"}}

    def errors(self, **updates):
        return semantics.claim_errors({**self.claim, **updates}, self.evidence,
                                      self.sources, required=True)

    def test_new_claim_requires_kind_and_legacy_remains_unclassified(self):
        self.assertIn("claim_kind", self.errors()[0])
        self.assertEqual(semantics.claim_errors(self.claim, {}, {}), [])
        self.assertNotIn("claim_kind", self.claim)
        for kind in ("observed", "derived", "fact", "", None, [], {}):
            with self.subTest(kind=kind):
                self.assertIn("claim_kind", self.errors(claim_kind=kind)[0])

    def test_observation_requires_positive_sample_unit_and_slice(self):
        scope = {"sample_size": 3, "unit": "games", "slice": "synthetic patch, selected VODs"}
        self.assertEqual(self.errors(claim_kind="observation", observation_scope=scope), [])
        for bad in (None, {}, {**scope, "sample_size": 0}, {**scope, "sample_size": -1},
                    {**scope, "sample_size": True}, {**scope, "sample_size": "3"},
                    {**scope, "unit": ""}, {**scope, "slice": ""}):
            with self.subTest(scope=bad):
                self.assertIn("observation_scope", self.errors(claim_kind="observation", observation_scope=bad)[0])

    def test_observation_cannot_supply_cause_or_inference(self):
        self.claim.update(claim_kind="observation", observation_scope={
            "sample_size": 1, "unit": "game", "slice": "synthetic"})
        for reason in ("", semantics.NO_REASON):
            self.assertEqual(self.errors(reason=reason), [])
        self.assertIn("reason", self.errors(reason="because the author assumes so")[0])
        self.assertIn("inference_steps", self.errors(inference_steps=["invented cause"])[0])

    def test_opinion_needs_named_inspected_supporting_source(self):
        self.claim["claim_kind"] = "opinion"
        attribution = {"name": "Synthetic Player", "source_id": "SRC-1"}
        self.assertEqual(self.errors(attribution=attribution, reason="Player explains why"), [])
        for bad in (None, {}, {**attribution, "name": ""}, {**attribution, "source_id": "SRC-missing"}):
            with self.subTest(attribution=bad):
                self.assertTrue(self.errors(attribution=bad))
        self.sources["SRC-1"]["access_integrity"] = "snippet"
        self.assertIn("inspected", self.errors(attribution=attribution)[0])
        self.sources["SRC-1"]["access_integrity"] = "inspected"
        self.evidence["EVD-1"]["relationship"] = "challenges"
        self.assertTrue(self.errors(attribution=attribution))

    def test_mechanic_requires_rule_evidence_not_expert_inference(self):
        self.claim["claim_kind"] = "mechanic"
        self.assertIn("rule_evidence_ids", self.errors()[0])
        self.assertEqual(self.errors(rule_evidence_ids=["EVD-1"]), [])
        for rule_type in semantics.RULE_TYPES:
            self.evidence["EVD-1"]["evidence_type"] = rule_type
            self.assertEqual(self.errors(rule_evidence_ids=["EVD-1"]), [])
        for rule_type in ("expert_analysis", "observation", [], None):
            self.evidence["EVD-1"]["evidence_type"] = rule_type
            self.assertIn("rule source", self.errors(rule_evidence_ids=["EVD-1"])[0])
        self.assertTrue(self.errors(rule_evidence_ids=["EVD-missing"]))
        self.evidence["EVD-1"]["evidence_type"] = "game_rule"
        self.sources["SRC-1"]["source_type"] = "expert_analysis"
        self.assertIn("rule source", self.errors(rule_evidence_ids=["EVD-1"])[0])

    def test_rule_requires_inspection_url_and_reciprocal_support(self):
        self.claim.update(claim_kind="mechanic", rule_evidence_ids=["EVD-1"])
        for key, value in (("url", ""), ("url", "https://user:secret@example.org"),
                           ("access_integrity", "snippet")):
            original = self.sources["SRC-1"][key]
            self.sources["SRC-1"][key] = value
            self.assertTrue(self.errors())
            self.sources["SRC-1"][key] = original
        self.evidence["EVD-1"]["claim_ids"] = ["CLM-other"]
        self.assertTrue(self.errors())

    def strategy_plan(self):
        field = {"text": "Synthetic inspected decision detail", "claim_ids": ["CLM-1"],
                 "evidence_refs": ["EVD-1"]}
        return {"strategy_review": True, "chapters": [{"chapter_id": "CH-1",
                "required_claim_ids": ["CLM-1"], "decision_cards": [{
                    "card_id": "CARD-1", "question": "Synthetic decision?",
                    "kind": "observed", "status": "supported", "player": "Synthetic Player",
                    "player_basis": "Synthetic verified tournament result",
                    "moment": {"turn": 8, "gold": 10, "tavern_tier": 4},
                    "fields": {name: copy.deepcopy(field) for name in
                               ("situation", "options", "action", "outcome")}}]}]}

    def coverage(self, plan):
        return semantics.strategy_decision_coverage(plan, {"CLM-1": self.claim}, self.evidence, self.sources)

    def test_strategy_requires_observed_player_decision_per_chapter(self):
        plan = self.strategy_plan()
        self.assertEqual(self.coverage(plan)["covered_chapters"], ["CH-1"])
        self.assertEqual(self.coverage(plan)["gaps"], [])
        plan["chapters"].append({"chapter_id": "CH-2"})
        self.assertIn("CH-2: " + semantics.ADVICE_GAP, self.coverage(plan)["gaps"][0])
        for kind in ("derived", "illustrative"):
            plan = self.strategy_plan()
            plan["chapters"][0]["decision_cards"][0]["kind"] = kind
            self.assertTrue(self.coverage(plan)["gaps"])

    def test_strategy_rejects_missing_fields_moment_player_or_evidence(self):
        for field in ("situation", "options", "action", "outcome"):
            plan = self.strategy_plan()
            del plan["chapters"][0]["decision_cards"][0]["fields"][field]
            self.assertTrue(self.coverage(plan)["gaps"], field)
        for key in ("moment", "player", "player_basis", "card_id", "question"):
            plan = self.strategy_plan()
            del plan["chapters"][0]["decision_cards"][0][key]
            self.assertTrue(self.coverage(plan)["gaps"], key)
        plan = self.strategy_plan()
        plan["chapters"][0]["decision_cards"][0]["fields"]["action"]["evidence_refs"] = ["missing"]
        self.assertTrue(self.coverage(plan)["gaps"])

    def test_malformed_strategy_records_leave_explicit_gaps(self):
        for chapters in (None, {}, [None], [{"decision_cards": {}}], [{"required_claim_ids": 5}]):
            with self.subTest(chapters=chapters):
                self.assertTrue(self.coverage({"strategy_review": True, "chapters": chapters})["gaps"])

    def test_player_decision_requires_timecode_or_transcript_quote(self):
        plan = self.strategy_plan()
        self.evidence["EVD-1"]["locator"] = {"section": "generic guide"}
        self.evidence["EVD-1"]["quote"] = "Ordinary guide quotation"
        self.assertTrue(self.coverage(plan)["gaps"])
        self.sources["SRC-1"]["access_integrity"] = "transcript"
        self.assertEqual(self.coverage(plan)["gaps"], [])
        del self.evidence["EVD-1"]["quote"]
        self.assertTrue(self.coverage(plan)["gaps"])


class BundleClaimContractTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "run"
        result = subprocess.run([sys.executable, str(fixtures.INIT), str(self.root),
                                 "--question", "Synthetic advice validation"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        fixtures.write_minimal_linked_fixture(self.root)

    def change(self, name, updates, *, remove=()):
        path = self.root / (name + (".json" if name == "manifest" else ".jsonl"))
        record = json.loads(path.read_text(encoding="utf-8"))
        record.update(updates)
        for key in remove:
            record.pop(key, None)
        path.write_text(json.dumps(record), encoding="utf-8")

    def validate(self):
        return fixtures.validate_bundle(self.root, stage="working")

    def test_initializer_enables_contract_and_missing_advice_kind_fails(self):
        manifest = json.loads((self.root / "manifest.json").read_text())
        self.assertEqual(manifest["claim_contract_version"], "1.0")
        self.change("claims", {"action": "Synthetic advice"}, remove=("claim_kind",))
        result = self.validate()
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("claim_kind", result.stdout)

    def test_legacy_bundle_without_claim_kind_still_validates(self):
        self.change("manifest", {}, remove=("claim_contract_version",))
        self.change("claims", {}, remove=("claim_kind", "observation_scope"))
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bundle_rejects_each_missing_kind_provenance(self):
        for kind, diagnostic in (("observation", "observation_scope"),
                                 ("opinion", "attribution"), ("mechanic", "rule_evidence_ids")):
            with self.subTest(kind=kind):
                self.change("claims", {"claim_kind": kind}, remove=("observation_scope",))
                result = self.validate()
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(diagnostic, result.stdout)

    def test_bundle_accepts_typed_mechanic_and_named_opinion(self):
        self.change("claims", {"claim_kind": "mechanic", "rule_evidence_ids": ["EVD-0001"]})
        self.change("evidence", {"evidence_type": "card_text"})
        self.assertEqual(self.validate().returncode, 0)
        self.change("claims", {"claim_kind": "opinion", "attribution": {
            "name": "Synthetic Author", "source_id": "SRC-0001"}})
        self.assertEqual(self.validate().returncode, 0)

    def test_strategy_gap_is_reported_by_search_coverage(self):
        self.change("manifest", {"strategy_review": True})
        report = search_coverage.analyze(self.root)
        self.assertIn(semantics.ADVICE_GAP, " ".join(report["findings"]["errors"]))
        self.assertEqual(report["completion_status"], "incomplete")

    def test_search_coverage_accepts_grounded_player_decision(self):
        plan = ClaimSemanticsTests().strategy_plan()
        chapter = plan["chapters"][0]
        chapter["required_claim_ids"] = ["CLM-0001"]
        for field in chapter["decision_cards"][0]["fields"].values():
            field.update(claim_ids=["CLM-0001"], evidence_refs=["EVD-0001"])
        (self.root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        self.change("evidence", {"locator": {"timestamp": "12:34"}})
        report = search_coverage.analyze(self.root)
        self.assertEqual(report["player_decisions"]["gaps"], [])
        self.assertEqual(report["player_decisions"]["covered_chapters"], ["CH-1"])
        self.assertNotIn(semantics.ADVICE_GAP, " ".join(report["findings"]["errors"]))

    def test_final_complete_bundle_cannot_hide_missing_player_decisions(self):
        self.change("manifest", {"strategy_review": True, "status": "complete"})
        (self.root / "plan.json").write_text('{"chapters": []}', encoding="utf-8")
        working = self.validate()
        self.assertEqual(working.returncode, 0, working.stdout)
        self.assertIn("warning: " + semantics.ADVICE_GAP, working.stdout)
        final = fixtures.validate_bundle(self.root, stage="final")
        self.assertEqual(final.returncode, 1)
        self.assertIn("\n- " + semantics.ADVICE_GAP, final.stdout)

    def test_unknown_contract_version_is_rejected(self):
        self.change("manifest", {"claim_contract_version": "unknown"})
        result = self.validate()
        self.assertEqual(result.returncode, 1)
        self.assertIn("unsupported claim_contract_version", result.stdout)

    def test_strategy_initializer_marks_manifest_and_plan(self):
        result = subprocess.run([sys.executable, str(fixtures.INIT), str(self.root.parent / "strategy"),
                                 "--question", "Synthetic strategy", "--strategy-review"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("manifest", "plan"):
            record = json.loads((self.root.parent / "strategy" / (name + ".json")).read_text())
            self.assertIs(record["strategy_review"], True)
