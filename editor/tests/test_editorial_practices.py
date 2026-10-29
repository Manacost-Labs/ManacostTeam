"""Contract tests: findings need evidence; ordinary style is not a failure."""

import copy

import pytest

from editorteam.editorial_practices import (
    catalog,
    identifiers,
    prepare,
    validate,
)

TEXT = "Не только атака, но и защита важны — сохраните ресурс, если нет угрозы."


def assessment(owner="literary_review", text=TEXT):
    packet = prepare(text, owner=owner)
    return {
        "status": "pass",
        "article_sha256": packet["article_sha256"],
        "practice_checks": [
            {
                "id": p["id"],
                "status": "clear",
                "quote": text,
                "reason": "В этом примере добавление защиты уточняет условный совет.",
            }
            for p in packet["practices"]
        ],
        "logic_checks": [
            {
                "id": key,
                "status": "clear",
                "quote": text,
                "reason": "Условие явно ограничивает совет, противоположных советов нет.",
            }
            for key in packet["logic_dimensions"]
        ],
        "preservation_checks": [
            {
                "id": key,
                "status": "clear",
                "quote": text,
                "reason": "Сверено с исходником: совет, условие и обращение сохранены.",
            }
            for key in packet["preservation_dimensions"]
        ],
    }


def test_all_26_practices_have_questions_exceptions_and_actions():
    rows = catalog()["practices"]
    assert len(rows) == len({p["id"] for p in rows}) == 26
    assert all(all(p.get(k) for k in ("section", "question", "acceptable", "action")) for p in rows)


def test_legitimate_parallelism_and_dash_do_not_block():
    assert validate(TEXT, assessment(), owner="literary_review") == []


def test_every_practice_requires_evidence_not_a_blanket_pass():
    valid = assessment()
    for index in range(len(valid["practice_checks"])):
        broken = copy.deepcopy(valid)
        broken["practice_checks"].pop(index)
        assert validate(TEXT, broken, owner="literary_review")
        broken = copy.deepcopy(valid)
        broken["practice_checks"][index]["quote"] = "Выдуманная цитата"
        assert validate(TEXT, broken, owner="literary_review")


def test_unknown_duplicate_stale_and_unresolved_reviews_fail():
    for mutate in (
        lambda r: r.update(article_sha256="stale"),
        lambda r: r["practice_checks"].append(r["practice_checks"][0]),
        lambda r: r["practice_checks"][0].update(id="unknown"),
        lambda r: r["practice_checks"][0].update(status="unverified"),
        lambda r: r["logic_checks"][0].update(status="issue"),
        lambda r: r["preservation_checks"][0].update(status="not_applicable"),
    ):
        report = assessment()
        mutate(report)
        assert validate(TEXT, report, owner="literary_review")


def test_na_needs_reason_and_never_excuses_core_logic():
    report = assessment()
    report["practice_checks"][0].update(status="not_applicable", quote="", reason="")
    assert validate(TEXT, report, owner="literary_review")
    report["practice_checks"][0]["reason"] = "Здесь нет утверждения об историческом значении."
    assert not validate(TEXT, report, owner="literary_review")


def test_identifiers_isbn_checksum_but_doi_has_no_checksum():
    result = identifiers("ISBN 978-0-306-40615-7; ISBN 978-0-306-40615-8; DOI 10.1000/xyz-42")
    assert [r["checksum_valid"] for r in result["isbn"]] == [True, False]
    assert result["doi"] == ["10.1000/xyz-42"]
    assert "checksum" not in str(result["doi"])


def test_source_checks_bind_to_actual_handoff_quotes_and_ids():
    handoff = {
        "schema_version": 1,
        "brief": "Условный совет",
        "patch": "test",
        "status": "research_ready",
        "style_profile": "guide",
        "sources": [{"source_id": "s", "url": "https://example.org", "quote": TEXT}],
        "claims": [
            {
                "claim_id": "c",
                "meaning": "Сохранить ресурс",
                "action": "сохраните ресурс",
                "condition": "если нет угрозы",
                "confidence": "high",
                "patch": "test",
                "status": "supported_with_conditions",
                "evidence_refs": ["s"],
            }
        ],
        "chapters": [{"chapter_id": "ch", "title": "Совет", "required_claim_ids": ["c"]}],
        "decisions": [
            {
                "question_id": "q",
                "chapter_id": "ch",
                "question": "Когда сохранять?",
                "required": True,
                "status": "answered",
                "claim_ids": ["c"],
            }
        ],
    }
    report = assessment("fact_review")
    report["handoff_sha256"] = prepare(TEXT, handoff=handoff)["handoff_sha256"]
    report["source_checks"] = [
        {
            "source_id": "s",
            "status": "verified",
            "evidence_quote": TEXT,
            "reason": "Проверено по сохранённому источнику.",
            "identity_check": "Проверено название и соответствие ссылке.",
            "support_check": "Цитата поддерживает условие совета.",
            "access": "snapshot",
        }
    ]
    assert not validate(TEXT, report, owner="fact_review", handoff=handoff)
    for key, value in (
        ("source_id", "other"),
        ("evidence_quote", "Выдумка"),
        ("status", "unavailable"),
        ("support_check", ""),
    ):
        bad = copy.deepcopy(report)
        bad["source_checks"][0][key] = value
        assert validate(TEXT, bad, owner="fact_review", handoff=handoff)


def test_source_free_report_cannot_claim_independent_fact_verification():
    report = assessment("fact_review")
    assert validate(TEXT, report, owner="fact_review")


def test_explicit_negative_verdict_cannot_be_overridden_by_clear_rows():
    report = assessment()
    report["status"] = "blocked"
    assert validate(TEXT, report, owner="literary_review")


@pytest.mark.parametrize("practice", catalog()["practices"], ids=lambda p: p["id"])
def test_every_documented_defect_blocks_even_when_other_checks_pass(practice):
    # Tests the gate, not semantic recognition: reviewer has already diagnosed
    # the catalog's concrete defect. No model-quality claim follows from this.
    text = practice["defect_example"]
    owner = practice["owner"]
    report = assessment(owner, text)
    row = next(r for r in report["practice_checks"] if r["id"] == practice["id"])
    row.update(
        status="issue",
        reason=practice["question"],
        reader_problem=practice["defect_example"],
        benefit=practice["action"],
        meaning_risk="Сохранить факты и оправданный авторский приём.",
        suggestion=practice["action"],
    )
    errors = validate(text, report, owner=owner)
    assert any(f"practice_checks/{practice['id']}: unresolved issue" in e for e in errors)


def test_preservation_binds_both_versions_and_quotes():
    original = "Не только атака, но и защита важны."
    report = assessment()
    report["original_sha256"] = prepare(TEXT, original=original)["original_sha256"]
    for row in report["preservation_checks"]:
        row["original_quote"] = original
        if row["id"] in {"author_voice", "strengths"}:
            row["change_evidence"] = [
                {
                    "original_quote": original,
                    "quote": TEXT,
                    "disposition": "justified",
                    "reason": "Параллелизм и обращение сохранены.",
                    "benefit": "Уточнено условие из задания.",
                    "meaning_risk": "Не потерять обе стороны сравнения.",
                }
            ]
    report["original_factual_checks"] = {
        "whole_text_checked": True,
        "internal_consistency": "clear",
        "source_agreement": "not_performed",
        "issues": [],
    }
    assert not validate(TEXT, report, owner="literary_review", original=original)
    assert validate(TEXT, report, owner="literary_review", original=original + " ещё")
    report["preservation_checks"][0]["original_quote"] = "выдумано"
    assert validate(TEXT, report, owner="literary_review", original=original)


@pytest.mark.parametrize("bad", [None, [], {}, 1, True])
def test_malformed_status_does_not_crash(bad):
    report = assessment()
    report["practice_checks"][0]["status"] = bad
    assert validate(TEXT, report, owner="literary_review")


def test_cli_prepare_is_assignment_and_validate_returns_failure(tmp_path, capsys):
    import json

    from editorteam.cli import main

    article = tmp_path / "article.md"
    article.write_text(TEXT, encoding="utf-8")
    assert (
        main(["editorial-review", "prepare", "--text", str(article), "--owner", "literary_review"])
        == 0
    )
    packet = json.loads(capsys.readouterr().out)
    assert "status" not in packet and len(packet["practices"]) == 19
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"status": "pass"}), encoding="utf-8")
    assert (
        main(
            [
                "editorial-review",
                "validate",
                "--text",
                str(article),
                "--owner",
                "literary_review",
                "--review",
                str(review),
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


@pytest.mark.parametrize(
    "handoff",
    [
        1,
        [],
        "invalid",
        {"sources": [{"source_id": "s", "quote": "fake"}]},
        {"sources": [{"source_id": "s", "quote": None}]},
    ],
)
def test_incomplete_or_malformed_handoff_is_blocked(handoff):
    assert validate(TEXT, assessment("fact_review"), owner="fact_review", handoff=handoff)


def test_factual_cli_requires_valid_full_snapshots(tmp_path, capsys):
    import json

    from test_publication_run import handoff, prepared, reviews

    from editorteam.cli import main
    from editorteam.publication_run import next_task

    run = prepared(tmp_path)
    task = next_task(run)
    fact, _ = reviews(run)
    source_path = task["inputs"]["sources"]
    from pathlib import Path

    snapshots = json.loads(Path(source_path).read_text(encoding="utf-8"))
    candidate = Path(task["inputs"]["draft"]).read_text(encoding="utf-8")
    packet = prepare(candidate, owner="fact_review", handoff=handoff(), snapshots=snapshots)
    fact["sources_sha256"] = packet["sources_sha256"]
    review = tmp_path / "review.json"
    review.write_text(json.dumps(fact), encoding="utf-8")
    args = [
        "editorial-review",
        "validate",
        "--text",
        task["inputs"]["draft"],
        "--owner",
        "fact_review",
        "--handoff",
        task["inputs"]["research"],
        "--review",
        str(review),
    ]
    assert main(args) == 1
    assert "snapshots required" in capsys.readouterr().out
    assert main([*args, "--sources", source_path]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pass"
    snapshots[0]["text"] = "Подменённое содержание"
    bad = tmp_path / "bad-sources.json"
    bad.write_text(json.dumps(snapshots), encoding="utf-8")
    assert main([*args, "--sources", str(bad)]) == 1
    assert "mismatch" in capsys.readouterr().out


def test_cli_bad_handoff_returns_blocked_json_without_traceback(tmp_path, capsys):
    from editorteam.cli import main

    article = tmp_path / "article.md"
    article.write_text(TEXT, encoding="utf-8")
    handoff = tmp_path / "handoff.json"
    handoff.write_text("[]", encoding="utf-8")
    assert (
        main(["editorial-review", "prepare", "--text", str(article), "--handoff", str(handoff)])
        == 1
    )
    assert '"status": "blocked"' in capsys.readouterr().out
