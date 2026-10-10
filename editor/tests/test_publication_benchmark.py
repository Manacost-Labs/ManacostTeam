import copy
import hashlib
import json

import pytest

from editorteam.publication_benchmark import export_approved, paired_summary, prepare


def candidate(identity, url=None, text=None):
    text = text or f"Synthetic advice for {identity}. Keep it conditional."
    return {
        "id": identity,
        "url": url or f"https://example.org/{identity}",
        "title": f"Case {identity}",
        "text": text,
        "access": "full",
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def test_prepare_freezes_order_independent_split_and_duplicate_groups(tmp_path):
    rows = [candidate(str(i)) for i in range(15)]
    rows.extend(
        [candidate("alias", rows[0]["url"] + "/#heading"), candidate("copy", text=rows[1]["text"])]
    )
    first = prepare(rows, tmp_path / "first", seed=17)
    second = prepare(list(reversed(rows)), tmp_path / "second", seed=17)
    assert first == second
    splits = {row["source_id"]: row["split"] for row in first["cases"]}
    assert splits["0"] == splits["alias"]
    assert splits["1"] == splits["copy"]
    assert set(splits.values()) == {"train", "holdout"}
    assert all(row["review_status"] == "pending" for row in first["cases"])
    assert (tmp_path / "first" / "index.md").exists()
    with pytest.raises(FileExistsError):
        prepare(rows, tmp_path / "first")


def test_candidates_and_missing_human_provenance_never_export_gold(tmp_path):
    directory = tmp_path / "bundle"
    manifest = prepare(
        [candidate("one", text="Synthetic advice.\r\nKeep it conditional.\r\n")], directory
    )
    with pytest.raises(ValueError, match="approved"):
        export_approved(directory)
    annotation = directory / manifest["cases"][0]["annotation_path"]
    row = json.loads(annotation.read_text())
    row.update(
        {
            "review_status": "approved",
            "patch": "synthetic",
            "reference": "Edited synthetic reference.",
            "reference_edit_confirmed": True,
            "required_claims": [
                {
                    "claim_id": "c1",
                    "meaning": "Keep advice conditional",
                    "action": "Keep",
                    "condition": "conditional",
                    "exception": "",
                    "evidence_quote": "Keep it conditional.",
                }
            ],
            "conditions": ["conditional"],
            "errors": [],
            "approval": {
                "human_confirmed": True,
                "reviewer": "Test reviewer",
                "reviewed_at": "2026-10-10T12:00:00Z",
            },
        }
    )
    annotation.write_text(json.dumps(row))
    approved = export_approved(directory)
    assert approved[0]["human_approved"] is True
    assert approved[0]["approval"]["reviewer"] == "Test reviewer"
    for field, value in (
        ("human_confirmed", False),
        ("reviewer", ""),
        ("reviewed_at", "yesterday"),
    ):
        invalid = copy.deepcopy(row)
        invalid["approval"][field] = value
        annotation.write_text(json.dumps(invalid))
        with pytest.raises(ValueError):
            export_approved(directory)
    annotation.write_text(json.dumps(row))
    source = directory / manifest["cases"][0]["source_path"]
    source.write_text("Tampered source")
    with pytest.raises(ValueError, match="hash"):
        export_approved(directory)


def reviewed(case_id, variant, minutes, errors=0, patch="synthetic"):
    return {
        "case_id": case_id,
        "variant": variant,
        "patch": patch,
        "review_status": "reviewed",
        "editor_minutes": minutes,
        "critical_errors": errors,
        "reviewer": "Test reviewer",
        "reviewed_at": "2026-10-10T12:00:00Z",
    }


def test_summary_uses_only_matching_reviewed_pairs():
    rows = [
        reviewed("one", "baseline", 10, 2),
        reviewed("one", "candidate", 6, 1),
        reviewed("incomplete", "baseline", 1000, 50),
        {
            "case_id": "incomplete",
            "variant": "candidate",
            "patch": "synthetic",
            "review_status": "pending",
        },
    ]
    report = paired_summary(rows)
    assert report["complete_pairs"] == 1
    assert report["variants"]["baseline"]["editor_minutes"] == 10
    assert report["variants"]["candidate"]["editor_minutes"] == 6
    assert report["editor_minutes_reduction_percent"] == 40
    assert report["critical_errors_reduction_percent"] == 50
    pending = paired_summary(rows[2:])
    assert pending["editor_minutes_reduction_percent"] is None
    assert pending["variants"]["baseline"]["editor_minutes"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"editor_minutes": -1},
        {"editor_minutes": float("nan")},
        {"editor_minutes": True},
        {"critical_errors": 1.5},
        {"reviewer": ""},
        {"reviewed_at": "yesterday"},
        {"patch": "different"},
        {"variant": "other"},
    ],
)
def test_summary_rejects_malformed_ratings(change):
    rows = [reviewed("one", "baseline", 10), reviewed("one", "candidate", 5)]
    rows[1].update(change)
    with pytest.raises(ValueError):
        paired_summary(rows)


def test_summary_rejects_duplicate_and_resolves_blind_key():
    rows = [reviewed("one", "baseline", 10), reviewed("one", "candidate", 5)]
    with pytest.raises(ValueError):
        paired_summary(rows + rows[:1])
    for index, row in enumerate(rows):
        row.pop("variant")
        row["blind_id"] = f"one:{index}"
    key = [
        {"blind_id": "one:0", "case_id": "one", "variant": "baseline"},
        {"blind_id": "one:1", "case_id": "one", "variant": "candidate"},
    ]
    assert paired_summary(rows, key)["complete_pairs"] == 1
    with pytest.raises(ValueError):
        paired_summary(rows, key + key[:1])
