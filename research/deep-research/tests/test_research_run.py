#!/usr/bin/env python3
"""Integration tests for persistent research-run tooling."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "scripts/init_research_run.py"
VALIDATE = ROOT / "scripts/validate_research_run.py"
MIGRATE = ROOT / "scripts/migrate_research_bundle.py"
FINGERPRINT = ROOT / "scripts/fingerprint_research_sources.py"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    text = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records)
    path.write_text(text, encoding="utf-8")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_bundle(run: Path, *, stage: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATE), str(run), "--stage", stage],
        check=False,
        capture_output=True,
        text=True,
    )


def write_minimal_linked_fixture(run: Path) -> None:
    write_jsonl(
        run / "queries.jsonl",
        [
            {
                "query_id": "QRY-0001",
                "pass": "discovery",
                "family": "primary",
                "query": "editor-ready fixture query",
                "executed_at": "2026-09-01T07:50:00Z",
                "status": "executed",
                "result_source_ids": ["SRC-0001"],
                "deliverable_section_ids": ["SEC-0001"],
            }
        ],
    )
    write_jsonl(
        run / "sources.jsonl",
        [
            {
                "source_id": "SRC-0001",
                "title": "Inspected editor-ready fixture source",
                "requested_url": "https://example.com/source",
                "final_url": "https://example.com/source",
                "accessed_at": "2026-09-01T07:55:00Z",
                "access_integrity": "full",
                "source_type": "official",
                "lineage_id": "LIN-0001",
                "mutable": False,
                "fingerprint_status": "exempt",
                "fingerprint_reason": "Immutable offline test fixture.",
            }
        ],
    )
    write_jsonl(
        run / "evidence.jsonl",
        [
            {
                "evidence_id": "EVD-0001",
                "source_id": "SRC-0001",
                "claim_ids": ["CLM-0001"],
                "relationship": "supports",
                "locator": {"section": "Fixture"},
                "evidence_type": "fact",
                "faithful_paraphrase": "Fixture evidence for validation only.",
                "deliverable_section_ids": ["SEC-0001"],
                "output_disposition": "main",
            }
        ],
    )
    write_jsonl(
        run / "claims.jsonl",
        [
            {
                "claim_id": "CLM-0001",
                "claim": "Fixture claim for editor-ready validation only.",
                "importance": "critical",
                "status": "supported",
                "confidence": "HIGH",
                "supporting_evidence_ids": ["EVD-0001"],
                "challenging_evidence_ids": [],
                "challenge_search": {"query_ids": ["QRY-0001"], "result": "none_found"},
                "deliverable_section_ids": ["SEC-0001"],
                "output_disposition": "main",
            }
        ],
    )
    write_jsonl(
        run / "semantic-audit.jsonl",
        [
            {
                "semantic_audit_id": "SEM-0001",
                "claim_id": "CLM-0001",
                "evidence_id": "EVD-0001",
                "source_id": "SRC-0001",
                "semantic_support": "exact",
                "scope_match": True,
                "authority_match": True,
                "freshness_match": True,
                "evidence_type_match": True,
                "reviewer_status": "pass",
                "reviewer_basis": "Exact offline fixture support.",
                "audited_at": "2026-09-01T07:58:00Z",
            }
        ],
    )


def write_editor_ready_plan(run: Path, *, status: str = "covered") -> None:
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    write_json(
        run / "plan.json",
        {
            "coverage_contract_version": "1.0",
            "research_id": manifest["research_id"],
            "updated_at": "2026-09-01T07:45:00Z",
            "deliverable_outline": [
                {
                    "section_id": "SEC-0001",
                    "working_title": "Проверяемый раздел",
                    "reader_question": "Что должен узнать читатель?",
                    "readiness_condition": (
                        "Раздел содержит подтверждённый вывод и понятное ограничение."
                    ),
                    "status": status,
                    "coverage_note": (
                        "Проверен по связанным записям."
                        if status == "covered"
                        else ""
                    ),
                }
            ],
            "source_emphasis": {"x": "standard", "youtube": "standard"},
        },
    )


def write_editor_ready_bank(run: Path) -> None:
    (run / "useful-data.md").write_text(
        "# Банк полезных данных\n\n"
        "## SEC-0001 · Проверяемый раздел\n\n"
        "Этот банк хранит проверенные вспомогательные наблюдения, ограничения и "
        "контекст, которые редактор может безопасно добавить в материал, не меняя "
        "основной вывод исследования.\n",
        encoding="utf-8",
    )


def write_editor_ready_handoff(run: Path, *, coverage: str = "pass") -> None:
    (run / "handoff.md").write_text(
        "# Research Handoff\n\n"
        "delivery_status: not_ready\n"
        "output_profile: editor-ready\n"
        "audit_status: pass\n"
        "clarity_preservation: pass\n"
        f"coverage_preservation: {coverage}\n"
        "bundle_validation: pass\n\n"
        "The incomplete fixture passed structural preservation checks.\n",
        encoding="utf-8",
    )


def populate_editor_ready_reviews(run: Path) -> dict[str, object]:
    audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
    audit["audit_status"] = "pass"
    audit["clarity_review"] = {
        "status": "pass",
        "claims_preserved": True,
        "numbers_preserved": True,
        "scope_preserved": True,
        "citations_preserved": True,
        "limitations_preserved": True,
        "contradictions_preserved": True,
        "reviewed_at": "2026-09-01T08:00:00Z",
        "reviewed_claim_ids": ["CLM-0001"],
        "report_sha256": file_sha256(run / "report.md"),
        "claims_sha256": file_sha256(run / "claims.jsonl"),
        "sources_sha256": file_sha256(run / "sources.jsonl"),
    }
    audit["coverage_review"] = {
        "status": "pass",
        "sections_covered": True,
        "dispositions_preserved": True,
        "reviewed_at": "2026-09-01T08:00:00Z",
        "reviewed_record_ids": ["EVD-0001", "CLM-0001"],
        "omitted_record_ids": [],
        "section_results": [
            {
                "section_id": "SEC-0001",
                "status": "covered",
                "record_ids": ["EVD-0001", "CLM-0001"],
                "note": "Раздел проверен по связанным данным.",
            }
        ],
        "manifest_sha256": file_sha256(run / "manifest.json"),
        "plan_sha256": file_sha256(run / "plan.json"),
        "queries_sha256": file_sha256(run / "queries.jsonl"),
        "sources_sha256": file_sha256(run / "sources.jsonl"),
        "evidence_sha256": file_sha256(run / "evidence.jsonl"),
        "claims_sha256": file_sha256(run / "claims.jsonl"),
        "community_sha256": file_sha256(run / "community.jsonl"),
        "contradictions_sha256": file_sha256(run / "contradictions.jsonl"),
        "checkpoints_sha256": file_sha256(run / "checkpoints.jsonl"),
        "semantic_audit_sha256": file_sha256(run / "semantic-audit.jsonl"),
        "report_sha256": file_sha256(run / "report.md"),
        "useful_data_sha256": file_sha256(run / "useful-data.md"),
        "appendix_sha256": None,
    }
    write_json(run / "audit.json", audit)
    return audit


def prepare_editor_ready_final(run: Path) -> dict[str, object]:
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    manifest["status"] = "incomplete"
    write_json(run / "manifest.json", manifest)
    write_editor_ready_plan(run)
    write_minimal_linked_fixture(run)
    (run / "report.md").write_text(
        "# Рабочий заголовок\n\n"
        "*Актуально на 1 сентября 2026 года.*\n\n"
        "## Коротко\n\n"
        "Основной вывод подтверждает [проверенный источник]"
        "(https://example.com/source#fixture). Границы вывода названы рядом.\n\n"
        "## Что важно не исказить\n\n"
        "Результат относится только к указанному периоду и аудитории.\n",
        encoding="utf-8",
    )
    write_editor_ready_bank(run)
    audit = populate_editor_ready_reviews(run)
    write_editor_ready_handoff(run)
    return audit


class ResearchRunToolsTest(unittest.TestCase):
    def initialize(
        self,
        parent: Path,
        *,
        output_profile: str | None = None,
        depth: str = "deep",
    ) -> Path:
        run = parent / "run"
        command = [
            sys.executable,
            str(INIT),
            str(run),
            "--question",
            "What exactly determines the current mechanic?",
            "--depth",
            depth,
            "--domain",
            "hearthstone",
        ]
        if output_profile is not None:
            command.extend(["--output-profile", output_profile])
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return run

    def assert_hidden_record_id_rejected(self, hidden_id: str) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            evidence = json.loads((run / "evidence.jsonl").read_text(encoding="utf-8"))
            evidence["output_disposition"] = "useful_data"
            evidence["useful_data_types"] = ["number"]
            write_jsonl(run / "evidence.jsonl", [evidence])
            (run / "useful-data.md").write_text(
                "# Банк полезных данных\n\n"
                "## Проверенное наблюдение\n\n"
                f"{hidden_id}\n\n"
                "Этот обычный абзац содержит больше шестидесяти знаков полезного "
                "текста, но идентификатор записи присутствует только внутри блока "
                "разметки, скрытого от читателя. "
                "[Источник](https://example.com/source#fixture)\n",
                encoding="utf-8",
            )
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["coverage_review"]["evidence_sha256"] = file_sha256(
                run / "evidence.jsonl"
            )
            audit["coverage_review"]["useful_data_sha256"] = file_sha256(
                run / "useful-data.md"
            )
            write_json(run / "audit.json", audit)

            result = validate_bundle(run, stage="final")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing useful_data record EVD-0001", result.stdout)

    def test_initializer_defaults_to_research_report_output_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp))
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["output_profile"], "research-report")
            self.assertNotIn("coverage_contract_version", manifest)
            self.assertFalse((run / "plan.json").exists())
            self.assertFalse((run / "useful-data.md").exists())
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            self.assertNotIn("coverage_review", audit)

    def test_initializer_accepts_editor_ready_output_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["output_profile"], "editor-ready")
            self.assertEqual(manifest["coverage_contract_version"], "1.0")
            plan = json.loads((run / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["coverage_contract_version"], "1.0")
            self.assertEqual(plan["research_id"], manifest["research_id"])
            self.assertEqual(plan["deliverable_outline"], [])
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["coverage_review"]["status"], "not_run")
            self.assertEqual(audit["coverage_review"]["reviewed_record_ids"], [])
            self.assertTrue((run / "useful-data.md").is_file())
            self.assertIn(
                "not-yet-populated",
                (run / "useful-data.md").read_text(encoding="utf-8"),
            )
            handoff = (run / "handoff.md").read_text(encoding="utf-8")
            self.assertIn("Output profile: `editor-ready`", handoff)
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "working"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_legacy_editor_ready_without_coverage_contract_still_passes_working(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            manifest.pop("coverage_contract_version")
            write_json(run / "manifest.json", manifest)
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit.pop("coverage_review")
            write_json(run / "audit.json", audit)
            (run / "plan.json").unlink()
            (run / "useful-data.md").unlink()

            result = validate_bundle(run, stage="working")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(
                "legacy editor-ready bundle without coverage contract", result.stdout
            )

    def test_legacy_editor_ready_without_coverage_contract_still_passes_final(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            manifest.pop("coverage_contract_version")
            write_json(run / "manifest.json", manifest)
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit.pop("coverage_review")
            write_json(run / "audit.json", audit)
            (run / "plan.json").unlink()
            (run / "useful-data.md").unlink()

            result = validate_bundle(run, stage="final")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(
                "legacy editor-ready bundle without coverage contract", result.stdout
            )

    def test_initializer_rejects_raw_research_as_modifier(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            result = subprocess.run(
                [
                    sys.executable,
                    str(INIT),
                    str(run),
                    "--question",
                    "What exactly determines the current mechanic?",
                    "--modifier",
                    "raw-research",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--output-profile raw-research", result.stderr)
            self.assertFalse(run.exists())

    def test_invalid_manifest_output_profile_fails_validation(self) -> None:
        for invalid_profile in ("publication-ready", [], {}):
            with self.subTest(invalid_profile=invalid_profile), tempfile.TemporaryDirectory() as temp:
                run = self.initialize(Path(temp))
                manifest = json.loads(
                    (run / "manifest.json").read_text(encoding="utf-8")
                )
                manifest["output_profile"] = invalid_profile
                write_json(run / "manifest.json", manifest)
                result = subprocess.run(
                    [sys.executable, str(VALIDATE), str(run), "--stage", "working"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("invalid output_profile", result.stdout)
                self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_legacy_schema_1_0_without_output_profile_still_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp))
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            manifest["schema_version"] = "1.0"
            manifest.pop("output_profile")
            write_json(run / "manifest.json", manifest)
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "working"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("legacy schema without output_profile", result.stdout)
            self.assertIn("assuming research-report", result.stdout)

    def test_schema_1_1_without_output_profile_is_inferred_but_cannot_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp))
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            manifest.pop("output_profile")
            manifest["schema_version"] = "1.1"
            write_json(run / "manifest.json", manifest)
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "working"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("legacy schema 1.1 is missing output_profile", result.stdout)
            final = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "final"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(final.returncode, 0)
            self.assertIn("explicit backfill is required for final", final.stdout)

    def test_legacy_raw_modifier_is_inferred_only_for_schema_1_0(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp))
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            manifest["schema_version"] = "1.0"
            manifest.pop("output_profile")
            manifest["modifiers"] = ["raw-research"]
            write_json(run / "manifest.json", manifest)
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "working"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("assuming raw-research", result.stdout)

    def test_raw_research_is_not_accepted_as_a_new_modifier(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp))
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            manifest["modifiers"] = ["raw-research"]
            write_json(run / "manifest.json", manifest)
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "working"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be output_profile, not a modifier", result.stdout)

    def test_initialized_run_passes_working_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp))
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "working"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Research bundle: PASS", result.stdout)

    def test_editor_ready_final_requires_clarity_preservation_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            manifest["status"] = "incomplete"
            write_json(run / "manifest.json", manifest)
            write_editor_ready_plan(run)
            write_editor_ready_bank(run)

            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["audit_status"] = "pass"
            write_json(run / "audit.json", audit)
            report_path = run / "report.md"
            report_path.write_text(
                "# Рабочий заголовок\n\n"
                "*Актуально на 1 сентября 2026 года.*\n\n"
                "## Коротко\n\n"
                "Основной вывод подтверждает [проверенный источник]"
                "(https://example.com/source#fixture). Границы вывода названы рядом.\n\n"
                "## Что важно не исказить\n\n"
                "Результат относится только к указанному периоду и аудитории.\n",
                encoding="utf-8",
            )
            (run / "handoff.md").write_text(
                "# Research Handoff\n\n"
                "delivery_status: not_ready\n"
                "output_profile: editor-ready\n"
                "audit_status: pass\n"
                "clarity_preservation: fail\n"
                "coverage_preservation: fail\n"
                "bundle_validation: pass\n\n"
                "This fixture is incomplete until the preservation review passes.\n",
                encoding="utf-8",
            )

            blocked = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "final"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("clarity_review.status=pass", blocked.stdout)
            self.assertIn("requires at least one claim record", blocked.stdout)

            write_minimal_linked_fixture(run)
            audit = populate_editor_ready_reviews(run)
            (run / "handoff.md").write_text(
                "# Research Handoff\n\n"
                "delivery_status: not_ready\n"
                "output_profile: editor-ready\n"
                "audit_status: pass\n"
                "clarity_preservation: pass\n"
                "coverage_preservation: pass\n"
                "bundle_validation: pass\n\n"
                "The incomplete fixture passed structural preservation checks.\n",
                encoding="utf-8",
            )
            passed = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "final"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
            self.assertIn("Research bundle: PASS", passed.stdout)

            claims_path = run / "claims.jsonl"
            valid_claims = claims_path.read_text(encoding="utf-8")
            for invalid_value in ("critcal", [], {}):
                typo_claim = json.loads(valid_claims)
                typo_claim["importance"] = invalid_value
                write_jsonl(claims_path, [typo_claim])
                audit["clarity_review"]["claims_sha256"] = file_sha256(claims_path)
                write_json(run / "audit.json", audit)
                invalid_importance = subprocess.run(
                    [sys.executable, str(VALIDATE), str(run), "--stage", "final"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(invalid_importance.returncode, 0)
                self.assertIn("invalid importance", invalid_importance.stdout)
                self.assertNotIn(
                    "Traceback",
                    invalid_importance.stdout + invalid_importance.stderr,
                )
            claims_path.write_text(valid_claims, encoding="utf-8")
            audit["clarity_review"]["claims_sha256"] = file_sha256(claims_path)
            write_json(run / "audit.json", audit)

            report_path.write_text(
                report_path.read_text(encoding="utf-8").replace(
                    "(https://example.com/source#fixture)",
                    '(https://example.com/source#fixture "Проверенный источник")',
                ),
                encoding="utf-8",
            )
            audit["clarity_review"]["report_sha256"] = file_sha256(report_path)
            audit["coverage_review"]["report_sha256"] = file_sha256(report_path)
            write_json(run / "audit.json", audit)
            titled_link = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "final"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                titled_link.returncode,
                0,
                titled_link.stdout + titled_link.stderr,
            )

            valid_report = report_path.read_text(encoding="utf-8")
            for replacement in (
                "https://www.example.com/source#fixture",
                "https://example.com/source/#fixture",
            ):
                report_path.write_text(
                    valid_report.replace(
                        "https://example.com/source#fixture", replacement
                    ),
                    encoding="utf-8",
                )
                audit["clarity_review"]["report_sha256"] = file_sha256(report_path)
                audit["coverage_review"]["report_sha256"] = file_sha256(report_path)
                write_json(run / "audit.json", audit)
                unsafe_alias = subprocess.run(
                    [sys.executable, str(VALIDATE), str(run), "--stage", "final"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(unsafe_alias.returncode, 0)
                self.assertIn("missing from sources.jsonl", unsafe_alias.stdout)
            report_path.write_text(valid_report, encoding="utf-8")
            audit["clarity_review"]["report_sha256"] = file_sha256(report_path)
            audit["coverage_review"]["report_sha256"] = file_sha256(report_path)
            write_json(run / "audit.json", audit)

            handoff_path = run / "handoff.md"
            valid_handoff = handoff_path.read_text(encoding="utf-8")
            for duplicate_value in ("not_ready", "ready"):
                handoff_path.write_text(
                    valid_handoff
                    + f"\ndelivery_status: {duplicate_value}\n",
                    encoding="utf-8",
                )
                duplicate_handoff = subprocess.run(
                    [sys.executable, str(VALIDATE), str(run), "--stage", "final"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(duplicate_handoff.returncode, 0)
                self.assertIn(
                    "delivery_status appears more than once",
                    duplicate_handoff.stdout,
                )
            handoff_path.write_text(
                valid_handoff.replace(
                    "delivery_status: not_ready",
                    "<!--\ndelivery_status: not_ready\n-->",
                ),
                encoding="utf-8",
            )
            commented_handoff = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "final"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(commented_handoff.returncode, 0)
            self.assertIn("missing or invalid delivery_status", commented_handoff.stdout)
            handoff_path.write_text(valid_handoff, encoding="utf-8")

            handoff_path.write_text(
                valid_handoff.replace("delivery_status: not_ready", "delivery_status: ready"),
                encoding="utf-8",
            )
            false_ready = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "final"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(false_ready.returncode, 0)
            self.assertIn("incomplete research requires", false_ready.stdout)

            handoff_path.write_text(
                valid_handoff.replace("bundle_validation: pass", "bundle_validation: fail"),
                encoding="utf-8",
            )
            invalid_handoff = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "final"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(invalid_handoff.returncode, 0)
            self.assertIn("requires bundle_validation: pass", invalid_handoff.stdout)
            handoff_path.write_text(valid_handoff, encoding="utf-8")

            sources_path = run / "sources.jsonl"
            valid_sources = sources_path.read_text(encoding="utf-8")
            source_record = json.loads(valid_sources)
            for invalid_url in (
                "https://example.com:bad/path",
                "https://exa_mple.com/source",
                "https://-bad.example/source",
                "https://.example.com/source",
                "https://example..com/source",
                "https://exa mple.com/source",
            ):
                source_record["requested_url"] = invalid_url
                source_record["final_url"] = invalid_url
                write_jsonl(sources_path, [source_record])
                audit["clarity_review"]["sources_sha256"] = file_sha256(sources_path)
                write_json(run / "audit.json", audit)
                malformed_url = subprocess.run(
                    [sys.executable, str(VALIDATE), str(run), "--stage", "final"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(malformed_url.returncode, 0)
                self.assertIn("invalid requested_url", malformed_url.stdout)
                self.assertNotIn(
                    "Traceback", malformed_url.stdout + malformed_url.stderr
                )
            sources_path.write_text(valid_sources, encoding="utf-8")
            audit["clarity_review"]["sources_sha256"] = file_sha256(sources_path)
            write_json(run / "audit.json", audit)

            report_path.write_text(
                report_path.read_text(encoding="utf-8")
                + "\nМатериал изменён после проверки.\n",
                encoding="utf-8",
            )
            changed = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "final"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn("report_sha256 does not match", changed.stdout)

    def test_editor_ready_working_requires_plan_and_known_section_links(self) -> None:
        with self.subTest(case="missing_plan"), tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            write_minimal_linked_fixture(run)
            (run / "plan.json").unlink()

            missing_plan = validate_bundle(run, stage="working")

            self.assertNotEqual(missing_plan.returncode, 0)
            self.assertIn("plan.json", missing_plan.stdout)
            self.assertNotIn("Traceback", missing_plan.stdout + missing_plan.stderr)

        with self.subTest(case="missing_section_link"), tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            write_editor_ready_plan(run, status="researching")
            write_minimal_linked_fixture(run)
            evidence = json.loads((run / "evidence.jsonl").read_text(encoding="utf-8"))
            evidence.pop("deliverable_section_ids")
            write_jsonl(run / "evidence.jsonl", [evidence])

            missing_link = validate_bundle(run, stage="working")

            self.assertNotEqual(missing_link.returncode, 0)
            self.assertIn("deliverable_section_ids", missing_link.stdout)
            self.assertNotIn("Traceback", missing_link.stdout + missing_link.stderr)

        with self.subTest(case="unknown_section"), tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            write_editor_ready_plan(run, status="researching")
            write_minimal_linked_fixture(run)
            query = json.loads((run / "queries.jsonl").read_text(encoding="utf-8"))
            query["deliverable_section_ids"] = ["SEC-9999"]
            write_jsonl(run / "queries.jsonl", [query])

            unknown_section = validate_bundle(run, stage="working")

            self.assertNotEqual(unknown_section.returncode, 0)
            self.assertIn("unknown deliverable section SEC-9999", unknown_section.stdout)
            self.assertNotIn(
                "Traceback", unknown_section.stdout + unknown_section.stderr
            )

    def test_editor_ready_working_rejects_invalid_or_unexplained_disposition(self) -> None:
        cases = (
            ("primary", "invalid output_disposition"),
            ("omit", "omit requires output_omit_reason"),
        )
        for disposition, expected_error in cases:
            with self.subTest(disposition=disposition), tempfile.TemporaryDirectory() as temp:
                run = self.initialize(Path(temp), output_profile="editor-ready")
                write_editor_ready_plan(run, status="researching")
                write_minimal_linked_fixture(run)
                evidence = json.loads(
                    (run / "evidence.jsonl").read_text(encoding="utf-8")
                )
                evidence["output_disposition"] = disposition
                evidence.pop("output_omit_reason", None)
                write_jsonl(run / "evidence.jsonl", [evidence])

                result = validate_bundle(run, stage="working")

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stdout)
                self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_editor_ready_final_rejects_unfinished_plan_section(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            write_editor_ready_plan(run, status="researching")
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["coverage_review"]["plan_sha256"] = file_sha256(run / "plan.json")
            audit["coverage_review"]["section_results"][0]["status"] = "researching"
            write_json(run / "audit.json", audit)

            result = validate_bundle(run, stage="final")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SEC-0001", result.stdout)
            self.assertIn("must be covered, excluded, or unresolved", result.stdout)

    def test_editor_ready_final_requires_useful_data_bank_for_deep_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            (run / "useful-data.md").unlink()

            result = validate_bundle(run, stage="final")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("useful-data.md", result.stdout)
            self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_editor_ready_final_requires_complete_coverage_review(self) -> None:
        with self.subTest(case="missing_reviewed_id"), tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["coverage_review"]["reviewed_record_ids"] = ["EVD-0001"]
            write_json(run / "audit.json", audit)

            incomplete_review = validate_bundle(run, stage="final")

            self.assertNotEqual(incomplete_review.returncode, 0)
            self.assertIn("reviewed_record_ids", incomplete_review.stdout)
            self.assertIn("CLM-0001", incomplete_review.stdout)

        with self.subTest(case="plan_hash_mismatch"), tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            plan = json.loads((run / "plan.json").read_text(encoding="utf-8"))
            plan["deliverable_outline"][0]["working_title"] = "Изменённый раздел"
            write_json(run / "plan.json", plan)

            stale_review = validate_bundle(run, stage="final")

            self.assertNotEqual(stale_review.returncode, 0)
            self.assertIn("plan_sha256", stale_review.stdout)
            self.assertIn("does not match", stale_review.stdout)

    def test_editor_ready_appendix_disposition_requires_appendix_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            evidence = json.loads((run / "evidence.jsonl").read_text(encoding="utf-8"))
            evidence["output_disposition"] = "appendix"
            write_jsonl(run / "evidence.jsonl", [evidence])
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["coverage_review"]["evidence_sha256"] = file_sha256(
                run / "evidence.jsonl"
            )
            write_json(run / "audit.json", audit)

            result = validate_bundle(run, stage="final")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("evidence-appendix.md", result.stdout)
            self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_editor_ready_useful_data_requires_id_and_visible_source_link(self) -> None:
        bank_cases = (
            (
                "missing_id",
                "# Банк полезных данных\n\n"
                "## Проверенное наблюдение\n\n"
                "Подробное вспомогательное наблюдение подтверждает "
                "[проверенный источник](https://example.com/source#fixture), но "
                "идентификатор записи здесь намеренно пропущен.\n",
                "missing useful_data record EVD-0001",
            ),
            (
                "missing_link",
                "# Банк полезных данных\n\n"
                "## EVD-0001 · Проверенное наблюдение\n\n"
                "Подробное вспомогательное наблюдение сохранено вместе с "
                "ограничениями, но видимая ссылка на проверенный источник здесь "
                "намеренно пропущена.\n",
                "visible inspected source link",
            ),
        )
        for case, bank_text, expected_error in bank_cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                run = self.initialize(Path(temp), output_profile="editor-ready")
                prepare_editor_ready_final(run)
                evidence = json.loads(
                    (run / "evidence.jsonl").read_text(encoding="utf-8")
                )
                evidence["output_disposition"] = "useful_data"
                evidence["useful_data_types"] = ["number"]
                write_jsonl(run / "evidence.jsonl", [evidence])
                (run / "useful-data.md").write_text(bank_text, encoding="utf-8")
                audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
                audit["coverage_review"]["evidence_sha256"] = file_sha256(
                    run / "evidence.jsonl"
                )
                audit["coverage_review"]["useful_data_sha256"] = file_sha256(
                    run / "useful-data.md"
                )
                write_json(run / "audit.json", audit)

                result = validate_bundle(run, stage="final")

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stdout)
                self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_editor_ready_valid_useful_data_artifact_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            evidence = json.loads((run / "evidence.jsonl").read_text(encoding="utf-8"))
            evidence["output_disposition"] = "useful_data"
            evidence["useful_data_types"] = ["number", "comparison"]
            write_jsonl(run / "evidence.jsonl", [evidence])
            (run / "useful-data.md").write_text(
                "# Банк полезных данных\n\n"
                "## EVD-0001 · Проверенное наблюдение\n\n"
                "Запись сохраняет конкретное число, сравнение и ограничение из "
                "[проверенного источника](https://example.com/source#fixture), "
                "чтобы редактор мог безопасно вернуть деталь в основной материал.\n",
                encoding="utf-8",
            )
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["coverage_review"]["evidence_sha256"] = file_sha256(
                run / "evidence.jsonl"
            )
            audit["coverage_review"]["useful_data_sha256"] = file_sha256(
                run / "useful-data.md"
            )
            write_json(run / "audit.json", audit)

            result = validate_bundle(run, stage="final")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_editor_ready_valid_appendix_artifact_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            evidence = json.loads((run / "evidence.jsonl").read_text(encoding="utf-8"))
            evidence["output_disposition"] = "appendix"
            write_jsonl(run / "evidence.jsonl", [evidence])
            appendix_path = run / "evidence-appendix.md"
            appendix_path.write_text(
                "# Приложение с доказательствами\n\n"
                "## EVD-0001 · Проверенная деталь\n\n"
                "Приложение сохраняет локатор, краткое объяснение и "
                "[проверенный источник](https://example.com/source#fixture), "
                "который подтверждает связанную запись доказательства.\n",
                encoding="utf-8",
            )
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["coverage_review"]["evidence_sha256"] = file_sha256(
                run / "evidence.jsonl"
            )
            audit["coverage_review"]["appendix_sha256"] = file_sha256(appendix_path)
            write_json(run / "audit.json", audit)

            result = validate_bundle(run, stage="final")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_editor_ready_review_hashes_freeze_evidence_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            evidence = json.loads((run / "evidence.jsonl").read_text(encoding="utf-8"))
            evidence["faithful_paraphrase"] += " Changed after coverage review."
            write_jsonl(run / "evidence.jsonl", [evidence])

            result = validate_bundle(run, stage="final")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("coverage_review.evidence_sha256", result.stdout)
            self.assertIn("does not match", result.stdout)

    def test_decision_relevant_claims_must_be_routed_to_main(self) -> None:
        cases = (
            ("critical", "useful_data"),
            ("material", "appendix"),
        )
        for importance, disposition in cases:
            with (
                self.subTest(importance=importance, disposition=disposition),
                tempfile.TemporaryDirectory() as temp,
            ):
                run = self.initialize(Path(temp), output_profile="editor-ready")
                write_editor_ready_plan(run, status="researching")
                write_minimal_linked_fixture(run)
                claim = json.loads(
                    (run / "claims.jsonl").read_text(encoding="utf-8")
                )
                claim["importance"] = importance
                claim["output_disposition"] = disposition
                if disposition == "useful_data":
                    claim["useful_data_types"] = ["advice"]
                write_jsonl(run / "claims.jsonl", [claim])

                result = validate_bundle(run, stage="working")

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "critical or material claim must use output_disposition main",
                    result.stdout,
                )

    def test_covered_section_requires_a_claim_routed_to_main(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            claim = json.loads((run / "claims.jsonl").read_text(encoding="utf-8"))
            claim["importance"] = "supporting"
            claim["output_disposition"] = "useful_data"
            claim["useful_data_types"] = ["advice"]
            write_jsonl(run / "claims.jsonl", [claim])
            (run / "useful-data.md").write_text(
                "# Банк полезных данных\n\n"
                "## CLM-0001 · Вспомогательный вывод\n\n"
                "Эта запись сохраняет подробный совет, границы применимости и "
                "[проверенный источник](https://example.com/source#fixture), "
                "чтобы редактор мог использовать вывод без потери контекста.\n",
                encoding="utf-8",
            )
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["clarity_review"]["claims_sha256"] = file_sha256(
                run / "claims.jsonl"
            )
            audit["coverage_review"]["claims_sha256"] = file_sha256(
                run / "claims.jsonl"
            )
            audit["coverage_review"]["useful_data_sha256"] = file_sha256(
                run / "useful-data.md"
            )
            write_json(run / "audit.json", audit)

            result = validate_bundle(run, stage="final")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "covered section has no claim routed to output_disposition main",
                result.stdout,
            )

    def test_commented_record_id_and_global_link_are_not_record_material(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            evidence = json.loads((run / "evidence.jsonl").read_text(encoding="utf-8"))
            evidence["output_disposition"] = "useful_data"
            evidence["useful_data_types"] = ["number"]
            write_jsonl(run / "evidence.jsonl", [evidence])
            (run / "useful-data.md").write_text(
                "# Банк полезных данных\n\n"
                "[Общий список источников](https://example.com/source#fixture)\n\n"
                "<!-- ## EVD-0001 · Скрытая запись -->\n\n"
                "## Общие заметки\n\n"
                "Этот длинный общий абзац содержит достаточно слов для обычного "
                "материала, но не является видимой записью конкретного "
                "доказательства и поэтому не должен удовлетворять контракту.\n",
                encoding="utf-8",
            )
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["coverage_review"]["evidence_sha256"] = file_sha256(
                run / "evidence.jsonl"
            )
            audit["coverage_review"]["useful_data_sha256"] = file_sha256(
                run / "useful-data.md"
            )
            write_json(run / "audit.json", audit)

            result = validate_bundle(run, stage="final")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing useful_data record EVD-0001", result.stdout)

    def test_record_block_must_link_its_own_source_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            evidence = json.loads((run / "evidence.jsonl").read_text(encoding="utf-8"))
            evidence["output_disposition"] = "useful_data"
            evidence["useful_data_types"] = ["number"]
            write_jsonl(run / "evidence.jsonl", [evidence])
            source = json.loads((run / "sources.jsonl").read_text(encoding="utf-8"))
            other_source = dict(source)
            other_source.update(
                {
                    "source_id": "SRC-0002",
                    "title": "Different inspected source",
                    "requested_url": "https://example.com/other",
                    "final_url": "https://example.com/other",
                    "lineage_id": "LIN-0002",
                }
            )
            write_jsonl(run / "sources.jsonl", [source, other_source])
            (run / "useful-data.md").write_text(
                "# Банк полезных данных\n\n"
                "## EVD-0001 · Проверенное наблюдение\n\n"
                "Запись содержит подробное число, сравнение и ограничение, но "
                "ссылается на [другой проверенный источник]"
                "(https://example.com/other), не связанный с этим доказательством.\n",
                encoding="utf-8",
            )
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["clarity_review"]["sources_sha256"] = file_sha256(
                run / "sources.jsonl"
            )
            audit["coverage_review"]["sources_sha256"] = file_sha256(
                run / "sources.jsonl"
            )
            audit["coverage_review"]["evidence_sha256"] = file_sha256(
                run / "evidence.jsonl"
            )
            audit["coverage_review"]["useful_data_sha256"] = file_sha256(
                run / "useful-data.md"
            )
            write_json(run / "audit.json", audit)

            result = validate_bundle(run, stage="final")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "visible inspected source link matching its evidence", result.stdout
            )

    def test_malformed_utf8_and_nul_snapshot_path_fail_without_traceback(self) -> None:
        with self.subTest(case="json"), tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp))
            (run / "manifest.json").write_bytes(b"\xff")

            result = validate_bundle(run, stage="working")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("manifest.json: invalid JSON", result.stdout)
            self.assertNotIn("Traceback", result.stdout + result.stderr)

        with self.subTest(case="jsonl"), tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp))
            (run / "claims.jsonl").write_bytes(b'{"claim_id":"CLM-\xff"}\n')

            result = validate_bundle(run, stage="working")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("claims.jsonl: cannot read", result.stdout)
            self.assertNotIn("Traceback", result.stdout + result.stderr)

        with self.subTest(case="nul_snapshot"), tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp))
            write_jsonl(
                run / "sources.jsonl",
                [
                    {
                        "source_id": "SRC-0001",
                        "title": "Invalid snapshot fixture",
                        "requested_url": "https://example.com/source",
                        "final_url": "https://example.com/source",
                        "accessed_at": "2026-09-01T07:55:00Z",
                        "access_integrity": "full",
                        "source_type": "official",
                        "lineage_id": "LIN-0001",
                        "mutable": True,
                        "fingerprint_status": "verified",
                        "content_sha256": "0" * 64,
                        "content_bytes": 0,
                        "fingerprinted_at": "2026-09-01T07:56:00Z",
                        "snapshot_path": "snapshots/\u0000invalid",
                    }
                ],
            )

            result = validate_bundle(run, stage="working")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid snapshot_path", result.stdout)
            self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_coverage_plan_and_review_notes_require_non_empty_strings(self) -> None:
        invalid_plan_fields = (
            ("working_title", []),
            ("reader_question", "   "),
            ("readiness_condition", {}),
        )
        for field, invalid_value in invalid_plan_fields:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                run = self.initialize(Path(temp), output_profile="editor-ready")
                write_editor_ready_plan(run, status="researching")
                plan = json.loads((run / "plan.json").read_text(encoding="utf-8"))
                plan["deliverable_outline"][0][field] = invalid_value
                write_json(run / "plan.json", plan)

                result = validate_bundle(run, stage="working")

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"{field} must be a non-empty string", result.stdout)

        with self.subTest(field="coverage_note"), tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            plan = json.loads((run / "plan.json").read_text(encoding="utf-8"))
            section = plan["deliverable_outline"][0]
            section["status"] = "excluded"
            section["coverage_note"] = "   "
            write_json(run / "plan.json", plan)
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["coverage_review"]["plan_sha256"] = file_sha256(run / "plan.json")
            audit["coverage_review"]["section_results"][0]["status"] = "excluded"
            audit["coverage_review"]["section_results"][0]["note"] = "Исключено явно."
            write_json(run / "audit.json", audit)

            result = validate_bundle(run, stage="final")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("excluded section requires coverage_note", result.stdout)

        with self.subTest(field="result_note"), tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            plan = json.loads((run / "plan.json").read_text(encoding="utf-8"))
            section = plan["deliverable_outline"][0]
            section["status"] = "excluded"
            section["coverage_note"] = "Исключено явно."
            write_json(run / "plan.json", plan)
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["coverage_review"]["plan_sha256"] = file_sha256(run / "plan.json")
            audit["coverage_review"]["section_results"][0]["status"] = "excluded"
            audit["coverage_review"]["section_results"][0]["note"] = "   "
            write_json(run / "audit.json", audit)

            result = validate_bundle(run, stage="final")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("excluded section requires note", result.stdout)

    def test_quick_editor_ready_present_bank_is_hash_reviewed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(
                Path(temp), output_profile="editor-ready", depth="quick"
            )
            prepare_editor_ready_final(run)
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["coverage_review"]["useful_data_sha256"] = None
            write_json(run / "audit.json", audit)

            missing_hash = validate_bundle(run, stage="final")

            self.assertNotEqual(missing_hash.returncode, 0)
            self.assertIn("coverage_review.useful_data_sha256", missing_hash.stdout)
            self.assertIn("must be SHA-256", missing_hash.stdout)

            audit["coverage_review"]["useful_data_sha256"] = file_sha256(
                run / "useful-data.md"
            )
            write_json(run / "audit.json", audit)
            valid = validate_bundle(run, stage="final")
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)

            with (run / "useful-data.md").open("a", encoding="utf-8") as bank:
                bank.write("\nИзменено после проверки.\n")
            changed = validate_bundle(run, stage="final")
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn("coverage_review.useful_data_sha256", changed.stdout)
            self.assertIn("does not match", changed.stdout)

    def test_shipped_routed_artifact_templates_are_not_substantive_content(self) -> None:
        cases = (
            (
                "useful_data",
                "useful-data.md",
                "useful-data.md",
                "useful_data_sha256",
                "useful-data.md: final content is missing",
            ),
            (
                "appendix",
                "evidence-appendix.md",
                "evidence-appendix.md",
                "appendix_sha256",
                "evidence-appendix.md: final content is missing",
            ),
        )
        for disposition, artifact_name, template_name, hash_field, expected in cases:
            with (
                self.subTest(disposition=disposition),
                tempfile.TemporaryDirectory() as temp,
            ):
                run = self.initialize(Path(temp), output_profile="editor-ready")
                prepare_editor_ready_final(run)
                evidence = json.loads(
                    (run / "evidence.jsonl").read_text(encoding="utf-8")
                )
                evidence["output_disposition"] = disposition
                if disposition == "useful_data":
                    evidence["useful_data_types"] = ["number"]
                write_jsonl(run / "evidence.jsonl", [evidence])
                template_text = (
                    ROOT / "references" / "templates" / template_name
                ).read_text(encoding="utf-8")
                artifact_path = run / artifact_name
                artifact_path.write_text(template_text, encoding="utf-8")
                audit = json.loads(
                    (run / "audit.json").read_text(encoding="utf-8")
                )
                audit["coverage_review"]["evidence_sha256"] = file_sha256(
                    run / "evidence.jsonl"
                )
                audit["coverage_review"][hash_field] = file_sha256(artifact_path)
                write_json(run / "audit.json", audit)

                result = validate_bundle(run, stage="final")

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stdout)
                self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_long_source_link_label_is_not_substantive_record_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            evidence = json.loads((run / "evidence.jsonl").read_text(encoding="utf-8"))
            evidence["output_disposition"] = "useful_data"
            evidence["useful_data_types"] = ["number"]
            write_jsonl(run / "evidence.jsonl", [evidence])
            (run / "useful-data.md").write_text(
                "# Банк полезных данных\n\n"
                "## EVD-0001 · Проверенное наблюдение\n\n"
                "[Очень длинное описание правильного проверенного источника, "
                "которое само по себе не сообщает читателю ни факта, ни совета, "
                "ни ограничения исследуемого вывода]"
                "(https://example.com/source#fixture)\n",
                encoding="utf-8",
            )
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["coverage_review"]["evidence_sha256"] = file_sha256(
                run / "evidence.jsonl"
            )
            audit["coverage_review"]["useful_data_sha256"] = file_sha256(
                run / "useful-data.md"
            )
            write_json(run / "audit.json", audit)

            result = validate_bundle(run, stage="final")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "useful_data record EVD-0001 has no substantive material",
                result.stdout,
            )

    def test_inline_code_is_not_substantive_record_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            evidence = json.loads((run / "evidence.jsonl").read_text(encoding="utf-8"))
            evidence["output_disposition"] = "useful_data"
            evidence["useful_data_types"] = ["number"]
            write_jsonl(run / "evidence.jsonl", [evidence])
            (run / "useful-data.md").write_text(
                "# Банк полезных данных\n\n"
                "## EVD-0001 · Проверенное наблюдение\n\n"
                "`Этот текст намеренно длиннее шестидесяти знаков, но целиком "
                "помещён в строчный код и не является обычным редакторским абзацем.`\n\n"
                "[Источник](https://example.com/source#fixture)\n",
                encoding="utf-8",
            )
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["coverage_review"]["evidence_sha256"] = file_sha256(
                run / "evidence.jsonl"
            )
            audit["coverage_review"]["useful_data_sha256"] = file_sha256(
                run / "useful-data.md"
            )
            write_json(run / "audit.json", audit)

            result = validate_bundle(run, stage="final")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "useful_data record EVD-0001 has no substantive material",
                result.stdout,
            )

    def test_punctuation_is_not_substantive_record_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            evidence = json.loads((run / "evidence.jsonl").read_text(encoding="utf-8"))
            evidence["output_disposition"] = "useful_data"
            evidence["useful_data_types"] = ["number"]
            write_jsonl(run / "evidence.jsonl", [evidence])
            (run / "useful-data.md").write_text(
                "# Банк полезных данных\n\n"
                "## EVD-0001 · Проверенное наблюдение\n\n"
                + "." * 80
                + "\n\n[Источник](https://example.com/source#fixture)\n",
                encoding="utf-8",
            )
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["coverage_review"]["evidence_sha256"] = file_sha256(
                run / "evidence.jsonl"
            )
            audit["coverage_review"]["useful_data_sha256"] = file_sha256(
                run / "useful-data.md"
            )
            write_json(run / "audit.json", audit)

            result = validate_bundle(run, stage="final")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "useful_data record EVD-0001 has no substantive material",
                result.stdout,
            )

    def test_record_id_inside_code_is_not_visible_artifact_content(self) -> None:
        id_cases = (
            ("fenced", "```text\nEVD-0001\n```"),
            ("indented", "    EVD-0001"),
        )
        for case, hidden_id in id_cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                run = self.initialize(Path(temp), output_profile="editor-ready")
                prepare_editor_ready_final(run)
                evidence = json.loads(
                    (run / "evidence.jsonl").read_text(encoding="utf-8")
                )
                evidence["output_disposition"] = "useful_data"
                evidence["useful_data_types"] = ["number"]
                write_jsonl(run / "evidence.jsonl", [evidence])
                (run / "useful-data.md").write_text(
                    "# Банк полезных данных\n\n"
                    "## Проверенное наблюдение\n\n"
                    f"{hidden_id}\n\n"
                    "Этот обычный абзац содержит достаточно содержательного текста, "
                    "но идентификатор записи скрыт внутри кода и потому не считается "
                    "видимым. [Источник](https://example.com/source#fixture)\n",
                    encoding="utf-8",
                )
                audit = json.loads(
                    (run / "audit.json").read_text(encoding="utf-8")
                )
                audit["coverage_review"]["evidence_sha256"] = file_sha256(
                    run / "evidence.jsonl"
                )
                audit["coverage_review"]["useful_data_sha256"] = file_sha256(
                    run / "useful-data.md"
                )
                write_json(run / "audit.json", audit)

                result = validate_bundle(run, stage="final")

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("missing useful_data record EVD-0001", result.stdout)

    def test_record_id_inside_blockquote_fence_is_not_visible(self) -> None:
        self.assert_hidden_record_id_rejected(
            "> ```text\n> EVD-0001\n> ```"
        )

    def test_record_id_inside_list_container_fence_is_not_visible(self) -> None:
        self.assert_hidden_record_id_rejected(
            "- ```text\n  EVD-0001\n  ```"
        )

    def test_record_id_inside_hidden_html_is_not_visible(self) -> None:
        for case, hidden_id in (
            ("raw-block", "<div hidden>\nEVD-0001\n</div>"),
            ("attribute", '<span data-record="EVD-0001"></span>'),
            ("hidden", "<span hidden>EVD-0001</span>"),
            ("aria-hidden", '<span aria-hidden="true">EVD-0001</span>'),
            ("display-none", '<span style="display:none">EVD-0001</span>'),
        ):
            with self.subTest(case=case):
                self.assert_hidden_record_id_rejected(hidden_id)

    def test_record_id_inside_link_destination_is_not_visible(self) -> None:
        self.assert_hidden_record_id_rejected(
            "[Источник](https://example.com/source#EVD-0001)"
        )

    def test_hidden_html_source_link_does_not_satisfy_routed_record(self) -> None:
        for case, hidden_link in (
            (
                "hidden",
                "<span hidden>[Источник]"
                "(https://example.com/source#fixture)</span>",
            ),
            (
                "aria-hidden",
                '<span aria-hidden="true">[Источник]'
                "(https://example.com/source#fixture)</span>",
            ),
            (
                "display-none",
                '<span style="display:none">[Источник]'
                "(https://example.com/source#fixture)</span>",
            ),
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                run = self.initialize(Path(temp), output_profile="editor-ready")
                prepare_editor_ready_final(run)
                evidence = json.loads(
                    (run / "evidence.jsonl").read_text(encoding="utf-8")
                )
                evidence["output_disposition"] = "useful_data"
                evidence["useful_data_types"] = ["number"]
                write_jsonl(run / "evidence.jsonl", [evidence])
                (run / "useful-data.md").write_text(
                    "# Банк полезных данных\n\n"
                    "## EVD-0001 · Проверенное наблюдение\n\n"
                    "Этот обычный абзац содержит больше шестидесяти знаков полезного "
                    "материала, но ссылка на доказательство скрыта от читателя. "
                    f"{hidden_link}\n",
                    encoding="utf-8",
                )
                audit = json.loads(
                    (run / "audit.json").read_text(encoding="utf-8")
                )
                audit["coverage_review"]["evidence_sha256"] = file_sha256(
                    run / "evidence.jsonl"
                )
                audit["coverage_review"]["useful_data_sha256"] = file_sha256(
                    run / "useful-data.md"
                )
                write_json(run / "audit.json", audit)

                result = validate_bundle(run, stage="final")

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "requires a visible inspected source link matching its evidence",
                    result.stdout,
                )

    def test_review_hashes_freeze_contradictions_and_semantic_audit(self) -> None:
        with self.subTest(ledger="contradictions"), tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            write_jsonl(
                run / "contradictions.jsonl",
                [
                    {
                        "contradiction_id": "CTR-0001",
                        "claim_id": "CLM-0001",
                        "outcome": "resolved",
                        "counter_evidence_ids": [],
                    }
                ],
            )

            result = validate_bundle(run, stage="final")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("coverage_review.contradictions_sha256", result.stdout)
            self.assertIn("does not match", result.stdout)

        with self.subTest(ledger="semantic-audit"), tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            semantic = json.loads(
                (run / "semantic-audit.jsonl").read_text(encoding="utf-8")
            )
            semantic["reviewer_basis"] = "Changed after coverage review."
            write_jsonl(run / "semantic-audit.jsonl", [semantic])

            result = validate_bundle(run, stage="final")

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("coverage_review.semantic_audit_sha256", result.stdout)
            self.assertIn("does not match", result.stdout)

    def test_ordinary_source_link_label_is_not_treated_as_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp), output_profile="editor-ready")
            prepare_editor_ready_final(run)
            evidence = json.loads((run / "evidence.jsonl").read_text(encoding="utf-8"))
            evidence["output_disposition"] = "useful_data"
            evidence["useful_data_types"] = ["comparison"]
            write_jsonl(run / "evidence.jsonl", [evidence])
            (run / "useful-data.md").write_text(
                "# Банк полезных данных\n\n"
                "## EVD-0001 · Проверенное изменение\n\n"
                "Запись объясняет конкретное изменение, сравнивает состояние до и "
                "после него и сохраняет ограничение области вывода. "
                "[Что изменилось](https://example.com/source#fixture)\n",
                encoding="utf-8",
            )
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["coverage_review"]["evidence_sha256"] = file_sha256(
                run / "evidence.jsonl"
            )
            audit["coverage_review"]["useful_data_sha256"] = file_sha256(
                run / "useful-data.md"
            )
            write_json(run / "audit.json", audit)

            result = validate_bundle(run, stage="final")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_complete_linked_run_passes_final_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp))
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            manifest["status"] = "complete"
            write_json(run / "manifest.json", manifest)
            write_jsonl(
                run / "queries.jsonl",
                [
                    {
                        "query_id": "QRY-0001",
                        "pass": "discovery",
                        "family": "primary",
                        "query": "fixture query",
                        "executed_at": "2026-08-28T08:00:00Z",
                        "status": "executed",
                    }
                ],
            )
            write_jsonl(
                run / "sources.jsonl",
                [
                    {
                        "source_id": "SRC-0001",
                        "title": "Inspected primary source",
                        "requested_url": "https://example.com/original",
                        "final_url": "https://example.com/original",
                        "accessed_at": "2026-08-28T08:00:00Z",
                        "access_integrity": "full",
                        "source_type": "official",
                        "lineage_id": "LIN-0001",
                        "mutable": True,
                        "fingerprint_status": "unavailable",
                        "fingerprint_reason": "Fixture has no preserved source content.",
                    }
                ],
            )
            write_jsonl(
                run / "evidence.jsonl",
                [
                    {
                        "evidence_id": "EVD-0001",
                        "source_id": "SRC-0001",
                        "claim_ids": ["CLM-0001"],
                        "relationship": "supports",
                        "locator": {"section": "Rules"},
                        "evidence_type": "fact",
                        "faithful_paraphrase": "Fixture evidence for integrity testing only.",
                    }
                ],
            )
            write_jsonl(
                run / "claims.jsonl",
                [
                    {
                        "claim_id": "CLM-0001",
                        "claim": "Fixture claim for integrity testing only.",
                        "importance": "critical",
                        "status": "supported",
                        "confidence": "HIGH",
                        "supporting_evidence_ids": ["EVD-0001"],
                        "challenging_evidence_ids": [],
                        "challenge_search": {"query_ids": ["QRY-0001"], "result": "none_found"},
                    }
                ],
            )
            write_jsonl(
                run / "semantic-audit.jsonl",
                [
                    {
                        "semantic_audit_id": "SEM-0001",
                        "claim_id": "CLM-0001",
                        "evidence_id": "EVD-0001",
                        "source_id": "SRC-0001",
                        "semantic_support": "exact",
                        "scope_match": True,
                        "authority_match": True,
                        "freshness_match": True,
                        "evidence_type_match": True,
                        "reviewer_status": "pass",
                        "reviewer_basis": "Fixture evidence exactly supports the fixture claim.",
                        "audited_at": "2026-08-28T08:05:00Z",
                    }
                ],
            )
            write_json(
                run / "audit.json",
                {
                    "audit_status": "pass",
                    "critical_issues": [],
                    "warnings": [],
                    "claims_to_rewrite": [],
                    "claims_to_remove": [],
                    "additional_search_required": [],
                },
            )
            (run / "report.md").write_text(
                "# Research Report\n\nThis is a non-factual fixture report used only to verify "
                "that a completed bundle passes structural and referential-integrity checks.\n",
                encoding="utf-8",
            )
            (run / "handoff.md").write_text(
                "# Research Handoff\n\n"
                "delivery_status: ready\n"
                "output_profile: research-report\n"
                "audit_status: pass\n"
                "clarity_preservation: not_applicable\n"
                "bundle_validation: pass\n\n"
                "Fixture handoff for structural validation only.\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "final"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_broken_evidence_reference_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp))
            write_jsonl(
                run / "claims.jsonl",
                [
                    {
                        "claim_id": "CLM-0001",
                        "claim": "Broken fixture claim.",
                        "importance": "material",
                        "status": "supported",
                        "confidence": "HIGH",
                        "supporting_evidence_ids": ["EVD-9999"],
                        "challenging_evidence_ids": [],
                    }
                ],
            )
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "working"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unknown evidence EVD-9999", result.stdout)

    def test_initializer_refuses_to_overwrite_non_empty_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp) / "run"
            run.mkdir()
            (run / "keep.txt").write_text("user data", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(INIT),
                    str(run),
                    "--question",
                    "Should not overwrite this directory",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((run / "keep.txt").read_text(encoding="utf-8"), "user data")

    def test_query_without_execution_timestamp_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp))
            write_jsonl(
                run / "queries.jsonl",
                [
                    {
                        "query_id": "QRY-0001",
                        "pass": "discovery",
                        "family": "primary",
                        "query": "fixture query without timestamp",
                        "status": "executed",
                    }
                ],
            )
            result = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "working"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing executed_at", result.stdout)

    def test_schema_1_0_migration_can_be_rolled_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp))
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            manifest["schema_version"] = "1.0"
            manifest.pop("provenance", None)
            manifest.pop("output_profile", None)
            manifest["modifiers"] = ["raw-research", "current-patch-only"]
            write_json(run / "manifest.json", manifest)
            (run / "handoff.md").write_text(
                re.sub(
                    r"(?im)^Output profile:.*\n+",
                    "",
                    (run / "handoff.md").read_text(encoding="utf-8"),
                ),
                encoding="utf-8",
            )
            (run / "semantic-audit.jsonl").unlink()
            write_jsonl(
                run / "sources.jsonl",
                [
                    {
                        "source_id": "SRC-0001",
                        "title": "Legacy source",
                        "url": "https://example.com/legacy",
                        "accessed_at": "2026-08-28T08:00:00Z",
                        "access_integrity": "full",
                        "source_type": "official",
                        "lineage_id": "LIN-0001",
                    }
                ],
            )
            apply_result = subprocess.run(
                [sys.executable, str(MIGRATE), str(run), "--apply"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(apply_result.returncode, 0, apply_result.stdout + apply_result.stderr)
            migrated = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(migrated["schema_version"], "1.1")
            self.assertEqual(migrated["output_profile"], "raw-research")
            self.assertEqual(migrated["modifiers"], ["current-patch-only"])
            validate_result = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "working"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                validate_result.returncode,
                0,
                validate_result.stdout + validate_result.stderr,
            )
            backup_line = next(
                line for line in apply_result.stdout.splitlines() if line.startswith("Rollback backup:")
            )
            backup = backup_line.split(":", 1)[1].strip()
            rollback_result = subprocess.run(
                [sys.executable, str(MIGRATE), str(run), "--rollback", backup],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                rollback_result.returncode, 0, rollback_result.stdout + rollback_result.stderr
            )
            restored = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(restored["schema_version"], "1.0")
            self.assertNotIn("output_profile", restored)
            self.assertIn("raw-research", restored["modifiers"])
            self.assertFalse((run / "semantic-audit.jsonl").exists())

    def test_legacy_schema_1_1_output_profile_can_be_backfilled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp))
            manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            manifest.pop("output_profile")
            manifest["schema_version"] = "1.1"
            manifest["modifiers"] = ["raw-research", "current-patch-only"]
            manifest["status"] = "complete"
            write_json(run / "manifest.json", manifest)
            write_minimal_linked_fixture(run)
            audit = json.loads((run / "audit.json").read_text(encoding="utf-8"))
            audit["audit_status"] = "pass"
            write_json(run / "audit.json", audit)
            (run / "report.md").write_text(
                "# Research report\n\n"
                "This structural fixture contains enough final content to prove that "
                "the migrated profile and handoff agree at the final validation gate.\n",
                encoding="utf-8",
            )
            legacy_handoff = (
                "# Research Handoff\n\n"
                "delivery_status: ready\n"
                "audit_status: pass\n"
                "clarity_preservation: not_applicable\n"
                "bundle_validation: pass\n\n"
                "This legacy fixture intentionally omits only the output profile field.\n"
            )
            (run / "handoff.md").write_text(legacy_handoff, encoding="utf-8")

            apply_result = subprocess.run(
                [sys.executable, str(MIGRATE), str(run), "--apply"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                apply_result.returncode,
                0,
                apply_result.stdout + apply_result.stderr,
            )
            migrated = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(migrated["schema_version"], "1.1")
            self.assertEqual(migrated["output_profile"], "raw-research")
            self.assertEqual(migrated["modifiers"], ["current-patch-only"])
            self.assertIn("output_profile backfill", apply_result.stdout)
            migrated_handoff = (run / "handoff.md").read_text(encoding="utf-8")
            self.assertIn("Output profile: `raw-research`", migrated_handoff)

            validate_result = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "final"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                validate_result.returncode,
                0,
                validate_result.stdout + validate_result.stderr,
            )

            backup_line = next(
                line
                for line in apply_result.stdout.splitlines()
                if line.startswith("Rollback backup:")
            )
            backup = backup_line.split(":", 1)[1].strip()
            rollback_result = subprocess.run(
                [sys.executable, str(MIGRATE), str(run), "--rollback", backup],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                rollback_result.returncode,
                0,
                rollback_result.stdout + rollback_result.stderr,
            )
            restored = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn("output_profile", restored)
            self.assertIn("raw-research", restored["modifiers"])
            self.assertEqual(
                (run / "handoff.md").read_text(encoding="utf-8"),
                legacy_handoff,
            )

    def test_schema_1_0_migration_rejects_invalid_or_conflicting_profiles(self) -> None:
        cases = (
            ("invented", ["current-patch-only"], "invalid existing output_profile"),
            ([], ["current-patch-only"], "invalid existing output_profile"),
            ({}, ["current-patch-only"], "invalid existing output_profile"),
            (
                "editor-ready",
                ["raw-research", "current-patch-only"],
                "conflicts with legacy raw-research modifier",
            ),
        )
        for output_profile, modifiers, expected_error in cases:
            with self.subTest(output_profile=output_profile), tempfile.TemporaryDirectory() as temp:
                run = self.initialize(Path(temp))
                manifest = json.loads(
                    (run / "manifest.json").read_text(encoding="utf-8")
                )
                manifest["schema_version"] = "1.0"
                manifest["output_profile"] = output_profile
                manifest["modifiers"] = modifiers
                write_json(run / "manifest.json", manifest)
                before = (run / "manifest.json").read_text(encoding="utf-8")

                result = subprocess.run(
                    [sys.executable, str(MIGRATE), str(run), "--apply"],
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)
                self.assertEqual(
                    (run / "manifest.json").read_text(encoding="utf-8"), before
                )
                self.assertFalse((run / "migration-backups").exists())

    def test_snapshot_fingerprint_is_recorded_and_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run = self.initialize(Path(temp))
            snapshots = run / "snapshots"
            snapshots.mkdir()
            (snapshots / "SRC-0001.txt").write_text(
                "Preserved inspected source content.\n", encoding="utf-8"
            )
            write_jsonl(
                run / "sources.jsonl",
                [
                    {
                        "source_id": "SRC-0001",
                        "title": "Snapshot source",
                        "requested_url": "https://example.com/requested",
                        "final_url": "https://example.com/final",
                        "accessed_at": "2026-08-28T08:00:00Z",
                        "access_integrity": "full",
                        "source_type": "official",
                        "lineage_id": "LIN-0001",
                        "mutable": True,
                        "fingerprint_status": "unavailable",
                        "fingerprint_reason": "Awaiting local fingerprint pass.",
                        "snapshot_path": "snapshots/SRC-0001.txt",
                    }
                ],
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(FINGERPRINT),
                    str(run),
                    "--apply",
                    "--require-all",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            source = json.loads((run / "sources.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(source["fingerprint_status"], "verified")
            self.assertEqual(len(source["content_sha256"]), 64)
            validation = subprocess.run(
                [sys.executable, str(VALIDATE), str(run), "--stage", "working"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)


if __name__ == "__main__":
    unittest.main()
