"""Журнал правок: замечание автора становится правилом, а не остаётся в чате."""

import common as C
import pytest

from editorteam import corrections as CR

gate = C.sibling("rewrite_gate")


def test_seeded_journal_loads_and_kinds_are_valid():
    items = CR.load()
    assert len(items) >= 8
    assert all(c.kind in CR.KINDS for c in items)
    assert any(c.was == "карты-награды" for c in items)


def test_proposals_preserve_short_and_substantive_replacements():
    before = "На Бриллианте эта яичная сборка карает провайдеров и держит темп."
    after = "На Алмазе эта сборка на яйцах карает источники и держит темп."
    found = CR.proposals(before, after)
    pairs = {(p["was"], p["became"]) for p in found}
    assert ("Бриллианте", "Алмазе") in pairs
    assert ("провайдеров", "источники") in pairs
    assert all(len(p["was"].split()) <= CR.MAX_WORDS for p in found)
    rewritten = CR.proposals(
        "Абзац целиком другой и длинный, много слов подряд без замены.",
        "Совсем иной текст, который ничего общего с исходным не имеет вовсе.",
    )
    assert rewritten and rewritten[0]["kind"] == "structure"
    assert rewritten[0]["scope"] == "local"


def test_add_and_load_round_trip(tmp_path, monkeypatch):
    file = tmp_path / "corrections.yaml"
    monkeypatch.setenv("EDITOR_CORRECTIONS", str(file))
    item = CR.add("оболочка", "версия", kind="term", reason="калька")
    assert item.date
    again = CR.add("оболочка", "версия", kind="term")
    assert again.was == item.was
    assert len(CR.load()) == 1
    with pytest.raises(CR.CorrectionsError):
        CR.add("то же", "то же")


def test_legacy_local_preferences_are_not_global_bans():
    text = (
        "Сборки\n"
        + "Новые карты встроились в яичные сборки, а провайдеры расходятся в оценке. " * 3
    )
    hits = gate.terminology_hits(text)
    preferred = {h["preferred"] for h in hits}
    assert "сборка на яйцах" not in preferred
    assert "источник статистики" not in preferred


def test_prompt_view_carries_reason():
    view = CR.for_prompt(author="manacost", game="hearthstone", genre="meta-report")
    assert view and {"was", "became", "kind", "reason"} <= set(view[0])


def test_scoped_policy_is_shared_by_prompt_and_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("EDITOR_CORRECTIONS", str(tmp_path / "corrections.yaml"))
    CR.add(
        "трекер",
        "запись партий",
        author="ivan",
        game="hearthstone",
        genre="meta-report",
        meaning="сбор данных",
        scope="author_global",
        reason="осознанная норма автора",
        context="отчёт по статистике",
    )
    request = dict(author="ivan", game="hearthstone", genre="meta-report", meaning="сбор данных")
    assert CR.for_prompt(**request)[0]["context"] == "отчёт по статистике"
    assert CR.for_prompt(**request)[0]["enforcement"] == "required"
    assert CR.for_gate(**request)[0]["preferred"] == "запись партий"
    assert gate.correction_rules(**request) == CR.for_gate(**request)
    for key, value in {
        "author": "anna",
        "game": "wow",
        "genre": "news",
        "meaning": "приложение",
    }.items():
        other = {**request, key: value}
        assert CR.for_prompt(**other) == []
        assert CR.for_gate(**other) == []
    assert CR.for_gate() == []


def test_unscoped_legacy_record_stays_readable_and_advisory(tmp_path, monkeypatch):
    file = tmp_path / "corrections.yaml"
    file.write_text(
        "version: 1\ncorrections:\n  - was: трекер\n    became: запись партий\n    context: приложение\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EDITOR_CORRECTIONS", str(file))
    assert CR.load()[0].context == "приложение"
    assert CR.for_gate(text="приложение трекер") == []
    assert CR.for_prompt(text="приложение трекер")[0]["enforcement"] == "advisory"


def test_insert_delete_and_model_proposal_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("EDITOR_CORRECTIONS", str(tmp_path / "corrections.yaml"))
    inserted = CR.proposals(
        "Сохраните карту.", "Сохраните карту. При угрозе поражения разыграйте её."
    )
    deleted = CR.proposals("Сохраните карту. Это важный совет.", "Сохраните карту.")
    assert inserted[0]["operation"] == "insert"
    assert deleted[0]["operation"] == "delete"
    for item in inserted + deleted:
        CR.add(
            **item, reason="условие или удаление пустой оценки", model_proposal="Разыграйте карту."
        )
    stored = CR.load()
    assert len(stored) == 2
    assert stored[0].model_proposal == "Разыграйте карту."
    assert stored[1].became == ""
    assert CR.for_gate() == []


def test_same_replacement_can_belong_to_different_authors(tmp_path):
    file = tmp_path / "corrections.yaml"
    CR.add("термин", "слово", author="a", file=file)
    CR.add("термин", "слово", author="b", file=file)
    assert len(CR.load(file)) == 2


@pytest.mark.parametrize("depth", ["обычная", "переплавка"])
def test_model_and_postflight_resolve_same_author_policy(tmp_path, monkeypatch, depth):
    from editorteam import server

    monkeypatch.setenv("EDITOR_CORRECTIONS", str(tmp_path / "corrections.yaml"))
    CR.add("терм", "термин", scope="author_global", author="ivan", game="hearthstone", genre="news")
    for author, required in [("ivan", True), ("anna", False)]:
        prompt = server.rules_for("hearthstone", "news", author=author)
        assert bool(prompt["corrections"]) == required
        verdict = server.validate(
            "Терм описан.", "Терм описан.", "hearthstone", "news", depth=depth, author=author
        )
        assert any(v["kind"] == "term_replace" for v in verdict["violations"]) == required


def test_cli_scoped_learning_and_validation(tmp_path, monkeypatch, capsys):
    from editorteam.cli import main

    monkeypatch.setenv("EDITOR_CORRECTIONS", str(tmp_path / "corrections.yaml"))
    assert (
        main(
            [
                "learn",
                "add",
                "терм",
                "термин",
                "--author",
                "ivan",
                "--game",
                "hearthstone",
                "--genre",
                "news",
                "--meaning",
                "application",
                "--scope",
                "author_global",
                "--context",
                "название функции",
                "--reason",
                "терминология",
            ]
        )
        == 0
    )
    capsys.readouterr()
    text = tmp_path / "text.md"
    text.write_text("Терм описан.", encoding="utf-8")
    base = [
        "validate-edit",
        str(text),
        str(text),
        "--game",
        "hearthstone",
        "--profile",
        "news",
        "--meaning",
        "application",
        "--format",
        "json",
        "--author",
    ]
    assert main(base + ["ivan"]) == 1
    capsys.readouterr()
    assert main(base + ["anna"]) == 0


def test_prompt_limit_never_hides_a_rule_enforced_by_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("EDITOR_CORRECTIONS", str(tmp_path / "corrections.yaml"))
    CR.save(
        [
            CR.Correction(was=f"терм{i}", became=f"термин{i}", scope="language_norm")
            for i in range(45)
        ]
    )
    assert len(CR.for_gate()) == 45
    assert len(CR.for_prompt()) == 45


@pytest.mark.parametrize(
    "before,after,operation",
    [
        ("Then -- next.", "Then explanation next.", "insert"),
        ("Then explanation next.", "Then -- next.", "delete"),
    ],
)
def test_punctuation_only_diff_side_is_reclassified_for_cli(
    tmp_path, monkeypatch, capsys, before, after, operation
):
    from editorteam.cli import main

    monkeypatch.setenv("EDITOR_CORRECTIONS", str(tmp_path / "corrections.yaml"))
    source, edited = tmp_path / "before.md", tmp_path / "after.md"
    source.write_text(before, encoding="utf-8")
    edited.write_text(after, encoding="utf-8")
    proposals = CR.proposals(before, after)
    assert proposals[0]["operation"] == operation
    assert proposals[0]["kind"] == "structure"
    assert main(["learn", "diff", str(source), str(edited), "--format", "json"]) == 0
    capsys.readouterr()
    stored = CR.load()
    assert len(stored) == 1
    assert stored[0].operation == operation
