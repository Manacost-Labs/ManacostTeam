"""Профили Полей сражений считают чужие слова по своему словарю.

У гайдов по колодам нет «аберраций» и «божеств»: при общем словаре каждый
текст о Полях сражений получал 19% чужих слов, отказ затвора становился
шумом, и настоящие сигналы в нём терялись.
"""

import common as C

lexicon = C.sibling("lexicon")

TEXT = (
    "Аберрации по-прежнему задают темп ранней игры. Божество приходит в бой после гибели "
    "трех аберраций, а звукорегуляторы усиливают следующих звукорегуляторов. " * 6
)


def test_profile_settings_are_read_from_yaml():
    s = lexicon.profile_settings("battlegrounds-article")
    assert s["extra_corpora"] == ["corpus-bg"]
    assert "battlegrounds" in s["glossary"]
    assert s["skip_unknown_cards"] is True
    assert 0 < s["warn_pct"] < s["fail_pct"]


def test_constructed_profile_has_no_extra_settings():
    assert lexicon.profile_settings("constructed-guide") == {}
    assert lexicon.profile_settings(None) == {}


def test_glossary_terms_are_not_foreign_for_battlegrounds():
    plain = lexicon.measure(TEXT)
    with_profile = lexicon.measure(TEXT, profile="battlegrounds-article")
    assert plain and with_profile
    assert with_profile["ratio"] < plain["ratio"]
    assert not {"аберрации", "божество", "звукорегуляторов"} & set(with_profile["missing"])


def test_thresholds_come_from_profile():
    m = {"words": 500, "unique": 100, "missing": ["слово"] * 6, "ratio": 6.0}
    default = lexicon.findings("x", m)
    bg = lexicon.findings("x", m, profile="battlegrounds-article")
    assert default and default[0]["severity"] == "review"  # 6.0 не выше порога 6.0
    assert bg and bg[0]["severity"] == "review"  # выше warn 4.6, ниже fail 8.8
    m["ratio"] = 9.0
    assert lexicon.findings("x", m, profile="battlegrounds-article")[0]["severity"] == "error"
