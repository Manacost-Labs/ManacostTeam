"""Coverage and dependency checks, not an automatic semantic quality score."""

import copy
import json
from pathlib import Path

import pytest

from editorteam.article_structure import (
    inventory,
    validate_plan,
    validate_plan_evidence,
    validate_plan_review,
    validate_review,
)


def structure_assessment(text):
    """Synthetic evidence for unrelated test gates; never used by production."""
    packet = inventory(text)
    return {
        "article_sha256": packet["article_sha256"],
        "reader_question": "Synthetic question.", "main_answer": "Synthetic answer.",
        "order_reason": "Synthetic explanation order checked.",
        "ending_reason": "Synthetic ending answers the stated question.",
        "blocks": [{
            "id": b["id"], "quote": b["quote"], "function": "Synthetic explanatory block.",
            "new_information": "Synthetic contribution or intentional reprise.",
            "link_to_previous": "Synthetic progression checked, first block opens the question.",
            "depends_on": [], "repeat_of": [], "repeat_reason": "",
            "status": "clear", "reason": "Synthetic fixture only.",
        } for b in packet["blocks"]],
    }


def article_plan():
    return {
        "reader_question": "Когда сохранять ресурс?",
        "main_answer": "При слабой позиции, кроме угрозы поражения.",
        "sections": [{"id": "decision", "question": "Как выбрать действие?",
                      "contribution": "Совет вместе с условием и исключением.",
                      "depends_on": [], "claim_ids": ["CLM-1"]}],
    }


@pytest.mark.parametrize("case", json.loads((Path(__file__).parent / "fixtures/article-structure.json").read_text(encoding="utf-8")), ids=lambda c: c["name"])
def test_shared_go_python_inventory_fixture(case):
    assert inventory(case["text"])["blocks"] == case["blocks"]


def test_inventory_keeps_headings_paragraphs_lists_fences_and_html():
    text = "# Выбор\nПервый абзац\r\nпродолжение.\n\n- Пункт\n  пояснение.\n- Другой\n\n```md\n# не заголовок\n\n- не пункт\n```\n<p>Один.</p><p>Два.</p>"
    blocks = inventory(text)["blocks"]
    assert [b["kind"] for b in blocks] == ["heading", "text", "list", "list", "code", "text", "text"]
    assert blocks[1]["quote"] == "Первый абзац\r\nпродолжение."
    assert blocks[2]["quote"] == "- Пункт\n  пояснение."
    assert blocks[4]["quote"] == "```md\n# не заголовок\n\n- не пункт\n```"
    assert [b["quote"] for b in blocks[-2:]] == ["<p>Один.</p>", "<p>Два.</p>"]
    assert [b["id"] for b in blocks] == [f"b{i:03d}" for i in range(1, 8)]


def test_inventory_rejects_excess_instead_of_silently_truncating():
    with pytest.raises(ValueError, match="256"):
        inventory("\n\n".join(f"Block {n}" for n in range(257)))


@pytest.mark.parametrize("change", ["missing", "duplicate", "reordered", "stale", "wrong_quote", "future", "issue", "empty_reason"])
def test_structure_cannot_be_approved_from_one_quoted_opening(change):
    text = "Вступление.\n\nСовет с условием.\n\nПротивоположный совет."
    report = structure_assessment(text)
    if change == "missing":
        report["blocks"].pop(1)
    elif change == "duplicate":
        report["blocks"][1] = copy.deepcopy(report["blocks"][0])
    elif change == "reordered":
        report["blocks"].reverse()
    elif change == "stale":
        report["article_sha256"] = "0" * 64
    elif change == "wrong_quote":
        report["blocks"][1]["quote"] = "Вступление."
    elif change == "future":
        report["blocks"][1]["depends_on"] = ["b003"]
    elif change == "issue":
        report["blocks"][2]["status"] = "issue"
    else:
        report["blocks"][1]["link_to_previous"] = ""
    assert validate_review(text, report)


def test_deliberate_reprise_is_allowed_with_specific_function():
    text = "Условие.\n\nПрименение.\n\nУсловие."
    report = structure_assessment(text)
    report["blocks"][1]["depends_on"] = ["b001"]
    report["blocks"][2].update(repeat_of=["b001"], repeat_reason="Краткое напоминание после применения.")
    assert validate_review(text, report) == []
    report["blocks"][2]["repeat_reason"] = ""
    assert validate_review(text, report)


def test_plan_requires_prerequisites_before_dependent_section():
    plan = article_plan()
    plan["sections"].append({**plan["sections"][0], "id": "application", "depends_on": ["decision"]})
    validate_plan(plan)
    plan["sections"].reverse()
    with pytest.raises(ValueError, match="earlier"):
        validate_plan(plan)


def test_plan_binds_claims_without_inventing_new_evidence():
    from test_publication_run import handoff

    plan = article_plan()
    assert validate_plan_evidence(plan, handoff()) == []
    plan["sections"][0]["claim_ids"] = ["invented"]
    errors = validate_plan_evidence(plan, handoff())
    assert any("unknown" in e for e in errors)
    assert any("uncovered" in e for e in errors)


def test_plan_review_detects_actual_order_that_violates_a_prerequisite():
    plan = article_plan()
    plan["sections"].append({**plan["sections"][0], "id": "application", "depends_on": ["decision"]})
    rows = [
        {"id": "decision", "block_ids": ["b002"], "status": "clear", "reason": "Premise here."},
        {"id": "application", "block_ids": ["b001"], "status": "clear", "reason": "Application here."},
    ]
    assert validate_plan_review(plan, "Совет.\n\nЕго предпосылка.", rows)
    rows[0]["block_ids"], rows[1]["block_ids"] = ["b001"], ["b002"]
    assert validate_plan_review(plan, "Предпосылка.\n\nСовет.", rows) == []
    rows[0]["block_ids"], rows[1]["block_ids"] = ["b001", "b003"], ["b002"]
    assert validate_plan_review(plan, "Часть предпосылки.\n\nСовет.\n\nНеобходимое условие.", rows)


def test_old_opening_only_review_cannot_cover_appended_contradictions(tmp_path):
    from test_publication_run import TEXT, handoff, prepared, reviews

    from editorteam.publication_review import article_hash, validate_literary
    from editorteam.publication_run import next_task

    run = prepared(tmp_path)
    _, report = reviews(run)
    text = TEXT + "\n\n## Решение\nУлучшайте таверну только после появления источника усилений.\n\n## До старта\nСначала улучшайте таверну. Источник усилений не нужен.\n\n## Решение\nУлучшайте таверну только после появления источника усилений."
    report["article_sha256"] = article_hash(text)
    report["structure_review"]["article_sha256"] = article_hash(text)
    assert len(report["paragraph_functions"]) == 1
    assert len(report["structure_review"]["blocks"]) == 1
    import json
    from pathlib import Path

    snapshots = json.loads(Path(next_task(run)["inputs"]["sources"]).read_text(encoding="utf-8"))
    errors = validate_literary(text, report, require_extended=True, require_practices=True, handoff=handoff(), snapshots=snapshots)
    assert any("every block must be covered" in e for e in errors)


def test_legacy_context_needs_plan_before_next_revision(tmp_path):
    import json

    from test_publication_run import TEXT, prepared, write

    from editorteam.publication_run import configure_context, next_task, revise

    run = prepared(tmp_path)
    context = json.loads((tmp_path / "task-context.json").read_text(encoding="utf-8"))
    context.pop("article_plan")
    configure_context(run, artifact=write(tmp_path, "legacy-context.json", context))
    with pytest.raises(ValueError, match="article_plan"):
        revise(run, artifact=write(tmp_path, "changed.md", TEXT + "\n"))
    assert next_task(run)["stage"] == "fact_review"
