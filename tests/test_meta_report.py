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

    def test_initialize_creates_unverified_research_and_refuses_overwrite(self):
        other = Path(self.temp.name) / "other"
        report = meta.initialize(other, as_of="2025-03-29", game_format="wild")
        self.assertIsNone(report["patch"])
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


if __name__ == "__main__":
    unittest.main()
