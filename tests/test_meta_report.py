"""Synthetic evidence tests; none of the fixtures describe the real ladder."""

import base64
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/meta-report/scripts/meta_report.py"
spec = importlib.util.spec_from_file_location("meta_report", SCRIPT)
meta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(meta)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class MetaReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name) / "report"
        meta.initialize(self.run, as_of="2026-10-20", game_format="standard")
        self.report = meta.read_json(self.run / "meta-report.json")
        self.report["schema_version"] = 1  # Previously created runs retain the v1 contract.
        self.code = base64.b64encode(bytes([0, 1, 2, 1, 8, 0, 15, *range(1, 16), 0, 0])).decode()
        text = "Synthetic patch fixture only: synthetic-patch. Synthetic metric: 56%. " + self.code
        self.sources = [{"id": "snapshot", "source": "synthetic", "url": "https://hearthstone.blizzard.com/en-us/fixture",
                         "text": text, "access": "public", "sha256": hashlib.sha256(text.encode()).hexdigest(),
                         "retrieved_at": "2026-10-20T12:00:00Z"}]
        self.handoff = {"schema_version": 1, "brief": "Synthetic test report", "patch": "synthetic-patch",
                        "style_profile": "meta-report", "status": "research_ready_with_gaps",
                        "sources": [{"source_id": "E1", "url": self.sources[0]["url"], "quote": text}],
                        "claims": [], "chapters": [], "decisions": []}
        for chapter in ("overview", *meta.CLASSES):
            cid = "C-" + chapter
            self.handoff["claims"].append({"claim_id": cid, "meaning": "Synthetic explanation " + chapter,
                                            "patch": "synthetic-patch", "status": "supported_with_conditions",
                                            "confidence": "medium", "condition": "Synthetic scope only",
                                            "exception": "Synthetic limitation", "evidence_refs": ["E1"]})
            self.handoff["chapters"].append({"chapter_id": chapter, "title": chapter, "required_claim_ids": [cid]})
            self.handoff["decisions"].append({"question_id": "Q-" + chapter, "chapter_id": chapter,
                                               "question": "Synthetic question?", "required": True,
                                               "status": "answered", "claim_ids": [cid]})
        self.report.update(patch="synthetic-patch", scope_note="Synthetic scope",
                           official_checks=[{"kind": "patch", "claim_id": "C-overview", "evidence_ref": "E1",
                                             "checked_on": "2026-10-20", "effective_on": "2026-10-20"}],
                           trend_claim_ids=["C-overview"],
                           statistics_gap="Synthetic fixture has no public statistics")
        for key, row in self.report["classes"].items():
            row.update(status="gap", gap="No synthetic list available", assessment_claim_ids=["C-" + key])
        self.report["classes"]["mage"].update(status="covered", deck_ids=["mage-list"], gap="")
        self.report["decks"] = [{"id": "mage-list", "class": "mage", "name": "Тестовый Маг", "archetype": "Synthetic mage",
                                  "plan_claim_ids": ["C-mage"], "limitation_claim_ids": ["C-mage"],
                                  "legality_claim_ids": ["C-mage"], "list_evidence_ref": "E1",
                                  "code_provenance": "author-export", "code": self.code,
                                  "deck_list": {"format": 2, "heroes": [8], "cards": [[i, 2] for i in range(1, 16)], "sideboards": []}}]
        self.save()

    def save(self):
        for name, value in (("meta-report.json", self.report), ("sources.json", self.sources),
                            ("publication-handoff.json", self.handoff)):
            write_json(self.run / name, value)

    def add_stat(self, identity="wr", **changes):
        row = {"id": identity, "metric": "winrate", "value": 56, "grain": "deck",
               "subject_id": "mage-list", "source_id": "snapshot", "evidence_ref": "E1", "claim_id": "C-mage",
               "patch": "synthetic-patch", "format": "standard", "rank": "all-ranks", "region": "all-regions",
               "start": "2026-10-19T12:00:00Z", "end": "2026-10-20T12:00:00Z",
               "population": "Synthetic tracked games", "sample_games": None,
               "sample_note": "The fixture does not report a sample size"}
        row.update(changes)
        self.report["statistics"].append(row)
        return row

    def material(self):
        pieces = ["# Synthetic report", "Synthetic overview"]
        for key, name in meta.CLASSES.items():
            pieces.extend(["## " + name, "Synthetic assessment"])
            if key == "mage":
                pieces.extend(["### Тестовый Маг", "Synthetic explanation", "```text\n" + self.code + "\n```"])
        return "\n\n".join(pieces)

    def enable_analysis(self):
        self.report["schema_version"] = 2
        second = copy.deepcopy(self.report["decks"][0])
        second.update(id="mage-alt", name="Альтернативный Маг", publish=False)
        self.report["decks"][0]["publish"] = True
        second["deck_list"]["cards"][0][0] = 16
        second["code"] = meta.runtimes()[2].encode(second["deck_list"])
        self.report["decks"].append(second)
        self.report["classes"]["mage"]["deck_ids"].append(second["id"])
        self.sources[0]["text"] += " " + second["code"] + " 54%"
        self.sources[0]["sha256"] = hashlib.sha256(self.sources[0]["text"].encode()).hexdigest()
        self.handoff["sources"][0]["quote"] = self.sources[0]["text"]
        self.add_stat("wr-a", sample_games=2000)
        self.add_stat("wr-b", value=54, sample_games=1800, subject_id="mage-alt")
        self.report["archetypes"] = [{
            "id": "mage-arch", "name": "Synthetic mage", "class": "mage",
            "identity_claim_ids": ["C-mage"],
            "deck_ids": ["mage-list", "mage-alt"],
            "search": {"source_ids": ["snapshot"], "note": "Synthetic candidate search", "gap": ""},
            "selection": {"verdict": "preferred", "preferred_deck_id": "mage-list", "basis": "mixed",
                          "confidence": "medium", "reason_claim_ids": ["C-mage"],
                          "scope_claim_ids": ["C-mage"], "caveat_claim_ids": ["C-mage"]},
            "comparisons": [{"id": "mage-a-b", "left": "mage-list", "right": "mage-alt",
                             "stat_pairs": [{"left": "wr-a", "right": "wr-b"}],
                             "impacts": [{"card_ids": [1, 16], "reason_claim_ids": ["C-mage"],
                                          "tradeoff_claim_ids": ["C-mage"]}],
                             "conclusion_claim_ids": ["C-mage"], "scope_claim_ids": ["C-mage"],
                             "counterargument": {"claim_ids": ["C-mage"], "gap": ""}}]}]
        self.report["dominance"] = [{
            "id": "mage-driver", "archetype_id": "mage-arch", "status": "hypothesis",
            "explanation_status": "hypothesis",
            "dimensions": ["performance"], "metric_ids": ["wr-a"],
            "observation_claim_ids": ["C-mage"], "driver_claim_ids": ["C-mage"],
            "counterplay_claim_ids": ["C-mage"], "limitation_claim_ids": ["C-mage"],
            "rival_explanations": {"claim_ids": ["C-mage"], "gap": ""},
            "uncertainty": "Synthetic inference, not causal proof"}]
        return self.report["archetypes"][0]

    def test_initialize_creates_unverified_research_and_refuses_overwrite(self):
        other = Path(self.temp.name) / "other"
        report = meta.initialize(other, as_of="2025-03-29", game_format="wild")
        self.assertIsNone(report["patch"])
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["format"], "wild")
        self.assertEqual(set(report["classes"]), set(meta.CLASSES))
        self.assertEqual(meta.read_json(other / "research/manifest.json")["as_of"], "2025-03-29")
        self.assertEqual(meta.next_task(other)["role"], "research-team")
        with self.assertRaisesRegex(ValueError, "exists"):
            meta.initialize(other, as_of="2025-03-29", game_format="wild")

    def test_accepts_explicit_gaps_and_preserves_unknown_sample_size(self):
        self.add_stat()
        result = meta.validate_package(self.report, self.sources, self.handoff)
        self.assertEqual(result["class_gaps"], [key for key in meta.CLASSES if key != "mage"])
        self.assertEqual(result["statistics_with_unknown_sample"], ["wr"])
        self.assertTrue(result["mechanical_checks_only"])

    def test_rejects_missing_patch_evidence_and_unaccounted_class(self):
        for change, message in ((lambda: self.report.update(official_checks=[]), "patch"),
                                (lambda: self.report["classes"].pop("druid"), "11 classes"),
                                (lambda: self.report["classes"]["druid"].update(chapter_id=None), "class chapter"),
                                (lambda: self.report["classes"]["druid"].update(status="covered", gap=""), "deck or gap")):
            with self.subTest(message=message):
                original = copy.deepcopy(self.report)
                change()
                with self.assertRaisesRegex(ValueError, message):
                    meta.validate_package(self.report, self.sources, self.handoff)
                self.report = original

    def test_rejects_code_list_mismatch_and_unproven_export(self):
        deck = self.report["decks"][0]
        deck["deck_list"]["cards"][0][1] = 1
        with self.assertRaisesRegex(ValueError, "code/list"):
            meta.validate_package(self.report, self.sources, self.handoff)
        deck["deck_list"]["cards"][0][1] = 2
        self.sources[0]["text"] = self.sources[0]["text"].replace(self.code, "")
        self.sources[0]["sha256"] = hashlib.sha256(self.sources[0]["text"].encode()).hexdigest()
        self.handoff["sources"][0]["quote"] = self.sources[0]["text"]
        with self.assertRaisesRegex(ValueError, "author export"):
            meta.validate_package(self.report, self.sources, self.handoff)

    def test_rejects_statistics_without_provenance_or_valid_temporal_scope(self):
        row = self.add_stat()
        for key, value, message in (("sample_note", "", "sample"), ("patch", "older", "patch/format"),
                                     ("end", "2026-10-21T12:00:00Z", "period"),
                                     ("start", "2026-10-20T14:00:00Z", "period"),
                                     ("value", 57, "percentage"), ("source_id", "missing", "source"),
                                     ("sample_games", 0, "sample")):
            with self.subTest(key=key):
                original = row[key]
                row[key] = value
                with self.assertRaisesRegex(ValueError, message):
                    meta.validate_package(self.report, self.sources, self.handoff)
                row[key] = original

    def test_rankings_reject_mixed_cohorts_and_wrong_sort_order(self):
        self.add_stat("first", grain="archetype", subject_id="archetype-a")
        second = self.add_stat("second", rank="legend", grain="archetype", subject_id="archetype-b")
        self.report["rankings"] = [{"title": "Synthetic selection", "stat_ids": ["first", "second"],
                                     "universe": "selected-decks", "scope_note": "Among studied synthetic decks"}]
        with self.assertRaisesRegex(ValueError, "cohort"):
            meta.validate_package(self.report, self.sources, self.handoff)
        second["rank"] = "all-ranks"
        second["value"] = 60
        self.sources[0]["text"] += " 60%"
        self.sources[0]["sha256"] = hashlib.sha256(self.sources[0]["text"].encode()).hexdigest()
        self.handoff["sources"][0]["quote"] = self.sources[0]["text"]
        with self.assertRaisesRegex(ValueError, "descending"):
            meta.validate_package(self.report, self.sources, self.handoff)

    def test_material_requires_class_coverage_and_codes_under_the_correct_deck(self):
        text = self.material()
        self.assertEqual(meta.audit_material(self.report, text), [])
        for bad in (text.replace("## Друид", "## Other"), text.replace("### Тестовый Маг", "### Other"),
                    text.replace("```text\n" + self.code + "\n```", ""), text + "\n63% winrate"):
            with self.subTest(bad=bad[-40:]):
                self.assertTrue(meta.audit_material(self.report, bad))

    def test_material_rejects_empty_class_and_deck_explanations(self):
        text = self.material().replace("Synthetic assessment", "").replace("Synthetic explanation", "")
        errors = meta.audit_material(self.report, text)
        self.assertTrue(any("empty class section: Друид" == error for error in errors), errors)
        self.assertIn("missing deck explanation: Тестовый Маг", errors)

    def test_next_cli_emits_utf8_when_parent_encoding_is_ascii(self):
        meta.prepare(self.run)
        environment = {**os.environ, "PYTHONIOENCODING": "ascii:strict", "PYTHONUTF8": "0"}
        result = subprocess.run([sys.executable, str(SCRIPT), "next", str(self.run)],
                                capture_output=True, env=environment)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
        task = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(task["stage"], "draft")
        self.assertIn("skills/meta-report/references/workflow.md", task["instructions"])

    def test_prepare_uses_existing_publication_gates_and_detects_changed_inputs(self):
        result = meta.prepare(self.run)
        self.assertEqual(result["stage"], "draft")
        task = meta.next_task(self.run)
        self.assertEqual(task["stage"], "draft")
        self.assertIn("meta_report", task["inputs"])
        draft = self.run / "candidate.md"
        draft.write_text(self.material(), encoding="utf-8")
        self.assertEqual(meta.submit(self.run, stage="draft", artifact=draft)["stage"], "fact_review")
        with self.assertRaisesRegex(ValueError, "both reviews"):
            meta.export(self.run, self.run / "final.md")
        self.report["scope_note"] = "Changed after acceptance"
        self.save()
        with self.assertRaisesRegex(ValueError, "changed"):
            meta.next_task(self.run)

    def test_prepare_rejects_unsupported_claims_before_creating_publication(self):
        self.handoff["claims"][0]["status"] = "disputed"
        self.save()
        with self.assertRaisesRegex(ValueError, "unsupported"):
            meta.prepare(self.run)
        self.assertFalse((self.run / "publication").exists())

    def test_exact_comparison_counts_main_and_sideboard_copies(self):
        self.enable_analysis()
        left, right = self.report["decks"]
        delta = meta.compare_decks(left, right)
        self.assertEqual(delta["common_main_copies"], 28)
        self.assertEqual(delta["left_only"], [[1, 2]])
        self.assertEqual(delta["right_only"], [[16, 2]])
        left["deck_list"]["sideboards"] = [[90, 1, 2]]
        right["deck_list"]["sideboards"] = [[90, 2, 2]]
        codec = meta.runtimes()[2]
        left["code"] = codec.encode(left["deck_list"])
        right["code"] = codec.encode(right["deck_list"])
        self.assertEqual(meta.compare_decks(left, right)["right_sideboard_only"], [[90, 1, 2]])

    def test_analysis_preserves_recommendation_deltas_and_research_only_variant(self):
        self.enable_analysis()
        meta.validate_package(self.report, self.sources, self.handoff)
        brief = meta.analysis_brief(self.report, self.sources, self.handoff)
        comparison = brief["archetypes"][0]["comparisons"][0]
        self.assertEqual(comparison["card_delta"]["left_only"], [[1, 2]])
        self.assertEqual(comparison["statistics"][0]["difference_pp"], 2)
        self.assertEqual(comparison["statistics"][0]["sample_games"], [2000, 1800])
        self.assertEqual(brief["archetypes"][0]["selection"]["preferred_deck_id"], "mage-list")
        self.assertEqual(meta.audit_material(self.report, self.material()), [])
        self.save()
        meta.prepare(self.run)
        self.assertEqual(meta.next_task(self.run)["analysis_brief"]["archetypes"][0]["id"], "mage-arch")

    def test_comparison_rejects_wrong_subjects_and_incomparable_filters(self):
        self.enable_analysis()
        second = self.report["statistics"][1]
        for key, value, expected in (("subject_id", "mage-list", "subject"),
                                     ("rank", "legend", "cohort"),
                                     ("opponent", "another-archetype", "cohort"),
                                     ("filters", {"coin": "first"}, "cohort")):
            with self.subTest(key=key):
                original = copy.deepcopy(second)
                second[key] = value
                with self.assertRaisesRegex(ValueError, expected):
                    meta.validate_package(self.report, self.sources, self.handoff)
                second.clear()
                second.update(original)

    def test_selection_requires_compared_changes_and_tradeoffs(self):
        archetype = self.enable_analysis()
        comparison = archetype["comparisons"][0]
        mutations = (
            (lambda: archetype.update(comparisons=[]), "comparison"),
            (lambda: comparison["impacts"][0].update(card_ids=[1]), "changed cards"),
            (lambda: comparison["impacts"][0].update(tradeoff_claim_ids=[]), "tradeoff"),
            (lambda: comparison.update(counterargument={"claim_ids": [], "gap": ""}), "counterargument"),
        )
        for mutate, expected in mutations:
            with self.subTest(expected=expected):
                original = copy.deepcopy(self.report)
                mutate()
                with self.assertRaisesRegex(ValueError, expected):
                    meta.validate_package(self.report, self.sources, self.handoff)
                self.report = original
                archetype = self.report["archetypes"][0]
                comparison = archetype["comparisons"][0]

    def test_unknown_sample_cannot_support_high_confidence_statistical_preference(self):
        archetype = self.enable_analysis()
        archetype["selection"].update(confidence="high", basis="statistics")
        for row in self.report["statistics"]:
            row.update(sample_games=None, sample_note="Synthetic source does not disclose n")
        with self.assertRaisesRegex(ValueError, "unknown sample"):
            meta.validate_package(self.report, self.sources, self.handoff)
        archetype["selection"]["confidence"] = "medium"
        self.assertEqual(meta.validate_package(self.report, self.sources, self.handoff)["statistics_with_unknown_sample"], ["wr-a", "wr-b"])

    def test_equivalent_timestamp_offsets_remain_comparable(self):
        self.enable_analysis()
        self.report["statistics"][1].update(start="2026-10-19T14:00:00+02:00", end="2026-10-20T14:00:00+02:00")
        self.assertTrue(meta.validate_package(self.report, self.sources, self.handoff)["mechanical_checks_only"])

    def test_conditional_and_inconclusive_choices_preserve_alternatives(self):
        archetype = self.enable_analysis()
        archetype["selection"].update(verdict="conditional", preferred_deck_id=None)
        self.report["decks"][1]["publish"] = True
        self.assertTrue(meta.validate_package(self.report, self.sources, self.handoff)["mechanical_checks_only"])
        self.assertTrue(meta.audit_material(self.report, self.material()))  # Both published lists need codes.
        archetype["selection"].update(verdict="inconclusive", basis="insufficient")
        self.report["decks"][1]["publish"] = False
        self.assertTrue(meta.validate_package(self.report, self.sources, self.handoff)["mechanical_checks_only"])
        archetype["selection"]["preferred_deck_id"] = "mage-list"
        with self.assertRaisesRegex(ValueError, "inconclusive"):
            meta.validate_package(self.report, self.sources, self.handoff)

    def test_single_candidate_requires_gap_and_cannot_claim_comparative_winner(self):
        archetype = self.enable_analysis()
        self.report["decks"].pop()
        self.report["classes"]["mage"]["deck_ids"] = ["mage-list"]
        self.report["statistics"].pop()
        archetype.update(deck_ids=["mage-list"], comparisons=[])
        with self.assertRaisesRegex(ValueError, "single-candidate"):
            meta.validate_package(self.report, self.sources, self.handoff)
        archetype["selection"].update(verdict="single-candidate", basis="statistics")
        archetype["search"]["gap"] = "No other verified full list found in the inspected sources"
        self.assertTrue(meta.validate_package(self.report, self.sources, self.handoff)["mechanical_checks_only"])

    def test_target_scope_mismatch_is_transferred_and_requires_article_disclosure(self):
        self.enable_analysis()
        self.report["rank"] = "legend"
        brief = meta.analysis_brief(self.report, self.sources, self.handoff)
        self.assertEqual(brief["target_scope"]["rank"], "legend")
        self.assertEqual(brief["scope_warnings"][0]["differences"]["rank"],
                         {"requested": "legend", "observed": "all-ranks"})
        errors = meta.validate_analysis_review(self.report, self.material(), {"meta_analysis": {"archetypes": [], "dominance": []}})
        self.assertTrue(any("scope_quote" in error for error in errors))

    def test_dominance_distinguishes_popularity_from_performance(self):
        self.enable_analysis()
        driver = self.report["dominance"][0]
        driver["status"] = "supported"
        driver["metric_ids"] = []
        with self.assertRaisesRegex(ValueError, "dominance.*metric"):
            meta.validate_package(self.report, self.sources, self.handoff)
        driver["metric_ids"] = ["wr-a"]
        driver["dimensions"] = ["popularity"]
        with self.assertRaisesRegex(ValueError, "popularity"):
            meta.validate_package(self.report, self.sources, self.handoff)

    def test_dominance_requires_counterplay_and_marks_unresolved_explanations(self):
        self.enable_analysis()
        driver = self.report["dominance"][0]
        driver["counterplay_claim_ids"] = []
        with self.assertRaisesRegex(ValueError, "counterplay"):
            meta.validate_package(self.report, self.sources, self.handoff)
        driver["counterplay_claim_ids"] = ["C-mage"]
        driver["rival_explanations"] = {"claim_ids": [], "gap": "Skill and matchup mix could not be separated"}
        self.assertTrue(meta.validate_package(self.report, self.sources, self.handoff)["mechanical_checks_only"])
        driver["uncertainty"] = ""
        with self.assertRaisesRegex(ValueError, "uncertainty"):
            meta.validate_package(self.report, self.sources, self.handoff)

    def test_dominance_keeps_matchups_and_unknown_explanations_separate(self):
        self.enable_analysis()
        driver = self.report["dominance"][0]
        self.add_stat("matchup", opponent="synthetic-opponent")
        driver.update(matchup_metric_ids=["matchup"], explanation_status="unknown", driver_claim_ids=[],
                      counterplay_claim_ids=[], counterplay_gap="No verified counterplay found")
        brief = meta.analysis_brief(self.report, self.sources, self.handoff)
        self.assertEqual(brief["dominance"][0]["matchups"][0]["opponent"], "synthetic-opponent")
        self.assertEqual(brief["dominance"][0]["explanation_status"], "unknown")
        self.assertEqual(brief["dominance"][0]["driver_claim_ids"], [])
        driver["metric_ids"] = ["matchup"]
        with self.assertRaisesRegex(ValueError, "one matchup"):
            meta.validate_package(self.report, self.sources, self.handoff)

    def test_v2_requires_archetype_analysis_but_legacy_v1_still_reads(self):
        self.assertEqual(meta.validate_package(self.report, self.sources, self.handoff)["selected_decks"], 1)
        self.report["schema_version"] = 2
        self.report["decks"][0]["publish"] = True
        with self.assertRaisesRegex(ValueError, "archetype"):
            meta.validate_package(self.report, self.sources, self.handoff)

    def test_factual_analysis_review_requires_actual_article_quotes(self):
        self.enable_analysis()
        article = self.material()
        record = {"archetypes": [{"id": "mage-arch", "selection_quote": "Synthetic assessment",
                                   "comparison_quote": "Synthetic explanation", "limitation_quote": "Synthetic assessment"}],
                  "dominance": [{"id": "mage-driver", "observation_quote": "Synthetic assessment",
                                  "explanation_quote": "Synthetic explanation", "limitation_quote": "Synthetic assessment"}]}
        self.assertEqual(meta.validate_analysis_review(self.report, article, {"meta_analysis": record}), [])
        record["archetypes"][0]["comparison_quote"] = "Absent from article"
        self.assertTrue(meta.validate_analysis_review(self.report, article, {"meta_analysis": record}))
        self.assertTrue(meta.validate_analysis_review(self.report, article, {}))

    def test_v2_factual_submit_cannot_skip_analysis_or_base_review_gates(self):
        self.enable_analysis()
        self.save()
        meta.prepare(self.run)
        draft = self.run / "candidate.md"
        draft.write_text(self.material(), encoding="utf-8")
        meta.submit(self.run, stage="draft", artifact=draft)
        review = self.run / "factual.json"
        write_json(review, {})
        with self.assertRaisesRegex(ValueError, "meta_analysis"):
            meta.submit(self.run, stage="fact_review", artifact=review)
        self.assertEqual(meta.next_task(self.run)["stage"], "fact_review")
        record = {"archetypes": [{"id": "mage-arch", "selection_quote": "Synthetic assessment",
                                   "comparison_quote": "Synthetic explanation", "limitation_quote": "Synthetic assessment"}],
                  "dominance": [{"id": "mage-driver", "observation_quote": "Synthetic assessment",
                                  "explanation_quote": "Synthetic explanation", "limitation_quote": "Synthetic assessment"}]}
        write_json(review, {"meta_analysis": record})
        state = meta.submit(self.run, stage="fact_review", artifact=review)
        self.assertEqual(state["blocked"]["stage"], "fact_review")
        self.assertTrue(state["blocked"]["errors"])
        with self.assertRaisesRegex(ValueError, "both reviews"):
            meta.export(self.run, self.run / "final.md")

    def test_negative_review_can_report_absent_explanations_without_inventing_quotes(self):
        self.enable_analysis()
        self.save()
        meta.prepare(self.run)
        article = self.material()
        draft = self.run / "candidate.md"
        draft.write_text(article, encoding="utf-8")
        meta.submit(self.run, stage="draft", artifact=draft)
        review = self.run / "negative.json"
        validator = meta.runtimes()[1]
        payload = {"status": "repair", "article_sha256": validator.article_hash(article),
                   "handoff_sha256": validator.handoff_hash(self.handoff),
                   "findings": [{"message": "Synthetic prose contains no supported card-role explanation"}]}
        write_json(review, payload)
        state = meta.submit(self.run, stage="fact_review", artifact=review)
        self.assertEqual(state["blocked"]["stage"], "fact_review")
        self.assertFalse(state["artifacts"]["fact_review"]["accepted"])
        stored = self.run / "publication" / state["artifacts"]["fact_review"]["path"]
        self.assertEqual(meta.read_json(stored), payload)
        draft.write_text(article + "\n\nSynthetic revision records unresolved evidence limitations.\n", encoding="utf-8")
        revised = meta.revise(self.run, draft)
        self.assertIsNone(revised["blocked"])
        self.assertEqual(revised["stage"], "fact_review")


if __name__ == "__main__":
    unittest.main()
