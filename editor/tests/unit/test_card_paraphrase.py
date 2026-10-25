"""Механический текст про карты: пересказ, упоминание без совета, инсайт."""

import json
from collections import Counter

import common as C
import pytest

from editorteam import card_paraphrase as P
from editorteam.cli import _prose_lines, main

cards = C.sibling("cards")

TEXTS = {
    "Огненный шар": ["Наносит 6 ед. урона."],
    "Служитель боли": ["Когда это существо получает урон, вы берете карту."],
    "Главный канонир": [
        "Боевой клич: вы получаете канонира 1/1, наносящего 1 ед. урона "
        "случайному противнику в конце хода."
    ],
    "Мастер клинка Самуро": [
        "Натиск. Бешенство: наносит урон, равный атаке этого существа, всем существам противника."
    ],
    "Подготовка": ["Ваше следующее заклинание на этом ходу стоит на (2) меньше."],
    "Зефрис Великий": [
        "Боевой клич: если в вашей колоде нет одинаковых карт, пожелайте себе идеальную карту."
    ],
    "Нечетные не в почете": ["Ваша сила героя улучшается."],
    "Разбойник Зловещей Чешуи": ["Боевой клич: раскопайте карту."],
    "Солнцементаль Запределья": ["Боевой клич: наносит 2 ед. урона."],
    "Йети Морозного Кряжа": [],
}


@pytest.fixture(scope="module")
def lex():
    idx = cards.Index(list(TEXTS), C.morph())
    # «подготовка» — обычное слово корпуса: в начале фразы это не карта
    return P.Lexicon(idx, TEXTS, Counter({"подготовка": 12}), cards.NOT_CARDS)


def run(text, lex):
    return P.analyze(text, lex, _prose_lines, "t.md")


def mentioned(text, lex):
    return [
        (m.card, m.surface)
        for sents in P.split_sentences(text, lex, lambda t: t)
        for s in sents
        for m in s.mentions
    ]


# ── пересказ ─────────────────────────────────────────────────────────────


def test_restated_effect_is_paraphrase(lex):
    r = run(
        "Огненный шар наносит 6 урона. Служитель боли — когда это существо "
        "получает урон, вы берёте карту.",
        lex,
    )
    assert [p["card"] for p in r["paraphrases"]] == ["Огненный шар", "Служитель боли"]
    assert r["metrics"]["paraphrase_rate"] == 1.0
    assert r["verdicts"]["paraphrase_rate"] is False
    assert r["paraphrases"][0]["card_text"] == "Наносит 6 ед. урона."


def test_paraphrase_with_wrapper_verbs_still_counts(lex):
    r = run(
        "Главный канонир при розыгрыше даёт канонира 1/1, который в конце хода "
        "наносит 1 урон случайному противнику.",
        lex,
    )
    assert [p["card"] for p in r["paraphrases"]] == ["Главный канонир"]


def test_effect_plus_decision_is_not_paraphrase(lex):
    r = run("Огненный шар наносит 6 урона, поэтому держите его для добивания героя.", lex)
    assert r["paraphrases"] == []
    assert r["bare_mentions"] == []


def test_own_content_is_not_paraphrase(lex):
    r = run(
        "Огненный шар наносит 6 урона, и этого хватает на большинство "
        "дорогих существ Жреца в текущей мете.",
        lex,
    )
    assert r["paraphrases"] == []


def test_card_text_condition_does_not_make_advice(lex):
    # «если» из текста карты не делает пересказ советом
    r = run(
        "Зефрис Великий: если в колоде нет одинаковых карт, вы желаете себе идеальную карту.", lex
    )
    assert [p["card"] for p in r["paraphrases"]] == ["Зефрис Великий"]
    assert r["bare_mentions"]


def test_vanilla_card_has_nothing_to_paraphrase(lex):
    r = run("Мы снова взяли Йети Морозного Кряжа в колоду.", lex)
    assert r["paraphrases"] == []
    assert r["metrics"]["mentions"] == 1


# ── тест упоминания ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sentence, kind",
    [
        ("Разыгрывайте Огненный шар на шестом ходу по самому опасному существу.", "when"),
        ("Огненный шар особенно хорош против агро колод Охотника.", "against"),
        ("В агро матч-апах Огненный шар ценнее любой дорогой карты.", "against"),
        ("Придержите Огненный шар для финального удара по герою.", "hold"),
        ("Без Огненного шара его роль в колоде выполнит Ледяная стрела вместо него.", "replace"),
        ("Взяли Огненный шар, а не вторую Ледяную стрелу из бюджета.", "replace"),
        ("Частая ошибка — тратить Огненный шар на мелкое существо в начале игры.", "mistake"),
        ("Не тратьте Огненный шар на мелочь из второй руки противника.", "mistake"),
    ],
)
def test_mention_with_advice_is_not_bare(lex, sentence, kind):
    s = P.split_sentences(sentence, lex, lambda t: t)[0][0]
    assert kind in P.context_kinds(P._own(s), lex, P._cards_lemmas(s, lex))
    assert run(sentence, lex)["bare_mentions"] == []


def test_bare_mention_is_flagged_with_quote(lex):
    r = run("В колоде есть Огненный шар и пара других заклинаний урона.", lex)
    assert r["bare_mentions"] == [
        {
            "line": 1,
            "card": "Огненный шар",
            "form": "Огненный шар",
            "quote": "В колоде есть Огненный шар и пара других заклинаний урона.",
        }
    ]
    assert r["metrics"]["bare_mention_rate"] == 1.0


def test_advice_in_neighbour_sentence_covers_mention(lex):
    text = (
        "В колоде есть Огненный шар и пара других заклинаний урона. "
        "Держите их до конца игры, чтобы добить героя."
    )
    assert run(text, lex)["bare_mentions"] == []


def test_advice_in_other_paragraph_does_not_cover_mention(lex):
    text = (
        "В колоде есть Огненный шар и пара других заклинаний урона.\n\n"
        "Держите их до конца игры, чтобы добить героя."
    )
    assert len(run(text, lex)["bare_mentions"]) == 1


# ── склонения и распознавание названий ───────────────────────────────────


def test_inflected_full_names(lex):
    found = mentioned(
        "Разменяйте Главного канонира с Мастером клинка Самуро, потом добейте Огненным шаром.", lex
    )
    assert found == [
        ("Главный канонир", "Главного канонира"),
        ("Мастер клинка Самуро", "Мастером клинка Самуро"),
        ("Огненный шар", "Огненным шаром"),
    ]


def test_short_personal_name(lex):
    assert mentioned("Сначала выставьте Самуро, потом разменяйтесь.", lex) == [
        ("Мастер клинка Самуро", "Самуро")
    ]


def test_place_in_genitive_is_not_a_short_name(lex):
    assert mentioned("Это было ещё до выхода Запределья в Стандарт.", lex) == []


def test_class_and_archetype_words_are_not_cards(lex):
    text = "Играя Разбойником, против Нечетного Паладина тяжело."
    assert mentioned(text, lex) == []


def test_sentence_initial_common_word_needs_mid_sentence_proof(lex):
    assert mentioned("Подготовка к турниру заняла неделю.", lex) == []
    text = "Подготовка удешевляет следующее заклинание. Без Подготовки комбо не собрать."
    assert [c for c, _ in mentioned(text, lex)] == ["Подготовка", "Подготовка"]


# ── плотность инсайта ────────────────────────────────────────────────────


def test_insight_needs_condition_decision_and_reason(lex):
    r = run(
        "Если у противника нет стола, разыгрывайте Подготовку с дорогим заклинанием, "
        "чтобы сэкономить ход. Подготовка — просто хорошая карта для темпа. Разыгрывайте её почаще.",
        lex,
    )
    assert r["metrics"]["prose_sentences"] == 3
    assert r["metrics"]["insight_density"] == round(1 / 3, 3)


def test_reason_may_open_the_next_sentence(lex):
    r = run(
        "Против агро держите Главного канонира до третьего хода. Иначе канонир умрёт без пользы.",
        lex,
    )
    assert r["metrics"]["insight_density"] == 0.5


def test_noun_with_imperative_homonym_is_not_decision(lex):
    s = P.split_sentences("Когда приходит этап боли, нужен план.", lex, lambda t: t)[0][0]
    assert not any(s.impr)


# ── markdown и пограничные случаи ────────────────────────────────────────


def test_markdown_noise_is_ignored_and_lines_are_real(lex):
    text = (
        "---\ntitle: x\n---\n"
        "# Огненный шар наносит 6 урона\n\n"
        "| Огненный шар | наносит 6 урона |\n|---|---|\n\n"
        "```\nОгненный шар наносит 6 урона.\n```\n\n"
        "> Огненный шар наносит 6 урона.\n\n"
        "- 2 × Огненный шар\n"
        "- **Огненный шар** наносит 6 урона.\n\n"
        '[hs_card id="1"]Огненный шар[/hs_card] наносит 6 урона.\n'
    )
    r = run(text, lex)
    assert [p["line"] for p in r["paraphrases"]] == [16, 18]
    assert r["metrics"]["prose_sentences"] == 2


def test_document_without_cards(lex):
    r = run("Мета стала медленнее. Колоды стали жаднее, и это видно по рангам.", lex)
    assert r["metrics"]["mentions"] == 0
    assert r["metrics"]["paraphrase_rate"] is None
    assert r["verdicts"]["paraphrase_rate"] is None
    assert run("", lex)["metrics"]["insight_density"] is None


# ── снимок текстов, калибровка, CLI ──────────────────────────────────────


def test_build_texts_keeps_collectible_and_battlegrounds_cards():
    raw = [
        {
            "name": "А",
            "collectible": True,
            "text": "[x]<b>Боевой клич:</b> наносит $2 ед.\nурона.@ <i>(Еще {0}!)</i>",
        },
        {"name": "А", "collectible": True, "text": "<b>Рывок</b>"},
        {
            "name": "Б",
            "set": "BATTLEGROUNDS",
            "type": "MINION",
            "techLevel": 2,
            "text": "Провокация.",
        },
        {"name": "В", "set": "BATTLEGROUNDS", "type": "ENCHANTMENT", "text": "+1/+1."},
        {"name": "Г", "set": "CORE", "type": "SPELL", "text": "Не коллекционная."},
        {"name": "Д", "collectible": True},
    ]
    assert P.build_texts(raw) == {
        "А": ["Боевой клич: наносит 2 ед. урона.", "Рывок"],
        "Б": ["Провокация."],
        "Д": [],
    }


def test_update_texts_writes_snapshot(tmp_path):
    out = tmp_path / "texts.json"
    raw = [{"name": "А", "collectible": True, "text": "<b>Рывок</b>"}]
    assert P.update_texts(lambda url: raw, out, taken="2026-10-25") == 1
    assert P.load_texts(out) == {"А": ["Рывок"]}
    with pytest.raises(FileNotFoundError):
        P.load_texts(tmp_path / "нет.json")


def test_percentiles_use_observed_values():
    vals = [0.0] * 9 + [0.5]
    assert P.percentiles(vals, (50, 90, 100)) == {"p50": 0.0, "p90": 0.0, "p100": 0.5}
    assert P.percentiles([]) == {}


def test_shipped_texts_snapshot_has_known_cards():
    texts = P.load_texts()
    assert texts["Огненный шар"] == ["Наносит 6 ед. урона."]
    assert len(texts) > 5000


def test_cli_json_and_check(tmp_path, capsys):
    f = tmp_path / "g.md"
    f.write_text("# Гайд\n\nОгненный шар наносит 6 урона.\n", encoding="utf-8")
    assert main(["card-paraphrase", str(f), "--format", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert set(report) == {
        "document",
        "metrics",
        "thresholds",
        "verdicts",
        "paraphrases",
        "bare_mentions",
    }
    assert report["paraphrases"][0]["line"] == 3
    assert main(["card-paraphrase", str(f), "--check"]) == 1
    out = capsys.readouterr().out
    assert "ПЕРЕСКАЗ ЭФФЕКТА" in out and "ВНЕ НОРМЫ" in out


def test_cli_needs_input(tmp_path, capsys):
    assert main(["card-paraphrase"]) == 2
    assert main(["card-paraphrase", "--calibrate", str(tmp_path / "нет")]) == 2
