import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
handoff_module = importlib.import_module("editorial_handoff")
compile_handoff = handoff_module.compile_handoff
decision_coverage = handoff_module.decision_coverage


class EditorialHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        for name, records in {
            "sources": [
                {
                    "source_id": "SRC-1",
                    "url": "https://example.org/guide",
                    "access_integrity": "full_text",
                }
            ],
            "evidence": [
                {
                    "evidence_id": "EVD-1",
                    "source_id": "SRC-1",
                    "quote": "Совет с условием.",
                }
            ],
            "claims": [
                {
                    "claim_id": "CLM-1",
                    "claim": "Совет с условием.",
                    "status": "supported_with_conditions",
                    "confidence": "MEDIUM",
                    "supporting_evidence_ids": ["EVD-1"],
                    "patch": "test",
                    "action": "Совет",
                    "condition": "с условием",
                }
            ],
        }.items():
            (self.root / f"{name}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in records), encoding="utf-8"
            )
        self.plan = {
            "brief": "Гайд",
            "patch": "test",
            "style_profile": "battlegrounds-guide",
            "chapters": [
                {
                    "chapter_id": "CH-1",
                    "title": "Решение",
                    "required_claim_ids": ["CLM-1"],
                }
            ],
            "decisions": [
                {
                    "question_id": "Q-1",
                    "chapter_id": "CH-1",
                    "question": "Когда?",
                    "required": True,
                    "status": "answered",
                    "claim_ids": ["CLM-1"],
                }
            ],
        }

    def test_compile_preserves_conditions_and_provenance(self):
        handoff, report = compile_handoff(self.root, self.plan)
        self.assertEqual(handoff["status"], "research_ready")
        self.assertEqual(handoff["claims"][0]["condition"], "с условием")
        self.assertEqual(handoff["claims"][0]["confidence"], "medium")
        self.assertEqual(handoff["sources"][0]["quote"], "Совет с условием.")
        self.assertEqual(report["required_coverage"], 1.0)

    def test_critical_gap_blocks_even_with_many_sources(self):
        self.plan["decisions"][0]["status"] = "open"
        handoff, report = compile_handoff(self.root, self.plan)
        self.assertEqual(handoff["status"], "research_blocked")
        self.assertEqual(report["required_coverage"], 0.0)
        self.assertEqual(report["gap_queue"][0]["question_id"], "Q-1")

    def test_unknown_claim_and_cross_chapter_answer_are_blocked(self):
        self.plan["decisions"][0]["claim_ids"] = ["CLM-other"]
        _, report = compile_handoff(self.root, self.plan)
        self.assertTrue(report["blocking"])
        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        collision = self.root / "same-output.json"
        with (
            patch.object(
                sys,
                "argv",
                [
                    "editorial_handoff.py",
                    str(self.root),
                    "--plan",
                    str(plan_path),
                    "--output",
                    str(collision),
                    "--report",
                    str(collision),
                ],
            ),
            self.assertRaises(SystemExit) as caught,
        ):
            handoff_module.main()
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse(collision.exists())

    def test_duplicate_ids_do_not_inflate_coverage(self):
        self.plan["decisions"].append(dict(self.plan["decisions"][0]))
        self.assertTrue(decision_coverage(self.plan, {"CLM-1"})["blocking"])

    def test_missing_quote_is_not_replaced_with_analyst_summary(self):
        (self.root / "evidence.jsonl").write_text(
            json.dumps(
                {
                    "evidence_id": "EVD-1",
                    "source_id": "SRC-1",
                    "faithful_paraphrase": "Сводка исследователя",
                }
            ),
            encoding="utf-8",
        )
        handoff, _ = compile_handoff(self.root, self.plan)
        self.assertEqual(handoff["status"], "research_blocked")


if __name__ == "__main__":
    unittest.main()
