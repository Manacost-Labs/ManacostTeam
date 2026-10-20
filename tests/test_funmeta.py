import base64
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
from deck_code import decode, normalize_deck
from funmeta import CLASSES, initialize, validate
from quality import export_material, next_actions, review_digests


class FunmetaFixture:
    """Synthetic records test selection gates, never actual Hearthstone claims."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name) / "run"
        selection = initialize(self.run, "2026-10-19", "standard")
        self.data = json.loads(selection.read_text(encoding="utf-8"))
        self.data.pop("discovery_policy")  # Explicit legacy fixtures, including pre-0.4 v2.
        self.data.pop("material_policy")  # Preserve pre-0.6 material/export behavior.
        self.data["schema_version"] = 1  # Keep the legacy contract covered explicitly.
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


class FunmetaTests(FunmetaFixture, unittest.TestCase):
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

    def test_verified_label_cannot_accept_arbitrary_text_as_deck_code(self):
        self.candidate.update(deck_code_status="verified", deck_code="NOT A DECK CODE")
        with self.assertRaisesRegex(ValueError, "base64"):
            validate(self.data, self.run)


class DeckCodeTests(unittest.TestCase):
    def test_documented_hearthsim_vector(self):
        # Public format example; deliberately not a legal/playable deck.
        result = decode("AAEBAQcAAAQBAwIDAwMEAw==")
        self.assertEqual(result, {"format": 1, "heroes": [7], "sideboards": [],
                                  "cards": [[1, 3], [2, 3], [3, 3], [4, 3]]})

    def test_sideboards_and_real_varints(self):
        # Historical upstream wire-format fixture, not a current deck recommendation.
        code = ("AAEBAZCaBgjlsASotgSX7wTvkQXipAX9xAXPxgXGxwUQvp8EobYElrcE+dsEuNwEutwE9v"
                "AEhoMFopkF4KQFlMQFu8QFu8cFuJ4Gz54G0Z4GAAED8J8E/cQFuNkE/cQF/+EE/cQFAAA=")
        result = decode(code)
        self.assertEqual(result["heroes"], [101648])
        self.assertEqual(sum(count for _, count in result["cards"]), 40)
        self.assertEqual(result["sideboards"], [[69616, 1, 90749], [76984, 1, 90749], [78079, 1, 90749]])

    def test_truncation_bad_version_duplicate_cards_and_unknown_trailer(self):
        vectors = (
            [128, 0, 1, 2, 1, 7, 1, 1, 0, 0],  # Reserved header is a byte, not a varint.
            [0, 1, 2, 1, 128],  # Incomplete hero varint.
            [0, 2, 2, 1, 7, 1, 1, 0, 0],
            [0, 1, 2, 1, 7, 2, 1, 1, 0, 0],
            [0, 1, 2, 1, 7, 1, 1, 0, 0, 9],
            [0, 1, 2, 1, 7, 1, 1, 0, 0, 0, 99],
        )
        for vector in vectors:
            with self.subTest(vector=vector), self.assertRaises(ValueError):
                decode(base64.b64encode(bytes(vector)).decode())

    def test_sideboard_requires_its_owner_and_positive_integer_counts(self):
        deck = {"format": 2, "heroes": [7], "cards": [[1, 1]], "sideboards": [[2, 1, 3]]}
        with self.assertRaisesRegex(ValueError, "owner"):
            normalize_deck(deck)
        deck.update(sideboards=[], cards=[[1, True]])
        with self.assertRaisesRegex(ValueError, "invalid cards"):
            normalize_deck(deck)


class FunmetaV2Fixture(FunmetaFixture):
    def setUp(self):
        super().setUp()
        self.data["schema_version"] = 2
        self.data["evidence"] = [{"id": "e1", "source_id": "deck",
                                  "quote": "SYNTHETIC fixture only: deck"}]
        self.data["search_log"] = [
            {"id": f"{name}-{language}", "class": name, "language": language,
             "query": f"Synthetic {name} {language}", "status": "inspected" if name == "mage" else "empty",
             "notes": "Synthetic search outcome", "source_ids": ["deck"] if name == "mage" else []}
            for name in CLASSES for language in ("ru", "en")
        ]
        for source in self.data["sources"]:
            source["publisher"] = source["id"]
        self.candidate.update(
            deck_list={"format": 2, "heroes": [7], "cards": [[1, 1], [2, 1]], "sideboards": []},
            deck_code_status="verified",
            deck_code=base64.b64encode(bytes([0, 1, 2, 1, 7, 2, 1, 2, 0, 0, 0])).decode(),
            explanation_evidence={field: ["e1"] for field in
                                  ("game_plan", "fun_moment", "limitations", "legality")},
            closest_meta_plan="Synthetic meta plan", plan_difference="Synthetic distinct interaction",
        )
        self.data["fun_cards"][0]["evidence_ids"] = ["e1"]

    def save_review(self, material=None):
        selection = self.run / "selection.json"
        selection.write_text(json.dumps(self.data), encoding="utf-8")
        if material is None:
            material = ("Synthetic reviewed material, with class gaps disclosed.\n\n"
                        f"```text\n{self.candidate['deck_code']}\n```\n")
        (self.run / "material.md").write_text(material, encoding="utf-8", newline="")
        review = dict(review_digests(selection), verdict="pass", checked_on="2026-10-19",
                      facts_checked=True, plan_explained=True, coverage_checked=True,
                      gaps_disclosed=True, findings=[], notes="Synthetic reviewer notes")
        (self.run / "review.json").write_text(json.dumps(review), encoding="utf-8")
        return selection


class FunmetaV2Tests(FunmetaV2Fixture, unittest.TestCase):
    def test_v2_tracks_failures_without_counting_them_as_inspected(self):
        result = validate(self.data, self.run)
        self.assertEqual(result["inspected_searches"], 2)
        self.assertEqual(result["failed_or_empty_searches"], 20)
        self.assertEqual(result["evidence_items"], 1)
        self.assertEqual(result["coverage"], "partial")

    def test_code_must_match_full_list(self):
        self.candidate["deck_list"]["cards"][0][0] = 99
        with self.assertRaisesRegex(ValueError, "code/list mismatch"):
            validate(self.data, self.run)

    def test_alias_does_not_allow_duplicate_deck(self):
        alias = copy.deepcopy(self.candidate)
        alias.update(id="another-id", name="Another name")
        self.data["candidates"].append(alias)
        with self.assertRaisesRegex(ValueError, "duplicate deck"):
            validate(self.data, self.run)

    def test_made_up_quote_and_unbound_explanation_are_rejected(self):
        changed = copy.deepcopy(self.data)
        changed["evidence"][0]["quote"] = "This was never in the source."
        with self.assertRaisesRegex(ValueError, "quote not found"):
            validate(changed, self.run)
        self.candidate["explanation_evidence"]["legality"] = ["missing"]
        with self.assertRaisesRegex(ValueError, "unknown reference"):
            validate(self.data, self.run)

    def test_mirrors_excerpt_and_unattempted_class_are_not_accepted(self):
        changed = copy.deepcopy(self.data)
        changed["sources"][2]["publisher"] = "meta-a"
        with self.assertRaisesRegex(ValueError, "mirrors"):
            validate(changed, self.run)
        changed = copy.deepcopy(self.data)
        changed["sources"][3]["access"] = "excerpt"
        with self.assertRaisesRegex(ValueError, "deck is an excerpt"):
            validate(changed, self.run)
        self.data["search_log"].pop()
        with self.assertRaisesRegex(ValueError, "actual RU and EN"):
            validate(self.data, self.run)

    def test_next_prioritizes_unattempted_lanes_and_keeps_failures_visible(self):
        before = copy.deepcopy(self.data)
        result = next_actions(self.data)
        self.assertEqual(result["remaining_search_lanes"], 20)
        self.assertTrue(all(row["reason"] == "blocked_or_empty" for row in result["suggested_queries"]))
        self.assertTrue(all(row["query"] is None and row["focus"] for row in result["suggested_queries"]))
        self.assertEqual(self.data, before)
        self.data["search_log"].pop()
        self.assertEqual(next_actions(self.data)["suggested_queries"][0]["reason"], "not_attempted")

    def test_next_stops_after_one_targeted_retry_and_keeps_gap(self):
        failed = copy.deepcopy(self.data["search_log"][0])
        failed["id"] += "-retry"
        self.data["search_log"].append(failed)
        result = next_actions(self.data, limit=22)
        self.assertEqual(len(result["exhausted_lanes"]), 1)
        self.assertIn(failed["class"], result["class_gaps"])
        self.assertFalse(any(row["class"] == failed["class"] and row["language"] == failed["language"]
                             for row in result["suggested_queries"]))

    def test_export_requires_matching_review_and_never_overwrites(self):
        selection = self.save_review()
        output = self.run / "final.md"
        result = export_material(selection, self.data, validate(self.data, self.run), output)
        self.assertEqual(result["coverage"], "partial")
        self.assertEqual(output.read_bytes(), (self.run / "material.md").read_bytes())
        self.assertIn(self.candidate["deck_code"], output.read_text(encoding="utf-8"))
        with self.assertRaises(FileExistsError):
            export_material(selection, self.data, validate(self.data, self.run), output)

    def test_export_requires_verified_codes_even_for_readable_legacy_records(self):
        self.candidate["deck_code_status"] = "unavailable"
        self.candidate.pop("deck_code")
        selection = self.save_review(material="Synthetic full list link only.")
        output = self.run / "final.md"
        with self.assertRaisesRegex(ValueError, "verified deck code"):
            export_material(selection, self.data, validate(self.data, self.run), output)
        self.assertFalse(output.exists())

    def test_export_requires_the_selected_code_in_a_copyable_block(self):
        code = self.candidate["deck_code"]
        for index, material in enumerate(("Synthetic source link only.", f"Inline code: {code}",
                                          "```text\nAAECAwrongcode\n```\n")):
            with self.subTest(material=material):
                selection = self.save_review(material=material)
                output = self.run / f"final-{index}.md"
                with self.assertRaisesRegex(ValueError, "copyable code block"):
                    export_material(selection, self.data, validate(self.data, self.run), output)
                self.assertFalse(output.exists())

    def test_export_accepts_plain_fences_and_crlf_without_rewriting_the_code(self):
        material = f"Synthetic material.\r\n\r\n```\r\n{self.candidate['deck_code']}\r\n```\r\n"
        selection = self.save_review(material=material)
        output = self.run / "final.md"
        export_material(selection, self.data, validate(self.data, self.run), output)
        self.assertIn(f"```\n{self.candidate['deck_code']}\n```", output.read_text(encoding="utf-8"))

    def test_material_or_selection_change_invalidates_review(self):
        for field in ("material", "selection"):
            with self.subTest(field=field):
                selection = self.save_review()
                path = self.run / ("material.md" if field == "material" else "selection.json")
                path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, f"stale {field}_sha256"):
                    export_material(selection, self.data, validate(self.data, self.run), self.run / "final.md")

    def test_unresolved_findings_and_undisclosed_gaps_block_export(self):
        for field, value, message in (("findings", ["Fix a claim"], "findings"),
                                      ("gaps_disclosed", False, "partial coverage")):
            with self.subTest(field=field):
                selection = self.save_review()
                review_path = self.run / "review.json"
                review = json.loads(review_path.read_text(encoding="utf-8"))
                review[field] = value
                review_path.write_text(json.dumps(review), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    export_material(selection, self.data, validate(self.data, self.run), self.run / "final.md")

    def test_cli_next_decode_and_export(self):
        selection = self.save_review()
        for arguments, status in ((["next", str(selection)], "research_in_progress"),
                                  (["export", str(selection), "--output", str(self.run / "final.md")],
                                   "exported_after_recorded_review")):
            result = subprocess.run([sys.executable, str(SCRIPT), *arguments], check=False,
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], status)
        result = subprocess.run([sys.executable, str(SCRIPT), "decode", self.candidate["deck_code"]],
                                check=False, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["legality_verified"])


if __name__ == "__main__":
    unittest.main()
