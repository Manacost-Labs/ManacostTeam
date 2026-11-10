"""Проверки по замечаниям владельца: только синтетические тексты."""

import json
from collections import Counter

import common as C
import pytest

from editorteam import card_paraphrase as P
from editorteam import owner_checks as O
from editorteam import publication_context
from editorteam.cli import _masked_with_headings, _prose_lines, main

cards = C.sibling("cards")
MORPH = C.morph()

HERO_POWER = (
    "Пассивный эффект: в начале игры вы раскапываете существо 7-го уровня "
    "и получаете его, потратив 60 золотых. (Еще 60!)"
)
MAGNET = (
    "Когда вы применяете «Магнетизм» к другому существу, механизм также "
    "примагничивается к этому существу."
)
BG = {
    "BGX_HERO_1": {"n": "Торговец песком", "t": [HERO_POWER]},
    "BGX_1": {"n": "Притягательный звонарь", "t": [MAGNET]},
}


@pytest.fixture(scope="module")
def lex():
    texts = {"Огненный шар": ["Наносит 6 ед. урона."], **P.bg_texts_by_name(BG)}
    idx = cards.Index(list(texts), MORPH)
    return P.Lexicon(idx, texts, Counter(), cards.NOT_CARDS)


# ── пересказ по предложению ──────────────────────────────────────────────


def test_hero_power_retelling_is_flagged_despite_condition_word(lex):
    text = (
        "## Герои\n\n- **Торговец песком** — в начале игры раскапывает существо "
        "7 уровня, которое приходит, когда вы потратите 60 золотых.\n"
    )
    hits = P.retellings(text, lex, _prose_lines)
    assert [(h["card"], h["line"]) for h in hits] == [("Торговец песком", 3)]
    assert hits[0]["card_text"] == HERO_POWER


def test_retelling_with_decision_and_reason_is_advice(lex):
    text = (
        "Торговец песком хорош для механизмов, потому что раскопка 7 уровня "
        "приходит рано: берите его, если в лобби есть механизмы.\n"
    )
    assert P.retellings(text, lex, _prose_lines) == []


def test_shortcode_names_the_exact_battlegrounds_card(lex):
    text = (
        '[hs_bg id="BGX_1"]Звонарь[/hs_bg] — когда вы применяете магнетизм '
        "к другому существу, механизм примагничивается и к нему.\n"
    )
    aliases = P.shortcode_aliases(text, BG)
    assert aliases == {"Звонарь": "Притягательный звонарь"}
    hits = P.retellings(text, lex, _prose_lines, aliases)
    assert [h["card"] for h in hits] == ["Притягательный звонарь"]
    # без шорткода «Звонарь» — не карта, пересказывать нечего
    assert P.retellings(text, lex, _prose_lines) == []


def test_build_bg_maps_hero_to_power_and_minion_to_both_texts():
    raw = [
        {"id": "BGX_HERO_1", "dbfId": 1, "name": "Герой", "set": "BATTLEGROUNDS",
         "type": "HERO", "heroPowerDbfId": 2},
        {"id": "BGX_HERO_1p", "dbfId": 2, "name": "Сила", "set": "BATTLEGROUNDS",
         "type": "HERO_POWER", "text": "<b>Пассивный эффект:</b> раскапывает."},
        {"id": "BGX_HERO_1_SKIN_A", "dbfId": 3, "name": "Герой", "set": "BATTLEGROUNDS",
         "type": "HERO", "heroPowerDbfId": 2},
        {"id": "BGX_5", "dbfId": 4, "name": "Звонарь", "set": "BATTLEGROUNDS", "type": "MINION",
         "text": "Дает +1.", "battlegroundsPremiumDbfId": 5},
        {"id": "BGX_5_G", "dbfId": 5, "name": "Звонарь", "set": "BATTLEGROUNDS",
         "type": "MINION", "text": "Дает +2."},
        {"id": "BGX_E", "dbfId": 6, "name": "Чары", "set": "BATTLEGROUNDS",
         "type": "ENCHANTMENT", "text": "+1/+1."},
    ]
    assert P.build_bg(raw) == {
        "BGX_5": {"n": "Звонарь", "t": ["Дает +1.", "Дает +2."]},
        "BGX_HERO_1": {"n": "Герой", "t": ["Пассивный эффект: раскапывает."]},
        "BGX_HERO_1p": {"n": "Сила", "t": ["Пассивный эффект: раскапывает."]},
    }


def test_update_texts_writes_bg_section(tmp_path):
    out = tmp_path / "texts.json"
    raw = [{"id": "BGX_1", "dbfId": 1, "name": "А", "set": "BATTLEGROUNDS",
            "type": "MINION", "techLevel": 1, "text": "Рывок"}]
    P.update_texts(lambda url: raw, out, taken="2026-11-10")
    assert P.load_bg(out) == {"BGX_1": {"n": "А", "t": ["Рывок"]}}
    assert P.load_bg(tmp_path / "нет.json") == {}


def test_shipped_snapshot_has_hero_powers():
    bg = P.load_bg()
    assert len(bg) > 1000
    assert any(cid.startswith("TB_BaconShop_HERO") for cid in bg)


# ── слово-паразит ────────────────────────────────────────────────────────

FREQ = {
    "words": 1_000_000,
    "nouns": {"стол": 6000, "игрок": 8000, "покупка": 3000, "золото": 5000, "ход": 9000},
    "game": ["звонарь"],
}
FILLER = "Игрок спокойно выбирает покупки и следит за золотом на каждом ходу. "


def test_overused_word_is_flagged_against_author_frequency():
    text = (FILLER * 10 + "Стек растет, стек копится, стеком гордится звонарь. ") * 4
    text += "Звонарь звонарь звонарь звонарь звонарь звонарь звонарь звонарь. "
    text += "Стол стол стол стол стол стол стол стол стол. "
    hits = O.overused_words(text, FREQ, MORPH, lambda t: t)
    assert [h["lemma"] for h in hits] == ["стек"]
    assert hits[0]["count"] == 12 and hits[0]["corpus_count"] == 0


def test_rare_repeat_in_long_text_is_not_flagged():
    text = FILLER * 200 + "Стек. " * 9
    assert O.overused_words(text, FREQ, MORPH, lambda t: t) == []


# ── повтор между разделами ───────────────────────────────────────────────


def test_same_fact_in_two_sections_is_flagged():
    text = (
        "## План\n\nСамый простой путь к звонарю — портрет звонаря из лобби механизмов.\n\n"
        "## Аксессуары\n\n- **Портрет звонаря** — самый прямой путь к звонарю "
        "в лобби механизмов.\n"
    )
    hits = O.section_repeats(text, MORPH, _masked_with_headings)
    assert [(h["first_line"], h["line"]) for h in hits] == [(3, 7)]
    assert {"портрет", "путь", "лобби"} <= set(hits[0]["shared"])


def test_repeat_inside_one_section_and_different_facts_are_not_flagged():
    same_section = (
        "## План\n\nСамый простой путь к звонарю — портрет звонаря из лобби механизмов.\n"
        "Портрет звонаря — самый прямой путь к звонарю в лобби механизмов.\n"
    )
    assert O.section_repeats(same_section, MORPH, _masked_with_headings) == []
    different = (
        "## План\n\nСамый простой путь к звонарю — портрет звонаря из лобби механизмов.\n\n"
        "## Герои\n\nТорговец песком раскапывает существо седьмого уровня за золото.\n"
    )
    assert O.section_repeats(different, MORPH, _masked_with_headings) == []


# ── запрещённые владельцем слова ─────────────────────────────────────────

CONTEXT = {
    "requirements": [
        {"id": "no-stack", "instruction": "Не используй стек.", "forbidden_literals": ["стек"]}
    ]
}


@pytest.mark.parametrize("form", ["стек", "стека", "Стеком", "стеки", "стеках"])
def test_forbidden_word_matches_every_case_form(form):
    assert publication_context.literal_errors(CONTEXT, f"Растите {form} до финала.")


@pytest.mark.parametrize("word", ["Стеклянный", "стекает", "стекло"])
def test_forbidden_word_does_not_match_other_words(word):
    assert not publication_context.literal_errors(CONTEXT, f"{word} предмет.")


def test_multiword_literal_stays_exact():
    context = {"requirements": [{"id": "x", "instruction": "x", "forbidden_literals": ["по данным"]}]}
    assert publication_context.literal_errors(context, "По данным сайта.")
    assert not publication_context.literal_errors(context, "По данными сайта.")


def test_forbidden_literals_report_line_and_count():
    text = "# Гайд\n\nОснова растет.\n\nВторой [hs_bg id=\"X\"]стек[/hs_bg] и **стеком** тоже.\n"
    assert O.forbidden_literals(CONTEXT, text) == [
        {"requirement": "no-stack", "instruction": "Не используй стек.", "term": "стек",
         "count": 2, "line": 5}
    ]
    assert O.forbidden_literals(CONTEXT, "Чистый текст.") == []


def test_audit_author_context_turns_forbidden_word_into_error(tmp_path, capsys):
    article = tmp_path / "a.md"
    article.write_text("# Гайд\n\nСтек растет до финала.\n", encoding="utf-8")
    ctx = tmp_path / "ctx.json"
    ctx.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile": "battlegrounds-article",
                "style_note": "Синтетический контекст.",
                "requirements": CONTEXT["requirements"],
                "style_examples": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    argv = ["audit", str(article), "--profile", "battlegrounds-article", "--format", "json"]
    assert main(argv + ["--author-context", str(ctx)]) == 1
    report = json.loads(capsys.readouterr().out)
    hit = [f for f in report["findings"] if f["id"] == "owner.forbidden_literal"]
    assert hit and hit[0]["severity"] == "error" and hit[0]["line"] == 3
    assert main(argv) == 0
    capsys.readouterr()


def test_shipped_frequencies_cover_author_corpus():
    freq = O.load_frequencies()
    assert freq["words"] > 1_000_000
    assert "стек" not in freq["nouns"] or freq["nouns"]["стек"] < 5
    assert "звукорегулятор" in freq["game"]
