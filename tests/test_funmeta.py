import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/funmeta/scripts/funmeta.py"
sys.path.insert(0, str(SCRIPT.parent))
from funmeta import CLASSES, initialize, validate


class FunmetaTests(unittest.TestCase):
    """Synthetic records test selection gates, never actual Hearthstone claims."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name) / "run"
        selection = initialize(self.run, "2026-10-19", "standard")
        self.data = json.loads(selection.read_text(encoding="utf-8"))
        self.data.update(patch="synthetic-patch", patch_source_id="official",
                         meta_source_ids=["meta-a", "meta-b"])
        for source_id, kind, domain in (
            ("official", "official", "official.example"),
            ("meta-a", "meta", "table-a.example"),
            ("meta-b", "meta", "table-b.example"),
            ("deck", "deck", "creator.example"),
        ):
            payload = f"SYNTHETIC fixture only: {source_id}".encode()
            relative = f"sources/{source_id}.txt"
            (self.run / relative).write_bytes(payload)
            self.data["sources"].append({
                "id": source_id, "kind": kind, "title": source_id,
                "url": f"https://{domain}/source", "checked_on": "2026-10-19",
                "patch": "synthetic-patch", "format": "standard", "access": "full",
                "scope": "Synthetic scope", "snapshot": relative,
                "sha256": hashlib.sha256(payload).hexdigest(),
            })
        self.candidate = {
            "id": "example", "class": "mage", "name": "Synthetic candidate",
            "decision": "include", "reason": "Distinct synthetic plan",
            "premise": "Synthetic premise", "game_plan": "Synthetic sequence",
            "fun_moment": "Synthetic interaction", "limitations": "Synthetic condition",
            "legality": "verified", "legality_reason": "Synthetic manual review",
            "source_ids": ["deck"], "mechanics_source_ids": ["official"],
            "deck_code_status": "unavailable", "deck_code_reason": "Full list only",
            "meta_checks": [{"source_id": source_id, "result": "absent",
                             "reason": "Synthetic archetype comparison"}
                            for source_id in ("meta-a", "meta-b")],
        }
        self.data["candidates"] = [self.candidate]
        del self.data["gaps"]["mage"]
        self.data["fun_cards"] = [{"id": "card", "name": "Synthetic card",
                                   "why_fun": "Synthetic explanation", "source_ids": ["deck"]}]

    def test_partial_result_preserves_gaps_and_never_claims_factual_acceptance(self):
        result = validate(self.data, self.run)
        self.assertEqual(result["coverage"], "partial")
        self.assertEqual(result["classes_with_decks"], 1)
        self.assertEqual(len(result["class_gaps"]), len(CLASSES) - 1)
        self.assertTrue(result["mechanical_checks_only"])
        self.assertEqual(result["status"], "structure_valid")

    def test_complete_roster_requires_every_class(self):
        self.data["candidates"] = []
        self.data["gaps"] = {}
        for class_name in CLASSES:
            candidate = copy.deepcopy(self.candidate)
            candidate.update(id=class_name, **{"class": class_name})
            self.data["candidates"].append(candidate)
        self.assertEqual(validate(self.data, self.run)["coverage"], "complete")
        self.data["candidates"].pop()
        with self.assertRaisesRegex(ValueError, "every class"):
            validate(self.data, self.run)

    def test_known_meta_and_unknown_matches_cannot_be_included(self):
        for result in ("present", "unknown"):
            with self.subTest(result=result):
                self.candidate["meta_checks"][0]["result"] = result
                with self.assertRaisesRegex(ValueError, "present/unknown"):
                    validate(self.data, self.run)

    def test_missing_or_duplicated_table_check_does_not_prove_absence(self):
        first = self.candidate["meta_checks"][0]
        for checks in ([first], [first, first]):
            with self.subTest(checks=checks):
                self.candidate["meta_checks"] = checks
                with self.assertRaisesRegex(ValueError, "every meta table"):
                    validate(self.data, self.run)

    def test_wrong_scope_stale_excerpt_and_same_publisher_are_rejected(self):
        for field, value, error in (
            ("format", "wild", "format or patch"),
            ("patch", "older-patch", "format or patch"),
            ("checked_on", "2026-10-01", "older than"),
            ("checked_on", "2026-10-20", "after as_of"),
            ("access", "excerpt", "full table"),
            ("url", "https://www.table-a.example/other", "distinct publishers"),
        ):
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(self.data)
                changed["sources"][2][field] = value
                with self.assertRaisesRegex(ValueError, error):
                    validate(changed, self.run)

    def test_snapshot_tampering_and_path_escape_are_rejected(self):
        snapshot = self.run / self.data["sources"][0]["snapshot"]
        snapshot.write_text("modified", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate(self.data, self.run)
        self.data["sources"][0]["snapshot"] = "../outside.txt"
        with self.assertRaisesRegex(ValueError, "inside run"):
            validate(self.data, self.run)

    def test_included_candidate_needs_explanation_legality_and_sources(self):
        for field, value, error in (
            ("game_plan", "", "game_plan"),
            ("legality", "unverified", "legality"),
            ("source_ids", ["official"], "full deck"),
            ("mechanics_source_ids", ["missing"], "unknown source"),
            ("deck_code_status", "unverified", "unverified deck code"),
            ("deck_code", "UNVERIFIED", "omit unavailable"),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.data)
                changed["candidates"][0][field] = value
                with self.assertRaisesRegex(ValueError, error):
                    validate(changed, self.run)

    def test_pending_and_rejected_candidates_do_not_close_class(self):
        for decision in ("pending", "reject"):
            with self.subTest(decision=decision):
                self.candidate["decision"] = decision
                with self.assertRaisesRegex(ValueError, "every class"):
                    validate(self.data, self.run)
                changed = copy.deepcopy(self.data)
                changed["gaps"]["mage"] = "No verified candidate"
                self.assertEqual(validate(changed, self.run)["selected_decks"], 0)

    def test_duplicate_ids_and_contradictory_gap_are_rejected(self):
        changed = copy.deepcopy(self.data)
        changed["sources"].append(changed["sources"][0])
        with self.assertRaisesRegex(ValueError, "duplicate id"):
            validate(changed, self.run)
        self.data["gaps"]["mage"] = "Conflicts with included deck"
        with self.assertRaisesRegex(ValueError, "also has a gap"):
            validate(self.data, self.run)

    def test_initializer_never_replaces_run_and_empty_run_fails_check(self):
        marker = self.run / "material.md"
        marker.write_text("User draft", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            initialize(self.run, "2026-10-19", "wild")
        self.assertEqual(marker.read_text(encoding="utf-8"), "User draft")
        fresh = self.run.parent / "fresh"
        selection = initialize(fresh, "2026-10-19", "wild")
        with self.assertRaisesRegex(ValueError, "patch"):
            validate(json.loads(selection.read_text(encoding="utf-8")), fresh)

    def test_cli_pass_failure_and_invalid_json(self):
        selection = self.run / "selection.json"
        for payload, expected_status, expected_code in (
            (json.dumps(self.data), "structure_valid", 0),
            ("{", "invalid", 1),
            ("[]", "invalid", 1),
        ):
            selection.write_text(payload, encoding="utf-8")
            result = subprocess.run([sys.executable, str(SCRIPT), "check", str(selection)],
                                    check=False, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, expected_code, result.stderr)
            output = json.loads(result.stdout or result.stderr)
            self.assertEqual(output["status"], expected_status)


if __name__ == "__main__":
    unittest.main()
