import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from editorteam.evaluation_status import execution_summary, skipped_report


def test_skipped_model_evaluation_has_no_quality_or_acceptance_claim():
    report = skipped_report("no_provider_key")
    assert report["run_status"] == "not_run"
    assert report["reason"] == "no_provider_key"
    assert report["model_evaluation_completed"] is False
    assert report["quality_validated"] is False
    assert report["share"] is None


def test_partial_evaluation_counts_missing_cases_in_denominator():
    rows = [
        {"id": "one", "candidate": {"accepted": True, "failed": []}, "gateway": {"accepted": True}},
        {"id": "two", "note": "gateway unavailable"},
    ]
    summary = execution_summary(rows, "gateway", "synthetic-model")
    assert summary["run_status"] == "partial"
    assert summary["requested"] == 2
    assert summary["cases"] == 1
    assert summary["share"] == 0.5
    assert summary["model_evaluation_completed"] is False


def test_rejected_gateway_original_does_not_count_as_successful_edit():
    rows = [
        {"id": "one", "candidate": {"accepted": True, "failed": []}, "gateway": {"accepted": False}}
    ]
    summary = execution_summary(rows, "gateway", "synthetic-model")
    assert summary["accepted"] == 0
    assert summary["share"] == 0
    assert summary["model_evaluation_completed"] is True
    assert summary["quality_validated"] is False


@pytest.mark.parametrize("source", ["inputs", "candidates"])
def test_offline_scoring_is_not_model_quality_evaluation(source):
    score = {"accepted": True, "failed": []}
    rows = [{"id": "one", "input": score, "candidate": score}]
    report = execution_summary(rows, source, "synthetic-model")
    assert report["model_evaluation_completed"] is False
    assert report["quality_validated"] is False


def test_empty_run_is_failed_instead_of_zero_percent_quality():
    report = execution_summary([], "gateway", None)
    assert report["run_status"] == "failed"
    assert report["share"] is None
    assert report["requested"] == 0


def test_complete_execution_records_model_without_claiming_human_quality():
    rows = [
        {"id": "one", "candidate": {"accepted": True, "failed": []}, "gateway": {"accepted": True}}
    ]
    report = execution_summary(rows, "gateway", "synthetic-model")
    assert report["run_status"] == "completed"
    assert report["model_evaluation_completed"] is True
    assert report["quality_validated"] is False


def test_runner_writes_failed_report_and_nonzero_exit_for_missing_candidates(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "quality_test_runner", root / "tools/run_evals.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    monkeypatch.setattr(runner.C, "ensure_venv", lambda *args: None)
    monkeypatch.setattr(runner.C, "corpus_manifest", lambda: {})
    case = {"id": "missing", "_input": "input"}
    scorer = SimpleNamespace(
        load_thresholds=lambda: {},
        load_case=lambda p: case,
        score=lambda *args, **kwargs: {
            "accepted": True,
            "failed": [],
            "metrics": {"markers_per_10k": {}},
        },
        EVALS_SCHEMA_VERSION=1,
    )
    monkeypatch.setattr(runner.C, "sibling", lambda name: scorer)
    monkeypatch.setattr(runner, "cases", lambda selected: [tmp_path])
    output = tmp_path / "output"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_evals",
            "--candidates",
            str(tmp_path / "empty"),
            "--out",
            str(output),
            "--format",
            "json",
        ],
    )
    assert runner.main() == 2
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["summary"]["requested"] == 1
    assert report["summary"]["run_status"] == "failed"
    assert report["summary"]["model_evaluation_completed"] is False
    markdown = (output / "report.md").read_text(encoding="utf-8")
    assert "NOT RUN" in markdown
    assert "кандидат отсутствует" in markdown


def test_missing_or_unregistered_case_directory_fails_inventory(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "inventory_test_runner", root / "tools/run_evals.py"
    )
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"schema_version": 1, "case_ids": ["one", "two"]}))
    monkeypatch.setattr(runner, "INVENTORY_PATH", inventory, raising=False)
    monkeypatch.setattr(runner, "CASES_DIR", tmp_path / "cases")
    case = runner.CASES_DIR / "one"
    case.mkdir(parents=True)
    (case / "case.yaml").write_text("fixture")
    with pytest.raises(ValueError, match="inventory"):
        runner.cases(None)
