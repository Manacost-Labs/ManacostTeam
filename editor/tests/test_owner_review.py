from copy import deepcopy

import pytest

from editorteam.owner_review import CATEGORIES, validate_deletion, validate_rubric
from editorteam.publication_review import article_hash

TEXT = "Сохраняйте ресурс при угрозе поражения. Лишняя рамка."


def rubric(text=TEXT):
    return [
        {
            "id": key,
            "status": "clear",
            "quote": text,
            "reason": "Синтетический условный совет проверен.",
        }
        for key in CATEGORIES
    ]


def test_rubric_requires_every_category_and_exact_nonempty_quotes():
    assert validate_rubric(TEXT, rubric()) == []
    for defect in ("missing", "duplicate", "empty", "invented", "unknown"):
        rows = deepcopy(rubric())
        if defect == "missing":
            rows.pop()
        elif defect == "duplicate":
            rows[-1] = rows[0]
        elif defect == "unknown":
            rows[-1]["id"] = "other"
        else:
            rows[-1]["quote"] = "" if defect == "empty" else "Выдуманная цитата"
        assert validate_rubric(TEXT, rows), defect


def test_negative_rubric_is_valid_evidence_but_blocks_acceptance():
    rows = rubric()
    rows[0].update(status="issue", reason="Пересказ не помогает выбрать действие.")
    assert validate_rubric(TEXT, rows, allow_unresolved=True) == []
    assert "repair" in " ".join(validate_rubric(TEXT, rows))


def deletion(before=TEXT):
    return {
        "article_sha256": article_hash(before),
        "deletions": [
            {
                "start": before.index(" Лишняя"),
                "quote": " Лишняя рамка.",
                "reason": "Не меняет решение игрока.",
            }
        ],
        "unchanged_reason": "",
    }


def test_deletion_replays_only_exact_nonoverlapping_removals():
    result, errors = validate_deletion(TEXT, deletion())
    assert errors == []
    assert result == "Сохраняйте ресурс при угрозе поражения."
    for defect in ("hash", "quote", "overlap", "reason"):
        report = deletion()
        if defect == "hash":
            report["article_sha256"] = "a" * 64
        elif defect == "overlap":
            report["deletions"] *= 2
        else:
            report["deletions"][0][defect] = ""
        assert validate_deletion(TEXT, report)[1]


def test_deletion_cannot_supply_new_text_or_erase_article():
    report = deletion()
    report["text"] = "Новое объяснение."
    assert validate_deletion(TEXT, report)[1]
    report = {
        "article_sha256": article_hash(TEXT),
        "deletions": [{"start": 0, "quote": TEXT, "reason": "Всё лишнее"}],
    }
    assert validate_deletion(TEXT, report)[1]
    report = {
        "article_sha256": article_hash(TEXT),
        "deletions": [],
        "unchanged_reason": "Оба предложения нужны для выбора.",
    }
    assert validate_deletion(TEXT, report) == (TEXT, [])


@pytest.mark.parametrize("rows", [None, {}, [None], [{"id": []}]])
def test_malformed_rubric_is_a_validation_error(rows):
    assert validate_rubric(TEXT, rows)


def test_native_deletion_precedes_reviews_and_replays_saved_removals(tmp_path):
    from test_publication_run import next_task, prepared, revise, status, submit, write

    run = prepared(tmp_path)
    revise(run, artifact=write(tmp_path, "water.md", TEXT))
    task = next_task(run)
    assert task["stage"] == "deletion_pass"
    assert "deletion_assignment" in task
    with pytest.raises(ValueError, match="deletion_pass"):
        submit(run, stage="literary_review", artifact=tmp_path / "missing.json")
    submit(run, stage="deletion_pass", artifact=write(tmp_path, "cuts.json", deletion()))
    task = next_task(run)
    assert task["stage"] == "fact_review"
    from pathlib import Path

    assert (
        Path(task["inputs"]["draft"]).read_text(encoding="utf-8")
        == "Сохраняйте ресурс при угрозе поражения."
    )
    receipt = status(run)["artifacts"]["deletion_pass"]
    assert "Не меняет решение" in (run / receipt["path"]).read_text(encoding="utf-8")
    from test_publication_run import TEXT as ORIGINAL

    from editorteam.publication_run import _previous_draft

    assert _previous_draft(run, status(run)) == ORIGINAL


@pytest.mark.parametrize("defect", ["missing", "quote", "issue", "unverified"])
def test_native_owner_verdict_blocks_export_and_preserves_fragment(tmp_path, defect):
    from test_publication_run import TEXT as ARTICLE
    from test_publication_run import export, next_task, prepared, reviews, submit, write

    run = prepared(tmp_path)
    fact, literary = reviews(run)
    submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    if defect == "missing":
        literary.pop("owner_checks")
    elif defect == "quote":
        literary["owner_checks"][0]["quote"] = ""
    else:
        literary["owner_checks"][0].update(status=defect, reason="Проверить пользу фрагмента.")
    result = submit(run, stage="literary_review", artifact=write(tmp_path, "lit.json", literary))
    assert result["blocked"] and not result["history"][-1]["accepted"]
    assert any("owner_checks" in e for e in next_task(run)["repair"]["errors"])
    if defect in {"issue", "unverified"}:
        assert ARTICLE in " ".join(result["blocked"]["errors"])
    with pytest.raises(ValueError, match="both reviews"):
        export(run, output=tmp_path / "final.md")


def test_sample_budget_is_measured_from_whole_sources_and_not_excerpt(tmp_path):
    import json

    from test_publication_context import context_file

    from editorteam.owner_review import genre_assignment, validate_genre, word_count
    from editorteam.publication_context import freeze, validate

    context = json.loads(freeze(context_file(tmp_path), "guide"))
    sample = context["style_examples"][0]
    assert sample["source_word_count"] > word_count(sample["quote"])
    measured = genre_assignment(TEXT, context)
    count = sample["source_word_count"]
    assert measured["word_budget"] == {"min": count, "max": count}
    assert (
        validate_genre(
            TEXT, context, {"genre_review": {**measured, "reason": "Сравнение по жанру."}}
        )
        == []
    )
    assert validate_genre(
        TEXT, context, {"genre_review": {**measured, "word_budget": {"min": 440, "max": 1300}}}
    )
    sample.pop("source_word_count")
    validate(context, "guide", frozen=True)  # saved old contexts remain readable
    assert genre_assignment(TEXT, context)["word_budget"] is None


def test_reviewer_categories_and_claim_guidance_match_owner_eval():
    from test_publication_run import handoff

    from editorteam.owner_eval import NEEDS_REVIEWER, REVIEW_CATEGORY
    from editorteam.owner_review import CLAIM_GUIDANCE
    from editorteam.publication_run import chapter_brief, craft_guidance

    assert set(CATEGORIES) <= set(NEEDS_REVIEWER)
    assert REVIEW_CATEGORY["water_hedging"] == "obvious_or_water"
    assert REVIEW_CATEGORY["genre_mismatch_too_long_literary"] == "genre_fit"
    h = handoff()
    h["claims"][0]["claim_kind"] = "observation"
    h["claims"][0]["research_context"] = {"reason": "", "observation_scope": {"sample_size": 3}}
    assert chapter_brief(h)["chapters"][0]["claims"][0]["claim_kind"] == "observation"
    assert CLAIM_GUIDANCE in craft_guidance("draft")["principles"]
    ids = [row["id"] for row in craft_guidance("draft")["editorial_passes"]]
    assert ids.index("author") < ids.index("deletion_pass") < ids.index("prose")
    assert [row["id"] for row in craft_guidance("deletion_pass")["editorial_passes"]] == ["deletion_pass"]


def test_saved_v3_without_deletion_or_rubric_is_readable_but_cannot_export(tmp_path):
    import hashlib
    import json

    from test_publication_run import export, next_task, prepared, reviews, status, submit, write

    run = prepared(tmp_path)
    fact, lit = reviews(run)
    submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    state = submit(run, stage="literary_review", artifact=write(tmp_path, "lit.json", lit))
    assert state["stage"] == "ready"
    state["review_contract_version"] = 3
    state["artifacts"].pop("deletion_pass")
    state["history"] = [row for row in state["history"] if row["stage"] != "deletion_pass"]
    lit.pop("owner_checks")
    lit.pop("genre_review")
    raw = json.dumps(lit).encode("utf-8")
    receipt = state["artifacts"]["literary_review"]
    (run / receipt["path"]).write_bytes(raw)
    for row in state["history"] + [receipt]:
        if row["path"] == receipt["path"]:
            row["sha256"] = hashlib.sha256(raw).hexdigest()
    (run / "state.json").write_text(json.dumps(state), encoding="utf-8")
    before = (run / "state.json").read_bytes()
    assert status(run)["stage"] == "ready"
    assert next_task(run)["current_review_required"] is True
    with pytest.raises(ValueError, match="current independent re-review"):
        export(run, output=tmp_path / "no.md")
    assert (run / "state.json").read_bytes() == before


def test_malformed_rubric_status_does_not_crash():
    rows = rubric()
    rows[0]["status"] = []
    assert validate_rubric(TEXT, rows)
