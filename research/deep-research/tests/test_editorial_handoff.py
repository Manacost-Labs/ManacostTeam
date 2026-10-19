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
    def test_shared_boundary_fixture_is_reproducible(self):
        fixture = json.loads(
            (SCRIPTS.parents[2] / "tests/fixtures/editorial-boundary.json").read_text(
                encoding="utf-8"
            )
        )
        (self.root / "source.txt").write_text(fixture["source_text"], encoding="utf-8")
        for name, rows in fixture["bundle"].items():
            (self.root / f"{name}.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows), encoding="utf-8"
            )
        handoff, report = compile_handoff(self.root, fixture["plan"])
        self.assertEqual(report["blocking"], [])
        self.assertEqual(handoff, fixture["handoff"])

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

    def test_rich_context_survives_compilation_and_shared_evidence(self):
        updates = {
            "sources": {
                "title": "Guide",
                "author": "Editor",
                "lineage_id": "origin-1",
                "published_at": "2026-10-01",
                "accessed_at": "2026-10-19",
            },
            "evidence": {
                "evidence_type": "expert_analysis",
                "sample": {"size": 40, "population": "test"},
            },
            "claims": {
                "claim_type": "recommendation",
                "confidence_basis": "Scoped evidence",
                "inference_steps": ["Apply the condition"],
                "scope": {"mode": "test"},
            },
        }
        audit = dict(self.audit)
        for name, extra in updates.items():
            path = self.root / f"{name}.jsonl"
            record = {**json.loads(path.read_text()), **extra}
            path.write_text(json.dumps(record), encoding="utf-8")
            audit[
                {"sources": "source", "evidence": "evidence", "claims": "claim"}[name]
                + "_sha256"
            ] = handoff_module.record_sha256(record)
        (self.root / "semantic-audit.jsonl").write_text(
            json.dumps(audit), encoding="utf-8"
        )
        handoff, _ = compile_handoff(self.root, self.plan)
        self.assertEqual(handoff["status"], "research_ready")
        self.assertEqual(
            handoff["sources"][0].get("source_context", {}).get("lineage_id"),
            "origin-1",
        )
        self.assertEqual(
            handoff["sources"][0]["evidence_context"]["sample"]["size"], 40
        )
        self.assertEqual(
            handoff["claims"][0]["research_context"]["confidence_basis"],
            "Scoped evidence",
        )
        self.assertEqual(
            handoff["sources"][0]["claim_hashes"]["CLM-1"], audit["claim_sha256"]
        )

    def test_structured_decision_fields_are_grounded_and_gaps_remain_visible(self):
        card = {
            "card_id": "CARD-1",
            "kind": "derived",
            "status": "inference",
            "question": "Когда?",
            "fields": {
                "action": {
                    "text": "Следуйте совету, только когда условие выполнено.",
                    "claim_ids": ["CLM-1"],
                    "evidence_refs": ["EVD-1"],
                }
            },
            "gaps": ["Нет независимого примера"],
        }
        self.plan["chapters"][0]["decision_cards"] = [card]
        handoff, report = compile_handoff(self.root, self.plan)
        self.assertEqual(handoff["status"], "research_ready_with_gaps")
        self.assertEqual(handoff["chapters"][0]["decision_cards"], [card])
        self.assertTrue(report["warnings"])
        card["fields"]["action"]["evidence_refs"] = ["unknown"]
        self.assertEqual(
            compile_handoff(self.root, self.plan)[0]["status"], "research_blocked"
        )

    def test_counterevidence_keeps_inspected_quote_and_missing_record_blocks(self):
        path = self.root / "claims.jsonl"
        claim = json.loads(path.read_text())
        claim["challenging_evidence_ids"] = ["EVD-2"]
        path.write_text(json.dumps(claim), encoding="utf-8")
        self.audit["claim_sha256"] = handoff_module.record_sha256(claim)
        (self.root / "semantic-audit.jsonl").write_text(
            json.dumps(self.audit), encoding="utf-8"
        )
        self.assertEqual(
            compile_handoff(self.root, self.plan)[0]["status"], "research_blocked"
        )
        counter = {
            "evidence_id": "EVD-2",
            "source_id": "SRC-1",
            "quote": "Другая проверенная информация.",
            "relationship": "challenges",
            "claim_ids": ["CLM-1"],
            "locator": "p2",
        }
        with (self.root / "evidence.jsonl").open("a", encoding="utf-8") as handle:
            handle.write("\n" + json.dumps(counter))
        handoff, report = compile_handoff(self.root, self.plan)
        self.assertEqual(handoff["status"], "research_ready", report)
        record = handoff["claims"][0]["research_context"]["counterevidence"][0]
        self.assertEqual(record["quote"], counter["quote"])
        self.assertEqual(record["evidence_context"]["relationship"], "challenges")
        self.assertEqual(
            record["content_sha256"], handoff["sources"][0]["content_sha256"]
        )
        self.assertEqual(record["semantic_reviews"], [])

    def test_contradiction_resolution_context_survives(self):
        row = {
            "contradiction_id": "CTR-1",
            "claim_id": "CLM-1",
            "outcome": "narrowed",
            "reason": "Only for the tested population",
            "counter_evidence_ids": [],
        }
        (self.root / "contradictions.jsonl").write_text(
            json.dumps(row), encoding="utf-8"
        )
        handoff, report = compile_handoff(self.root, self.plan)
        self.assertEqual(report["blocking"], [])
        self.assertEqual(
            handoff["claims"][0]["research_context"]["contradictions"],
            [{**row, "record_sha256": handoff_module.record_sha256(row)}],
        )

    def test_review_digests_only_reports_hashes(self):
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        output = io.StringIO()
        with (
            patch.object(
                sys,
                "argv",
                ["editorial_handoff.py", str(self.root), "--review-digests"],
            ),
            redirect_stdout(output),
        ):
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
