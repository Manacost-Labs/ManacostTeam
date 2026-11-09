"""Run-bound owner requirements and illustrative (not gold) style references."""

import hashlib
import json

import pytest
from test_article_structure import article_plan
from test_publication_run import TEXT, prepared, reviews, write

from editorteam import publication_run as run_api


def context_file(tmp_path, *, requirements=None):
    source = write(tmp_path, "old-guide.md", "Исторический пример. Сначала объясните выбор, затем цену решения.")
    return write(tmp_path, "context.json", {
        "schema_version": 1,
        "profile": "guide",
        "article_plan": article_plan(),
        "requirements": requirements or [{"id": "plain", "instruction": "Объясни решение без технического отчёта."}],
        "style_note": "Выбранный для этой задачи образец, не одобренный обучающий эталон.",
        "style_examples": [{
            "id": "old-guide", "profile": "guide", "source": "https://example.org/old-guide",
            "source_path": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "quote": "Сначала объясните выбор, затем цену решения.",
            "use_for": "Развитие мысли через выбор и его цену", "avoid": "Исторические игровые утверждения",
        }],
    })


def bind_reports(run):
    fact, literary = reviews(run)
    task = run_api.next_task(run)
    for report in (fact, literary):
        report["author_context_sha256"] = task["author_context_sha256"]
    literary["requirement_checks"] = [
        {"id": row["id"], "status": "met", "quote": TEXT, "reason": "Тестовый совет объяснён без отчёта."}
        for row in task["author_context"]["requirements"]
    ]
    literary["style_checks"] = [{
        "id": "old-guide", "status": "met", "quote": TEXT,
        "reason": "Сохранён способ объяснения; старые факты не перенесены.",
    }]
    return fact, literary


def test_context_is_frozen_persistent_and_role_scoped(tmp_path):
    run = prepared(tmp_path)
    artifact = context_file(tmp_path)
    run_api.configure_context(run, artifact=artifact)
    artifact.unlink()
    (tmp_path / "old-guide.md").write_text("Changed source", encoding="utf-8")
    fact_task = run_api.next_task(run)
    assert fact_task["author_context"]["requirements"][0]["id"] == "plain"
    assert "style_examples" not in fact_task["author_context"]
    fact, literary = bind_reports(run)
    run_api.submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    task = run_api.next_task(run)
    assert task["author_context"]["style_examples"][0]["quote"].startswith("Сначала")
    assert task["author_context"]["purpose"] == "task_style_only_not_game_evidence_or_training_approval"
    assert "fact_review" not in task["inputs"]
    task["author_context"]["style_examples"].clear()
    assert run_api.next_task(run)["author_context"]["style_examples"]
    literary.pop("requirement_checks")
    result = run_api.submit(run, stage="literary_review", artifact=write(tmp_path, "lit.json", literary))
    assert result["blocked"]
    repair = run_api.next_task(run)
    assert repair["author_context"]["style_examples"]
    assert "editorial_practices" not in repair  # full catalog is a reviewer task
    run_api.revise(run, artifact=write(tmp_path, "revision.md", TEXT + "\n"))
    child = tmp_path / "continued"
    run_api.continue_research(run, output=child, questions=["Уточнить условие."])
    assert run_api.next_task(child)["author_context_sha256"] == fact_task["author_context_sha256"]


def test_context_change_invalidates_reviews_and_old_hashes(tmp_path):
    run = prepared(tmp_path)
    run_api.configure_context(run, artifact=context_file(tmp_path))
    fact, literary = bind_reports(run)
    run_api.submit(run, stage="fact_review", artifact=write(tmp_path, "f.json", fact))
    run_api.submit(run, stage="literary_review", artifact=write(tmp_path, "l.json", literary))
    run_api.export(run, output=tmp_path / "before.md")
    updated = context_file(tmp_path, requirements=[{"id": "plain", "instruction": "Сохрани условие и исключение."}])
    run_api.configure_context(run, artifact=updated)
    state = run_api.status(run)
    assert state["stage"] == "fact_review" and state["export"] is None
    assert "literary_review" not in state["artifacts"]
    assert (tmp_path / "before.md").exists()
    with pytest.raises(ValueError, match="both reviews"):
        run_api.export(run, output=tmp_path / "after.md")
    result = run_api.submit(run, stage="fact_review", artifact=write(tmp_path, "stale.json", fact))
    assert any("author_context_sha256" in error for error in result["blocked"]["errors"])


@pytest.mark.parametrize("change", ["hash", "quote", "profile", "duplicate", "oversize", "approval"])
def test_context_rejects_invalid_or_mislabelled_style_examples(tmp_path, change):
    run = prepared(tmp_path)
    artifact = context_file(tmp_path)
    data = json.loads(artifact.read_text(encoding="utf-8"))
    row = data["style_examples"][0]
    if change == "hash":
        row["source_sha256"] = "0" * 64
    elif change == "quote":
        row["quote"] = "Не существующая в источнике цитата."
    elif change == "profile":
        row["profile"] = "other-genre"
    elif change == "duplicate":
        data["requirements"] *= 2
    elif change == "oversize":
        row["quote"] = "x" * 3000
    else:
        row["human_approved"] = True
    before = (run / "state.json").read_bytes()
    with pytest.raises(ValueError):
        run_api.configure_context(run, artifact=write(tmp_path, "bad.json", data))
    assert (run / "state.json").read_bytes() == before


def test_literal_requirement_checks_visible_text_without_substring_false_positive(tmp_path):
    from editorteam.publication_context import literal_errors

    context = {"requirements": [{"id": "no-stack", "instruction": "Не используй стек.", "forbidden_literals": ["стек"]}]}
    assert literal_errors(context, "## Ст**ек**\n\nТекст.")
    assert literal_errors(context, '<b>стек</b>')
    assert literal_errors(context, '<h2>стек</h2><p>Текст</p>')
    assert literal_errors(context, '<p>Есть ресурс</p><p>стек</p>')
    assert literal_errors(context, 'ст<br>стек')
    assert literal_errors(context, 'ст<strong>ек</strong>')
    assert literal_errors(context, '![Стек](image.png)')
    assert not literal_errors(context, '[пример](https://example.org/стек)')
    assert not literal_errors(context, '[пример](https://example.org/(стек))')
    assert not literal_errors(context, '<a href="https://example.org/стек">пример</a>')
    assert not literal_errors(context, "Стеклянный предмет.")


def test_context_snapshot_drift_is_not_silently_accepted(tmp_path):
    run = prepared(tmp_path)
    state = run_api.configure_context(run, artifact=context_file(tmp_path))
    path = run / state["author_context_history"][-1]["path"]
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="context.*drift"):
        run_api.next_task(run)


def test_literary_review_rejects_invented_style_quote(tmp_path):
    run = prepared(tmp_path)
    run_api.configure_context(run, artifact=context_file(tmp_path))
    fact, literary = bind_reports(run)
    run_api.submit(run, stage="fact_review", artifact=write(tmp_path, "f.json", fact))
    literary["style_checks"][0]["quote"] = "Придуманная цитата"
    result = run_api.submit(run, stage="literary_review", artifact=write(tmp_path, "l.json", literary))
    assert result["blocked"]


def test_missing_context_cannot_be_silently_skipped(tmp_path):
    from test_publication_run import handoff

    run = prepared(tmp_path)
    bare = tmp_path / "bare"
    run_api.init_run(bare, brief="Guide", patch="test", profile="guide", shortcodes="off")
    state = run_api.status(run)
    run_api.submit(bare, stage="sources", artifact=run / state["artifacts"]["sources"]["path"])
    run_api.submit(bare, stage="research", artifact=write(tmp_path, "handoff.json", handoff()))
    before = (bare / "state.json").read_bytes()
    assert run_api.next_task(bare)["context_status"] == "missing"
    with pytest.raises(ValueError, match="configure author context"):
        run_api.submit(bare, stage="draft", artifact=write(tmp_path, "candidate.md", TEXT))
    assert (bare / "state.json").read_bytes() == before
    run_api.configure_context(bare, artifact=context_file(tmp_path, requirements=[{
        "id": "term", "instruction": "Synthetic explicit word restriction.",
        "forbidden_literals": ["ресурс"],
    }]))
    before = (bare / "state.json").read_bytes()
    with pytest.raises(ValueError, match="forbidden literal"):
        run_api.submit(bare, stage="draft", artifact=write(tmp_path, "candidate.md", TEXT))
    assert (bare / "state.json").read_bytes() == before


def test_same_context_does_not_invalidate_reviews_or_change_state(tmp_path):
    run = prepared(tmp_path)
    artifact = context_file(tmp_path)
    run_api.configure_context(run, artifact=artifact)
    fact, _ = bind_reports(run)
    run_api.submit(run, stage="fact_review", artifact=write(tmp_path, "f.json", fact))
    before = (run / "state.json").read_bytes()
    run_api.configure_context(run, artifact=artifact)
    assert (run / "state.json").read_bytes() == before


@pytest.mark.parametrize("change", ["not_met", "duplicate", "missing", "stale_hash"])
def test_review_cannot_skip_owner_requirement(tmp_path, change):
    run = prepared(tmp_path)
    fact, literary = reviews(run)
    run_api.submit(run, stage="fact_review", artifact=write(tmp_path, "f.json", fact))
    if change == "not_met":
        literary["requirement_checks"][0]["status"] = "not_met"
    elif change == "duplicate":
        literary["requirement_checks"] *= 2
    elif change == "missing":
        literary["requirement_checks"] = []
    else:
        literary["author_context_sha256"] = "0" * 64
    result = run_api.submit(run, stage="literary_review", artifact=write(tmp_path, "l.json", literary))
    assert result["blocked"]
    assert not result["artifacts"]["literary_review"]["accepted"]


def test_export_revalidates_context_checks_after_receipt_tampering(tmp_path):
    run = prepared(tmp_path)
    fact, literary = reviews(run)
    run_api.submit(run, stage="fact_review", artifact=write(tmp_path, "f.json", fact))
    state = run_api.submit(run, stage="literary_review", artifact=write(tmp_path, "l.json", literary))
    receipt = state["artifacts"]["literary_review"]
    literary["requirement_checks"] = []
    path = write(run, receipt["path"], literary)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt["sha256"] = digest
    for row in state["history"]:
        if row["path"] == receipt["path"]:
            row["sha256"] = digest
    write(run, "state.json", state)
    with pytest.raises(ValueError, match="coverage mismatch"):
        run_api.export(run, output=tmp_path / "bad-export.md")
    assert not (tmp_path / "bad-export.md").exists()


def test_literal_violation_rejected_on_revision_without_state_change(tmp_path):
    run = prepared(tmp_path)
    run_api.configure_context(run, artifact=context_file(tmp_path, requirements=[{
        "id": "term", "instruction": "Avoid this term.", "forbidden_literals": ["стек"],
    }]))
    before = (run / "state.json").read_bytes()
    with pytest.raises(ValueError, match="forbidden literal"):
        run_api.revise(run, artifact=write(tmp_path, "bad.md", TEXT + "\n## Ст**ек**"))
    assert (run / "state.json").read_bytes() == before
