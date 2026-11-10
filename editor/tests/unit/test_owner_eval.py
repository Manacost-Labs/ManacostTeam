"""owner-eval: разметка отклонений против находок audit. Синтетический набор."""

import json

from editorteam import owner_eval as E
from editorteam.cli import main

TEXT = (
    "# Гайд\n\n"
    "Растите [hs_bg id=\"X\"]стек[/hs_bg] каждый ход.\n\n"
    "- **Торговец** — в начале игры раскапывает существо 7 уровня.\n"
    "Сильные игроки чаще собирают двух обычных звонарей.\n"
)


def finding(fid, line=None, evidence="", **meta):
    return {"id": fid, "severity": "review", "line": line, "evidence": evidence, "meta": meta}


def test_fragment_on_flagged_line_is_detected():
    rejection = {
        "id": "R1", "version": "v.md", "category": "card_text_retelling",
        "fragments": ["в начале игры раскапывает существо 7 уровня"],
    }
    r = E.judge(rejection, TEXT, [finding("card_paraphrase.retelling", 5)])
    assert r["status"] == "detected"
    assert r["fragments"][0]["lines"] == [5]


def test_word_fragment_matches_evidence_not_line():
    rejection = {"id": "R2", "version": "v.md", "category": "overused_word", "fragments": ["стек"]}
    hit = finding("owner.overused_word", 3, "стек, стека", lemma="стек")
    assert E.judge(rejection, TEXT, [hit])["status"] == "detected"
    # другая находка на той же строке слово не помечает
    assert E.judge(rejection, TEXT, [finding("clarity.sentence.load", 3)])["status"] == "missed"


def test_partial_and_unlabeled_hits():
    rejection = {
        "id": "R3", "version": "v.md", "category": "card_text_retelling_and_duplication",
        "fragments": [
            "в начале игры раскапывает существо 7 уровня",
            "Сильные игроки чаще собирают двух обычных звонарей",
        ],
    }
    r = E.judge(
        rejection, TEXT, [finding("card_paraphrase.retelling", 5), finding("owner.section_repeat", 9)]
    )
    assert r["status"] == "partial"
    assert r["unlabeled_hits"] == [{"id": "owner.section_repeat", "line": 9}]


def test_non_deterministic_category_needs_reviewer_even_if_touched():
    rejection = {
        "id": "R4", "version": "v.md", "category": "illogical_comparison",
        "fragments": ["Сильные игроки чаще собирают двух обычных звонарей"],
    }
    r = E.judge(rejection, TEXT, [finding("card_paraphrase.retelling", 6)])
    assert r["status"] == "needs_reviewer"
    assert r["reason"]
    assert r["fragments"][0]["other_hits"] == ["card_paraphrase.retelling"]


def dataset(tmp_path):
    (tmp_path / "versions").mkdir()
    (tmp_path / "gold").mkdir()
    (tmp_path / "versions" / "v1.md").write_text(TEXT, encoding="utf-8")
    (tmp_path / "versions" / "final-accepted.md").write_text("# Гайд\n\nЧисто.\n", encoding="utf-8")
    (tmp_path / "gold" / "g.txt").write_text("### Эталон\nЧисто.\n", encoding="utf-8")
    labels = {
        "article": "синтетика",
        "rejections": [
            {"id": "R1", "version": "v1.md", "category": "overused_word", "fragments": ["стек"]},
            {"id": "R2", "version": "v1.md", "category": "weak_or_obvious_tips", "fragments": []},
        ],
    }
    (tmp_path / "labels.json").write_text(json.dumps(labels, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_evaluate_runs_each_file_once_and_counts_clean_findings(tmp_path):
    calls = []

    def run(text, name):
        calls.append(name)
        if name == "g.txt":
            return [finding("owner.section_repeat", 2), finding("clarity.thesis.missing", 1)]
        if name == "final-accepted.md":
            return []
        return [finding("owner.overused_word", 3, "стек", lemma="стек")]

    result = E.evaluate(dataset(tmp_path), run)
    assert sorted(calls) == ["final-accepted.md", "g.txt", "v1.md"]
    assert result["totals"] == {"detected": 1, "partial": 0, "missed": 0, "needs_reviewer": 1}
    assert set(result["clean"]) == {"versions/final-accepted.md", "gold/g.txt"}
    assert result["clean"]["gold/g.txt"]["new_checks"] == {"error": 0, "review": 1}
    assert result["clean_totals"] == {"error": 0, "review": 1}
    table = E.render(result)
    assert "R1" in table and "detected" in table and "needs_reviewer" in table


def test_cli_owner_eval_json(tmp_path, capsys):
    folder = dataset(tmp_path)
    assert main(["owner-eval", str(folder), "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in result["rejections"]] == ["R1", "R2"]
    assert result["rejections"][1]["status"] == "needs_reviewer"
    assert main(["owner-eval", str(tmp_path / "нет")]) == 2
