"""Подсказки SAGE: только подсказки, названия, сленг и «ё» не «исправляются»."""

import json
import re
import sys
from collections import Counter
from types import SimpleNamespace

import pytest

from editorteam import spell_hints as S
from editorteam.cli import main

KNOWN = {
    "эта",
    "колода",
    "сильная",
    "на",
    "ладдере",
    "еще",
    "ещё",
    "карта",
    "карты",
    "играет",
    "быстро",
}
NO_VOCABULARY = Counter()
NO_ALLOW = frozenset()


class Fake:
    """Модель-пустышка: заменяет слова по таблице и запоминает, что ей передали."""

    name = "fake"

    def __init__(self, replacements):
        self.replacements = replacements
        self.calls = []

    def correct(self, sentences):
        self.calls.append(list(sentences))
        fixed = []
        for sentence in sentences:
            for old, new in self.replacements.items():
                sentence = re.sub(rf"\b{old}\b", new, sentence)
            fixed.append(sentence)
        return fixed


def run(text, replacements, **kwargs):
    kwargs.setdefault("vocabulary", NO_VOCABULARY)
    kwargs.setdefault("allow", NO_ALLOW)
    provider = Fake(replacements)
    report = S.analyze(text, provider, known_word=KNOWN.__contains__, **kwargs)
    return report, provider


# ── что остаётся подсказкой ───────────────────────────────────────────────


def test_typo_becomes_a_review_hint_with_position():
    text = "Заголовок\n\nЭта калода сильная на ладдере."
    report, _ = run(text, {"калода": "колода"})
    (hint,) = report.findings
    assert (hint.severity, hint.confidence, hint.analyzer) == ("review", 0.8, "fake")
    assert (hint.evidence, hint.suggestion, hint.line, hint.column) == ("калода", "колода", 3, 5)
    assert text[hint.start : hint.end] == "калода"
    assert report.metrics["hints"] == 1 and report.metrics["model_replacements"] == 1
    assert "текст не менялся" in report.notes[0]


def test_replacing_one_known_word_with_another_is_not_a_typo_unless_asked():
    text = "Эта карта играет быстро."
    report, _ = run(text, {"карта": "карты"})
    assert report.findings == [] and report.metrics["dropped"] == {"known_word": 1}
    report, _ = run(text, {"карта": "карты"}, include_model_only=True)
    (hint,) = report.findings
    assert (hint.severity, hint.confidence) == ("info", 0.35)


def test_suggestion_must_be_a_known_word():
    report, _ = run("Эта калода играет быстро.", {"калода": "калоду"})
    assert report.findings == [] and report.metrics["dropped"] == {"suggestion_unknown": 1}


# ── что отсекается ────────────────────────────────────────────────────────


def test_yo_and_case_only_changes_are_dropped():
    text = "Эта карта еще играет быстро. Колода сильная на ладдере."
    report, _ = run(text, {"еще": "ещё", "Колода": "колода"})
    assert report.findings == [] and report.metrics["dropped"] == {"case_or_yo_only": 2}


def test_rewriting_is_not_spelling():
    report, _ = run("Эта калода играет быстро.", {"калода": "архетип"})
    assert report.metrics["dropped"] == {"rewrite_not_typo": 1}


def test_game_terms_editorial_terms_and_author_vocabulary_are_not_corrected():
    text = "Эта калода играет быстро. Этот ладер сильный. Этот сетапп сильный."
    fix = {"калода": "колода", "ладер": "ладдер", "сетапп": "сетап"}
    report, _ = run(text, fix, allow=frozenset({"ладер"}), vocabulary=Counter({"сетапп": 2}))
    assert [f.evidence for f in report.findings] == ["калода"]
    assert report.metrics["dropped"] == {"author_vocabulary": 1, "game_or_editorial_term": 1}
    once = run(text, fix, vocabulary=Counter({"сетапп": 1}))[0]
    assert "сетапп" not in {f.evidence for f in once.findings}  # одно употребление — ещё не словарь


def test_names_inside_sentences_are_not_corrected_but_sentence_start_is():
    report, _ = run(
        "Эта карта играет Балинда быстро. Калода сильная.",
        {"Балинда": "Балина", "Калода": "Колода"},
    )
    assert [f.evidence for f in report.findings] == ["Калода"]
    assert report.metrics["dropped"] == {"proper_name": 1}


def test_exact_card_names_and_their_words_are_protected():
    text = "Рыцарь на коне играет быстро. Эта калода быстро играет."
    report, _ = run(text, {"Рыцарь": "Рыцарей", "калода": "колода"}, names=("Рыцарь на коне",))
    assert [f.evidence for f in report.findings] == ["калода"]
    assert report.metrics["dropped"] == {"card_name": 1}


def test_card_words_in_inflected_forms_are_protected_too():
    words = S.card_words(["Рыцарь на коне", "Кел'Тузад"])
    assert {"рыцарь", "коне", "кел", "тузад"} <= words
    report, _ = run("Эта калода играет быстро.", {"калода": "колода"}, names=())
    assert len(report.findings) == 1


def test_markup_code_and_links_are_not_sent_to_the_model_but_headings_are():
    text = (
        "# Калода дня\n\nЭта калода играет быстро. См. https://example.com/калода.\n\n"
        "```\nкалода = 1\n```\n\n> Эта калода чужая цитата.\n"
    )
    report, provider = run(text, {"калода": "колода", "Калода": "Колода"})
    sent = " ".join(" ".join(call) for call in provider.calls)
    assert "http" not in sent and "= 1" not in sent and "чужая" not in sent
    assert "Калода дня" in sent
    assert {f.line for f in report.findings} == {1, 3}


def test_short_fragments_and_long_sentences_are_not_sent():
    text = "Да. т.е. так.\n" + "слово " * 200 + "конец."
    _, provider = run(text, {})
    assert provider.calls == [[]] or provider.calls == []


def test_provider_that_drops_sentences_is_refused():
    class Broken:
        name = "broken"

        def correct(self, sentences):
            return sentences[:-1]

    with pytest.raises(S.ProviderUnavailable, match="число предложений"):
        S.analyze(
            "Эта калода играет быстро. Эта карта играет быстро.",
            Broken(),
            known_word=KNOWN.__contains__,
            vocabulary=NO_VOCABULARY,
            allow=NO_ALLOW,
        )


# ── словари издания ───────────────────────────────────────────────────────


def test_allowlist_collects_dictionaries_terminology_and_protected_words():
    allow = S.allowlist()
    assert {"лейтгейм", "винрейт", "ладдер"} <= allow  # config/dictionaries
    assert {"дека", "колода", "статы"} <= allow  # терминология издания
    assert "возвещение" in allow  # config/games/hearthstone.yaml: protected


def test_corpus_vocabulary_knows_the_authors_words():
    vocabulary = S.corpus_vocabulary()
    assert vocabulary["колода"] > 100 and vocabulary["ладдер"] >= S.MIN_CORPUS_COUNT


@pytest.mark.parametrize(
    ("a", "b", "distance"), [("калода", "колода", 1), ("", "аб", 2), ("кот", "кот", 0)]
)
def test_edit_distance(a, b, distance):
    assert S.edit_distance(a, b) == distance


# ── SAGE: зависимости и согласие на загрузку ─────────────────────────────


def test_sage_without_libraries_reports_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    with pytest.raises(S.ProviderUnavailable, match="requirements-sage.txt"):
        S.SageProvider().correct(["Эта калода играет быстро."])


def test_sage_never_downloads_weights_without_consent(monkeypatch):
    seen = []

    def from_pretrained(name, **kwargs):
        seen.append(kwargs)
        raise OSError("нет в кэше")

    auto = SimpleNamespace(from_pretrained=from_pretrained)
    monkeypatch.setitem(
        sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    )
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(AutoTokenizer=auto, AutoModelForSeq2SeqLM=auto),
    )
    with pytest.raises(S.ProviderUnavailable, match="--download"):
        S.SageProvider().correct(["Эта калода играет быстро."])
    with pytest.raises(S.ProviderUnavailable):
        S.SageProvider(allow_download=True).correct(["Эта калода играет быстро."])
    assert [call["local_files_only"] for call in seen] == [True, False]


# ── оценка на корпусе и команда ──────────────────────────────────────────


def test_evaluate_counts_false_positives_per_thousand_words(tmp_path):
    good = tmp_path / "хорошо.md"
    good.write_text("Эта карта играет быстро.\n", encoding="utf-8")
    bad = tmp_path / "плохо.md"
    bad.write_text("Эта калодаа играет быстро.\n", encoding="utf-8")
    summary = S.evaluate(
        [good, bad],
        Fake({"калодаа": "колода"}),
        known_word=KNOWN.__contains__,
    )
    assert summary["files"] == 2 and summary["hints"] == 1
    assert summary["hints_per_1000_words"] == round(1000 / 8, 2)
    assert summary["top_pairs"] == [["калодаа → колода", 1]] or summary["top_pairs"] == [
        ("калодаа → колода", 1)
    ]


def test_cli_prints_hints_and_never_edits_the_file(tmp_path, capsys, monkeypatch):
    source = tmp_path / "статья.md"
    text = "Эта калода играет быстро на ладдере.\n"
    source.write_text(text, encoding="utf-8")
    monkeypatch.setattr(S, "SageProvider", lambda *a, **k: Fake({"калода": "колода"}))
    assert main(["--format", "json", "spelling-hints", str(source)]) == 0
    payload = json.loads(capsys.readouterr().out)
    (finding,) = payload["findings"]
    assert finding["evidence"] == "калода" and finding["suggestion"] == "колода"
    assert source.read_text(encoding="utf-8") == text
    assert main(["--fail-on", "review", "--format", "json", "spelling-hints", str(source)]) == 1


def test_cli_reports_missing_sage_with_exit_code_2(tmp_path, capsys, monkeypatch):
    source = tmp_path / "статья.md"
    source.write_text("Эта калода играет быстро.\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "torch", None)
    assert main(["spelling-hints", str(source)]) == 2
    assert "подсказки орфографии не запущены" in capsys.readouterr().err


def test_cli_needs_a_file_or_a_corpus(capsys):
    assert main(["spelling-hints"]) == 2
    assert "нужен файл или --corpus" in capsys.readouterr().err
