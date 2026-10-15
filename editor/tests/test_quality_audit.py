import hashlib
import json
import subprocess
import sys

import pytest

from editorteam.publication_benchmark import prepare
from editorteam.quality_audit import audit_summary, load_cases, prepare_reviews


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def corpus(tmp_path):
    text = "Совет может помочь при наличии ресурса. Не гарантирует победу."
    rows = [
        {
            "id": name,
            "url": f"https://article.example/{name}",
            "text": text + name,
            "title": name,
            "access": "full",
            "sha256": sha(text + name),
        }
        for name in ("one", "two")
    ]
    directory = tmp_path / "corpus"
    manifest = prepare(rows, directory)
    return directory, manifest, tmp_path / "evidence"


def review(case, text):
    return {
        "case_id": case["case_id"],
        "source_sha256": case["source_sha256"],
        "reviewer_kind": "model",
        "reviewer": "Independent synthetic reviewer",
        "reviewed_at": "2026-10-15T12:00:00Z",
        "temporal_scope": "historical",
        "target_period": "synthetic patch",
        "claim_scope": "sampled",
        "literary": {
            "dimensions": {
                key: "pass"
                for key in ("usefulness", "coherence", "natural_russian", "author_voice")
            },
            "strengths": [{"quote": "Совет может помочь", "reason": "Оговорка сохранена"}],
            "findings": [],
        },
        "source_facts": {
            "claims": [
                {
                    "claim_id": "C1",
                    "quote": "Совет может помочь при наличии ресурса.",
                    "kind": "recommendation",
                    "status": "unverified",
                    "reason": "Нет внешней опоры",
                    "search_queries": ["synthetic source"],
                    "evidence": [],
                }
            ]
        },
        "limitations": ["Проверена выборка утверждений, не все факты"],
    }


def supported(row, evidence_root, url="https://official.example/rules"):
    evidence_root.mkdir(exist_ok=True)
    snapshot = "A resource may help."
    (evidence_root / "evidence.txt").write_bytes(snapshot.encode())
    capture = {
        "source_url": url,
        "retrieved_at": "2026-10-15T11:00:00Z",
        "snapshot_sha256": sha(snapshot),
        "method": "web.open",
        "tool_reference": "synthetic-test-reference",
        "content_scope": "excerpt",
    }
    (evidence_root / "capture.json").write_text(json.dumps(capture), encoding="utf-8")
    claim = row["source_facts"]["claims"][0]
    claim.update(
        status="supported",
        evidence=[
            {
                "url": url,
                "quote": snapshot,
                "snapshot_path": "evidence.txt",
                "sha256": sha(snapshot),
                "authority": "official",
                "scope_matches": True,
                "time_matches": True,
                "retrieved_at": "2026-10-15T11:00:00Z",
                "capture_path": "capture.json",
            }
        ],
    )


def test_model_complete_current_claims_are_not_verified_facts(corpus):
    directory, _, evidence, row = first_review(corpus)
    supported(row, evidence)
    row.update(claim_scope="complete", temporal_scope="current")
    result = audit_summary(directory, [row], evidence)["results"][0]
    assert result["current_facts_verified"] is False
    assert result["model_current_support"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_url", "https://other.example/rules"),
        ("retrieved_at", "2026-10-14T11:00:00Z"),
        ("snapshot_sha256", "wrong"),
    ],
)
def test_snapshot_capture_must_match_cited_url_time_and_bytes(corpus, field, value):
    directory, _, evidence, row = first_review(corpus)
    supported(row, evidence)
    path = evidence / "capture.json"
    capture = json.loads(path.read_text(encoding="utf-8"))
    capture[field] = value
    path.write_text(json.dumps(capture), encoding="utf-8")
    with pytest.raises(ValueError, match="capture"):
        audit_summary(directory, [row], evidence)


def first_review(corpus):
    directory, manifest, evidence = corpus
    case = manifest["cases"][0]
    text = (directory / case["source_path"]).read_text(encoding="utf-8")
    return directory, case, evidence, review(case, text)


def test_pending_cases_stay_in_denominator_without_invented_quality(corpus):
    directory, _, evidence = corpus
    report = audit_summary(directory, [], evidence)
    assert report["cases"] == 2
    assert report["reviewed"] == 0
    assert report["pending"] == 2
    assert report["human_approved"] is False
    assert report["quality_improvement_percent"] is None
    assert all(row["edit_preservation"] == "not_run" for row in report["results"])


def test_sampled_historical_support_does_not_verify_current_article(corpus):
    directory, _, evidence, row = first_review(corpus)
    supported(row, evidence)
    report = audit_summary(directory, [row], evidence)
    result = report["results"][0]
    assert result["source_accuracy"] == "sampled_support"
    assert result["current_facts_verified"] is False
    assert report["claim_counts"] == {
        "supported": 1,
        "contradicted": 0,
        "unverified": 0,
        "outdated": 0,
    }
    assert report["pending"] == 1


def test_preserved_edit_does_not_confirm_unverified_source(corpus):
    directory, case, evidence, row = first_review(corpus)
    text = (directory / case["source_path"]).read_text(encoding="utf-8") + " Уточнение формы."
    row["edit_review"] = {
        "candidate": text,
        "candidate_sha256": sha(text),
        "all_changes_checked": True,
        "unsupported_additions": [],
        "claims": [
            {
                "claim_id": "C1",
                "status": "preserved",
                "quote": "Совет может помочь при наличии ресурса.",
            }
        ],
    }
    report = audit_summary(directory, [row], evidence)
    assert report["results"][0]["edit_preservation"] == "passed_model_review"
    assert report["results"][0]["source_accuracy"] == "needs_research"
    assert report["results"][0]["current_facts_verified"] is False
    assert len(report["search_queue"]) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_sha256", "wrong"),
        ("reviewer_kind", "human"),
        ("reviewed_at", "2026-10-15"),
        ("claim_scope", "everything"),
        ("target_period", ""),
    ],
)
def test_review_requires_identity_model_provenance_and_explicit_scope(corpus, field, value):
    directory, _, evidence, row = first_review(corpus)
    row[field] = value
    with pytest.raises(ValueError):
        audit_summary(directory, [row], evidence)


@pytest.mark.parametrize("mutation", ["invented_quote", "missing_dimension", "unknown_severity"])
def test_literary_review_requires_quoted_concrete_findings(corpus, mutation):
    directory, _, evidence, row = first_review(corpus)
    finding = {
        "category": "clarity",
        "severity": "warning",
        "quote": "Совет может помочь",
        "reason": "Нужно уточнение",
        "suggestion": "Уточнить условие",
    }
    row["literary"]["findings"] = [finding]
    row["literary"]["dimensions"]["usefulness"] = "needs_work"
    if mutation == "invented_quote":
        finding["quote"] = "Такого нет в исходнике"
    elif mutation == "missing_dimension":
        del row["literary"]["dimensions"]["author_voice"]
    else:
        finding["severity"] = "critical"
    with pytest.raises(ValueError):
        audit_summary(directory, [row], evidence)


@pytest.mark.parametrize("mutation", ["hash", "quote", "path", "scope", "time", "self_source"])
def test_supported_fact_requires_intact_independent_matching_evidence(corpus, mutation):
    directory, case, evidence, row = first_review(corpus)
    supported(row, evidence)
    item = row["source_facts"]["claims"][0]["evidence"][0]
    if mutation == "hash":
        item["sha256"] = "wrong"
    elif mutation == "quote":
        item["quote"] = "Absent quote"
    elif mutation == "path":
        item["snapshot_path"] = "../outside.txt"
    elif mutation in {"scope", "time"}:
        item[f"{mutation}_matches"] = False
    else:
        item["url"] = case["url"] + "#self"
    with pytest.raises(ValueError):
        audit_summary(directory, [row], evidence)


def test_duplicate_unknown_reports_and_tampered_corpus_are_rejected(corpus):
    directory, _, evidence, row = first_review(corpus)
    with pytest.raises(ValueError, match="duplicate"):
        audit_summary(directory, [row, row], evidence)
    bad = {**row, "case_id": "unknown"}
    with pytest.raises(ValueError):
        audit_summary(directory, [bad], evidence)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["cases"][0]["source_path"] = "../outside.md"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        load_cases(directory)


def test_frozen_split_and_source_bytes_are_retained_in_packet(corpus, tmp_path):
    directory, manifest, _ = corpus
    original = {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    packet = prepare_reviews(directory, tmp_path / "packet")
    assert [(r["case_id"], r["split"]) for r in packet["cases"]] == [
        (r["case_id"], r["split"]) for r in manifest["cases"]
    ]
    assert all(p.read_bytes() == value for p, value in original.items())
    with pytest.raises(FileExistsError):
        prepare_reviews(directory, tmp_path / "packet")


def test_cli_writes_pending_report_and_refuses_overwrite(corpus, tmp_path):
    directory, _, evidence = corpus
    evidence.mkdir()
    reviews = tmp_path / "reviews.json"
    reviews.write_text("[]")
    output = tmp_path / "Отчёт.json"
    markdown = tmp_path / "Отчёт.md"
    command = [
        sys.executable,
        "-m",
        "editorteam.quality_audit",
        "summarize",
        str(directory),
        "--reviews",
        str(reviews),
        "--evidence-root",
        str(evidence),
        "--output",
        str(output),
        "--markdown",
        str(markdown),
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["pending"] == 2
    assert "ожидают: 2" in markdown.read_text(encoding="utf-8")
    first = output.read_bytes()
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert output.read_bytes() == first
