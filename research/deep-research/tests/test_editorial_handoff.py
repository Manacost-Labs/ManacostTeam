import hashlib
import importlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
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
        snapshot = "Совет с условием. Другая проверенная информация.\n"
        (self.root / "source.txt").write_text(snapshot, encoding="utf-8")
        for name, records in {
            "sources": [
                {
                    "source_id": "SRC-1",
                    "url": "https://example.org/guide",
                    "access_integrity": "full_text",
                    "snapshot_path": "source.txt",
                    "content_sha256": hashlib.sha256(snapshot.encode()).hexdigest(),
                }
            ],
            "evidence": [
                {
                    "evidence_id": "EVD-1",
                    "source_id": "SRC-1",
                    "quote": "Совет с условием.",
                    "claim_ids": ["CLM-1"],
                    "relationship": "supports",
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
        claim = json.loads((self.root / "claims.jsonl").read_text())
        evidence = json.loads((self.root / "evidence.jsonl").read_text())
        source = json.loads((self.root / "sources.jsonl").read_text())

        def digest(value):
            return hashlib.sha256(
                json.dumps(
                    value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                ).encode()
            ).hexdigest()

        self.audit = {
            "semantic_audit_id": "SEM-1",
            "claim_id": "CLM-1",
            "evidence_id": "EVD-1",
            "source_id": "SRC-1",
            "semantic_support": "exact",
            "reviewer_status": "pass",
            "scope_match": True,
            "authority_match": True,
            "freshness_match": True,
            "evidence_type_match": True,
            "reviewer_basis": "Проверен совет и его условие.",
            "audited_at": "2026-10-14T12:00:00Z",
            "claim_sha256": digest(claim),
            "evidence_sha256": digest(evidence),
            "source_sha256": digest(source),
        }
        (self.root / "semantic-audit.jsonl").write_text(
            json.dumps(self.audit), encoding="utf-8"
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

    def test_review_digests_only_reports_hashes(self):
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        output = io.StringIO()
        with patch.object(
            sys, "argv", ["editorial_handoff.py", str(self.root), "--review-digests"]
        ), redirect_stdout(output):
            self.assertEqual(handoff_module.main(), 0)
        hashes = json.loads(output.getvalue())
        self.assertEqual(hashes["claims"]["CLM-1"], self.audit["claim_sha256"])
        self.assertEqual(hashes["evidence"]["EVD-1"], self.audit["evidence_sha256"])
        self.assertEqual(hashes["sources"]["SRC-1"], self.audit["source_sha256"])
        self.assertEqual(
            before, {path.name: path.read_bytes() for path in self.root.iterdir()}
        )

    def test_critical_gap_blocks_even_with_many_sources(self):
        self.plan["decisions"][0]["status"] = "open"
        handoff, report = compile_handoff(self.root, self.plan)
        self.assertEqual(handoff["status"], "research_blocked")
        self.assertEqual(report["required_coverage"], 0.0)
        self.assertEqual(report["gap_queue"][0]["question_id"], "Q-1")

    def test_chapter_examples_require_verified_claims(self):
        for field in ("decision_examples", "counterexamples"):
            self.plan["chapters"][0][field] = ["Выдуманный эффект способности."]
            self.assertEqual(
                compile_handoff(self.root, self.plan)[0]["status"], "research_blocked"
            )
            self.plan["chapters"][0][field] = ["Совет с условием."]
            self.assertEqual(
                compile_handoff(self.root, self.plan)[0]["status"], "research_ready"
            )

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

    def test_forged_quote_missing_snapshot_and_stale_review_block_handoff(self):
        for file, field, replacement in [
            ("evidence.jsonl", "quote", "Несуществующее описание способности."),
            ("sources.jsonl", "snapshot_path", "missing.txt"),
            ("sources.jsonl", "snapshot_path", "../outside.txt"),
            ("sources.jsonl", "content_sha256", "0" * 64),
            ("claims.jsonl", "claim", "Способность даёт несуществующий бонус."),
        ]:
            path = self.root / file
            original = path.read_text()
            value = json.loads(original)
            value[field] = replacement
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.subTest(file=file, field=field):
                handoff, report = compile_handoff(self.root, self.plan)
                self.assertEqual(handoff["status"], "research_blocked")
                self.assertTrue(report["blocking"])
            path.write_text(original, encoding="utf-8")

    def test_changed_source_context_requires_new_semantic_review(self):
        text = "Совет с условием. Контекст и ограничения источника изменены.\n"
        (self.root / "source.txt").write_text(text, encoding="utf-8")
        path = self.root / "sources.jsonl"
        source = json.loads(path.read_text())
        source["content_sha256"] = hashlib.sha256(text.encode()).hexdigest()
        path.write_text(json.dumps(source), encoding="utf-8")
        self.assertEqual(
            compile_handoff(self.root, self.plan)[0]["status"], "research_blocked"
        )

    def test_missing_or_partial_semantic_review_is_not_a_verified_description(self):
        audit_path = self.root / "semantic-audit.jsonl"
        for mutation in (
            {"semantic_support": "partial"},
            {"reviewer_status": "fail"},
            {"scope_match": False},
            {"claim_sha256": ""},
        ):
            audit_path.write_text(json.dumps({**self.audit, **mutation}))
            self.assertEqual(
                compile_handoff(self.root, self.plan)[0]["status"], "research_blocked"
            )
        audit_path.write_text("")
        self.assertEqual(
            compile_handoff(self.root, self.plan)[0]["status"], "research_blocked"
        )


if __name__ == "__main__":
    unittest.main()
