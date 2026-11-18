"""Живой язык автора: ИИ-склейки, хеджи, кальки, заголовки и пересказ связки карт.

Фрагменты — из старой версии тир-листа 1-х дропов Полей сражений (17.11.2026)
и правок редактора. Каждая проверка проверяется и на корректном тексте: она
не должна ругаться на то, как пишет автор.
"""

from __future__ import annotations

from collections import Counter

import common as C
import markers
import pytest
import rewrite_gate

from editorteam import bg_mechanics_gate, cli, profiles, rules
from editorteam import card_paraphrase as P
from editorteam import owner_checks as O
from editorteam.cli import _prose_lines, owner_findings

cards = C.sibling("cards")
TIER = profiles.load("battlegrounds-tierlist")


def marker_ids(text: str, profile=TIER) -> list[str]:
    hits = markers.scan(text, markers.load_patterns())
    return [h["id"] for h in rules.filter_marker_hits(hits, text, profile)]


def ids(hits: list[dict]) -> list[str]:
    return [h["id"] for h in hits]


def cherez(text: str) -> list[dict]:
    return [f for f in bg_mechanics_gate.check_bg_mechanics(text) if f["id"] == "bg.archetype_cherez"]


# ── ИИ-склейки, хеджи и объяснение правил (markers.json) ─────────────────

BRIDGE = (
    "На первый взгляд Выживший красный дракон, Вертлявый разведчик и Дюнный силач "
    "дают одно и то же — ровные характеристики 3/3. Но дальше у них разная судьба."
)


def test_essay_bridge_between_cards_is_flagged():
    assert marker_ids(BRIDGE).count("ai-essay-bridge") == 2


@pytest.mark.parametrize(
    "phrase",
    [
        "У Трескучего циклона, Клыкастого походника и Заклинателя гнева другая проблема.",
        "Музыкант Южных Морей и Зоатроид берут не дракой в первом раунде, а экономикой.",
        "Приятный бонус — в сильной сборке Мурлоков Стрелок полезен и позже.",
        "Правда, платить за это приходится потерянным здоровьем.",
    ],
)
def test_other_essay_bridges_are_flagged(phrase):
    assert "ai-essay-bridge" in marker_ids(phrase)


def test_bridge_spans_long_shortcodes_inside_one_sentence():
    text = (
        'На первый взгляд [hs_bg id="BG35_814"]Выживший красный дракон[/hs_bg], '
        '[hs_bg id="BG32_330"]Вертлявый разведчик[/hs_bg] и [hs_bg id="BG31_815"]Дюнный '
        "силач[/hs_bg] дают одно и то же."
    )
    assert "ai-essay-bridge" in marker_ids(text)


def test_plain_card_entries_are_not_bridges():
    text = (
        "Выживший красный дракон — берите на 1-м ходу и баффайте до 6 атаки.\n\n"
        "Дюнный силач — сразу даёт +1/+1 будущим элементалям в таверне."
    )
    assert "ai-essay-bridge" not in marker_ids(text)


def test_series_of_hedges_is_flagged():
    text = (
        "Позже по игре Вертлявого разведчика нередко оставляют в руке под прокрутку карт.\n\n"
        "В сильной сборке Мурлоков Пузырьковый стрелок бывает полезен и в середине игры."
    )
    assert marker_ids(text).count("directive-hedge") == 2


def test_single_hedge_in_long_text_is_author_norm():
    filler = "Берите существо на 1-м ходу и продавайте его на 3-м, когда придёт тир-2. " * 60
    text = filler + "\n\nТехнические карты порой берут против агрессии.\n"
    assert "directive-hedge" not in marker_ids(text)


@pytest.mark.parametrize(
    "phrase",
    [
        "Это карта для Механизмов, а Магнетизм на 1-м ходу применить не к кому.",
        "Усиление выгоднее отдавать существам, у которых щит уже есть.",
    ],
)
def test_explaining_basic_rules_is_flagged(phrase):
    assert "tautology-mechanic" in marker_ids(phrase)


# ── Карточки тира и сигнал однообразных начал ────────────────────────────

ENTRY = "**{name}** — {verdict}"
TIER_NAMES = [
    "Подозрительный надзиратель", "Бликостраж", "Золотой призер", "Иглошкур-геомант",
    "Выживший красный дракон", "Вертлявый разведчик", "Порхающий нетопырь", "Дюнный силач",
    "Пузырьковый стрелок", "Трескучий циклон", "Клыкастый походник",
]


def tier_cards(verdict: str = "берите на 1-м ходу, продавайте на 3-м.") -> str:
    entries = "\n\n".join(ENTRY.format(name=n, verdict=verdict) for n in TIER_NAMES)
    return "## Лучшие тир-1 существа\n\n" + entries + "\n"


def test_tierlist_card_entries_do_not_trigger_paragraph_starts():
    assert "battlegrounds-tierlist" not in cli.OPENING_PROFILES
    assert "battlegrounds-tierlist" in cli.BG_PROFILES
    text = tier_cards()
    assert len(O.paragraph_openings(text)) == 1  # схема та же, что ловится в гайдах
    assert "owner.paragraph_starts" not in ids(owner_findings(text, "battlegrounds-tierlist"))
    assert "owner.paragraph_starts" in ids(owner_findings(text, "battlegrounds-guide"))


def test_bold_card_entry_is_not_bold_spam_in_tierlist():
    text = "\n".join(
        ENTRY.format(name=n, verdict="**всегда** на 1-м ходу." if i == 1 else "на 1-м ходу.")
        for i, n in enumerate(TIER_NAMES[:4])
    )
    raw = [h["id"] for h in markers.scan(text, markers.load_patterns())]
    assert raw.count("bold-spam") == 5
    assert "bold-spam" not in marker_ids(text)
    assert "bold-spam" in marker_ids(text, profiles.load("battlegrounds-guide"))


def test_card_entry_with_two_accents_is_still_bold_spam():
    text = "**Подозрительный надзиратель** — **всегда** берите, **сразу** баффайте.\n"
    assert marker_ids(text).count("bold-spam") == 3


def test_shortcode_card_entry_in_list_is_not_label_list():
    text = (
        '- **[hs_bg id="BG36_345"]Подозрительный надзиратель[/hs_bg]** — 3/3 на старте.\n'
        '- **[hs_bg id="BG29_888"]Бликостраж[/hs_bg]** — держит два боя.\n'
    )
    assert set(marker_ids(text)) & {"bold-spam", "bold-label-list"} == set()


def test_label_with_dash_that_is_not_a_card_stays_label_list():
    text = "- **Плюс** — быстрый старт\n- **Итог** — брать\n"
    assert "bold-label-list" in marker_ids(text)


# ── «через» о типе существ (bg_mechanics_gate) ───────────────────────────


@pytest.mark.parametrize(
    "phrase",
    [
        "Это хороший задел, если лобби поведёт вас в Элементалей через Живого азерита.",
        "Свинобразы через самоцветы — сильнейшая сборка патча.",
        "А если игра пойдёт через Свинобразов, Геомант поможет запустить самоцветы.",
    ],
)
def test_archetype_cherez_is_error(phrase):
    found = cherez(phrase)
    assert [f["severity"] for f in found] == ["error"]
    assert "«с»" in found[0]["message"] or "«на»" in found[0]["message"]


@pytest.mark.parametrize(
    "phrase",
    [
        "Элементали с Живым азеритом держат лейтгейм.",
        "Свинобразы на самоцветах — сильнейшая сборка патча.",
        "Если лобби поведёт в Свинобразов, Геомант поможет с самоцветами.",
        "Разыграйте Сторожевого механизма через Монетку на 1-м ходу.",
        "Редактор правил «Элементали через Живого азерита» на «с Живым азеритом».",
    ],
)
def test_natural_forms_and_card_names_are_fine(phrase):
    assert cherez(phrase) == []


def test_archetype_cherez_ignores_type_inside_card_shortcode():
    text = '[hs_bg id="X1"]Сторожевого механизма[/hs_bg] через Монетку играют на 1-м ходу.'
    assert cherez(text) == []


# ── Язык автора (owner_checks) ───────────────────────────────────────────


def test_mixed_vy_and_ty_is_one_error():
    text = "Вы берёте Надзирателя на 1-м ходу.\n\nПотом ты продаёшь его, а ваше золото уходит в таверну."
    hits = O.pronoun_mix(text)
    assert [(h["id"], h["severity"], h["evidence"], h["line"]) for h in hits] == [
        ("owner.pronoun_mix", "error", "ты", 3)
    ]
    assert hits[0]["meta"] == {"vy": 2, "ty": 1}


@pytest.mark.parametrize(
    "text",
    [
        "Вы берёте Надзирателя на 1-м ходу, а ваше золото уходит в таверну.",
        "Вы берёте карту «Ты не пройдёшь» только ради шутки.",
        'Вы разыгрываете [hs_card id="X"]Тебе не уйти[/hs_card] на 5-м ходу.',
        "Что с тобой стало, Разношерстная фаланга? Вы её больше не берёте.",
    ],
)
def test_one_address_quotes_and_card_names_are_fine(text):
    assert O.pronoun_mix(text) == []


def test_trailing_dot_and_title_case_in_headings():
    text = "# Лучшие Тир-1 Существа На Первый Ход\n\n## Как играть на 1-м ходу.\n\nТекст.\n"
    hits = O.heading_issues(text)
    assert [(h["line"], h["severity"], h["meta"]["issue"]) for h in hits] == [
        (1, "error", "title_case"),
        (3, "error", "trailing_dot"),
    ]


def test_long_heading_and_soft_hyphen_are_review():
    soft = chr(0xAD)
    text = (
        "# Лучшие и худшие тир-1 существа для первого хода в новом сезоне Полей сражений\n\n"
        f"## Под{soft}робный разбор\n"
    )
    issues = [(h["line"], h["severity"], h["meta"]["issue"]) for h in O.heading_issues(text)]
    assert issues == [(1, "review", "too_long"), (3, "review", "soft_hyphen")]


@pytest.mark.parametrize(
    "heading",
    [
        "## Лучшие тир-1 существа на первый ход",
        "## Музыкант Южных Морей",
        "## 5. Барон Ривендер + Самоотверженная героиня",
        "## Колода Элем Биг Спелл Друид от Steelo",
        "## Хэндбафф ДК от Sintolol — топ-1 Легенды",
        "## Что дальше...",
    ],
)
def test_sentence_case_card_names_and_deck_names_are_fine(heading):
    assert O.heading_issues(heading + "\n") == []


def test_guide_na_is_error():
    hits = O.guide_preposition("Читайте также наш гайд на Мурлок Шамана и гайды на героев.")
    assert [(h["severity"], h["evidence"]) for h in hits] == [
        ("error", "гайд на Мурлок"),
        ("error", "гайды на героев"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Читайте наш гайд по Мурлок Шаману.",
        "Гайд на сайте обновлён, есть гайд на русском и гайд на YouTube.",
        "Поисковый запрос «гайд на мурлок шамана» оставляем в SEO.",
    ],
)
def test_guide_po_and_place_or_language_are_fine(text):
    assert O.guide_preposition(text) == []


def test_lowercase_wild_mode_is_review():
    hits = O.wild_mode_case("Колода играет в вольном, а мета вольного медленнее. Для вольного — ок.")
    assert [(h["severity"], h["evidence"]) for h in hits] == [
        ("review", "в вольном"),
        ("review", "мета вольного"),
        ("review", "Для вольного"),
    ]


@pytest.mark.parametrize(
    "text",
    ["Колода играет в Вольном формате.", "Пересказ в вольном переводе.", "Мета Вольного медленнее."],
)
def test_capitalized_wild_and_free_translation_are_fine(text):
    assert O.wild_mode_case(text) == []


def test_alias_before_full_name_is_review():
    text = (
        "Геомант хорош на первом ходу.\n\n"
        "## Лучшие\n\n"
        "**Иглошкур-геомант** — берите на 1-м ходу и отдавайте оба самоцвета.\n"
    )
    hits = O.premature_card_alias(text)
    assert [(h["id"], h["severity"], h["evidence"], h["line"]) for h in hits] == [
        ("owner.premature_card_alias", "review", "Геомант", 1)
    ]
    assert hits[0]["meta"]["first_full_line"] == 5


def test_shortcode_alias_before_full_shortcode_is_review():
    text = (
        'Усиление от [hs_bg id="BG36_345"]Надзирателя[/hs_bg] ложится на щит.\n\n'
        'Главный дроп — [hs_bg id="BG36_345"]Подозрительный надзиратель[/hs_bg].\n'
    )
    hits = O.premature_card_alias(text)
    assert [(h["evidence"], h["meta"]["card"]) for h in hits] == [
        ("Надзирателя", "Подозрительный надзиратель")
    ]


def test_full_name_first_then_alias_and_type_words_are_fine():
    text = (
        "## Лучшие\n\n"
        "- **Выживший красный дракон**\n"
        "- **Подозрительный надзиратель**\n\n"
        "Драконы в этом патче слабые. Надзиратель даёт +3/+3 на 3-м ходу.\n"
    )
    assert O.premature_card_alias(text) == []


def test_inflected_full_names_and_build_labels_are_not_aliases():
    text = (
        '**Свинобразы через Свиногонщика**\n\n'
        'До поздних столов доходит [hs_bg id="BG31_149"]Пузырьковый стрелок[/hs_bg].\n\n'
        'С [hs_bg id="BG31_149"]Пузырьковым стрелком[/hs_bg] решает удача; '
        '[hs_bg id="BG31_149"]Стрелок[/hs_bg] полезен и позже.\n\n'
        '[hs_bg id="X9"]День самоцветов[/hs_bg] после [hs_bg id="X9"]Дня самоцветов[/hs_bg].\n\n'
        "Портрет преобразователя ниже.\n\n"
        '[hs_bg id="X7"]Портрет преобразователя[/hs_bg] — аксессуар.\n'
    )
    assert O.premature_card_alias(text) == []


def test_voice_checks_reach_audit_for_every_profile():
    text = "## Как играть.\n\nВы берёте карту, а ты нет. Это гайд на Мурлоков в вольном.\n"
    found = {f["id"] for f in owner_findings(text, "news")}
    assert {"owner.heading_style", "owner.pronoun_mix", "owner.guide_preposition",
            "owner.wild_capitalization"} <= found
    clean = "## Как играть\n\nВы берёте карту на 1-м ходу. Это гайд по Мурлокам в Вольном.\n"
    assert owner_findings(clean, "news") == []


# ── Пересказ связки двух карт (card_paraphrase) ──────────────────────────

BAT = "Боевой раж: призывает зверя 1/1."
FISH = (
    "Активация (2): выберите карту в таверне, чтобы заменить ее на наживку. "
    "Ваш крайний левый зверь атакует ее."
)
BAIT = "Не может получать характеристики. Предсмертный хрип: уничтожившее наживку существо получает +5/+5."
BG = {
    "BGX_BAT": {"n": "Порхающий нетопырь", "t": [BAT]},
    "BGX_FISH": {"n": "Затаившаяся лев-рыба", "t": [FISH]},
    "BGX_FISHt": {"n": "Наживка", "t": [BAIT]},
}


@pytest.fixture(scope="module")
def lex():
    texts = P.bg_texts_by_name(BG)
    idx = cards.Index(list(texts), C.morph())
    return P.Lexicon(idx, texts, Counter(), cards.NOT_CARDS)


def test_linked_tokens_follow_dossier_rules():
    tokens = P.linked_tokens(BG)
    # токен по ID-префиксу и наживка по правилу досье (её текст — из BUILTIN_TOKENS)
    [(name, texts)] = tokens["Затаившаяся лев-рыба"]
    assert name == "Наживка" and BAIT in texts and any("+10/+10" in t for t in texts)
    assert "Порхающий нетопырь" not in tokens


RETELL = (
    "## Связка\n\n"
    "Крайний левый Порхающий нетопырь атакует наживку Затаившейся лев-рыбы, получает "
    "+5/+5 от ее Предсмертного хрипа и Боевым ражем призывает зверя 1/1.\n"
)


def test_two_card_retelling_is_flagged_by_union_of_texts(lex):
    tokens = P.linked_tokens(BG)
    hits = P.retellings(RETELL, lex, _prose_lines, tokens=tokens)
    assert [(h["card"], h["line"]) for h in hits] == [
        ("Порхающий нетопырь + Затаившаяся лев-рыба", 3)
    ]
    assert hits[0]["cards"] == ["Порхающий нетопырь", "Затаившаяся лев-рыба"]
    # по одной карте фраза не пересказ (своих слов слишком много): ловит только объединённый текст
    sentence = P.split_sentences(RETELL, lex, _prose_lines)[0][0]
    for card in hits[0]["cards"]:
        cover, novelty, _ = P.paraphrase_score(sentence, card, lex)
        assert cover < P.RETELL_COVER_MIN or novelty > P.RETELL_NOVELTY_MAX


def test_two_card_sentence_with_condition_and_reason_is_advice(lex):
    text = (
        "Берите Порхающего нетопыря, если на 3-м ходу видите Затаившуюся лев-рыбу: "
        "наживка даёт +5/+5, потому что нетопырь атакует первым.\n"
    )
    assert P.retellings(text, lex, _prose_lines, tokens=P.linked_tokens(BG)) == []


def test_owner_findings_report_two_card_retelling(monkeypatch, lex):
    monkeypatch.setattr(cli, "_bg_card_lexicon", lambda: (lex, BG))
    found = [f for f in owner_findings(RETELL, "battlegrounds-tierlist")
             if f["id"] == "card_paraphrase.retelling"]
    assert len(found) == 1 and found[0]["message"].startswith("пересказ связки карт")
    assert found[0]["meta"]["cards"] == ["Порхающий нетопырь", "Затаившаяся лев-рыба"]


# ── Термины редактора (terminology.yaml) ─────────────────────────────────


def test_editor_terms_are_valid_and_slang_is_caught():
    assert rules.validate() == []
    by_id = {r.id: r for r in rules.terminology()}
    for rule_id in ("term.milling", "term.win_condition", "term.raskrut",
                    "term.scale_bg", "term.concentrate", "term.naschet"):
        assert rule_id in by_id
    assert by_id["term.win_condition"].replacement_for("вин-кондишн") == "способ победы"
    assert by_id["term.concentrate"].replacement_for("сконцентрироваться") is None
    text = "Его вин-кондишн — раскрут колоды. Раскрутку и раскрутить не трогаем."
    found = sorted((h["rule"], h["found"]) for h in rewrite_gate.terminology_hits(text)
                   if h["rule"] in ("term.win_condition", "term.raskrut"))
    assert found == [("term.raskrut", "раскрут"), ("term.win_condition", "вин-кондишн")]


# ── Частотный AI-слоп (slop_calibrate + owner.slop_frequency) ────────────


def test_slop_calibrate_filters_human_split_noise_and_keeps_true_slop():
    from editorteam import slop_calibrate

    # В половине human_docs (_split_bit == 0) часто мелькает «осада» (разница тем),
    # тогда как в AI стабильно лезут «автоматически» и «не доказывать».
    half_zero = [f"hz-{i}" for i in range(60) if slop_calibrate._split_bit(f"hz-{i}") == 0][:6]
    half_one = [f"ho-{i}" for i in range(60) if slop_calibrate._split_bit(f"ho-{i}") == 1][:6]
    human_docs = [
        (did, "осада враг башня темп карта " * 40) for did in half_zero
    ] + [
        (did, "обычный ход темп размен стол карта " * 40) for did in half_one
    ]
    ai_docs = [
        (
            f"a-{i}",
            f"fam-{i}",
            "осада враг башня темп карта. " * 20
            + "Он автоматически улучшает темп. Этот выбор автоматически решает, "
            "и один эффект не доказывает победу. Автоматически и не доказывает.\n" * 6,
        )
        for i in range(6)
    ]
    slop = slop_calibrate.calibrate_slop(
        human_docs,
        ai_docs,
        game_texts=[],
        morph=C.morph(),
        min_uni_count=5,
        min_ngram_count=4,
    )
    assert "автоматически" in slop["unigrams"]
    assert "не доказывать" in slop["ngrams"]
    assert "осада" not in slop["unigrams"]
    assert slop["dropped_by_human_split"]["unigrams"] >= 0


def test_slop_frequency_flags_repeated_slop_and_stays_silent_on_clean_prose():
    slop = {
        "unigrams": {
            "заранее": {"ai_per_1k": 0.9, "human_per_1k": 0.02, "ratio": 25.0, "score": 9.5},
        },
        "ngrams": {
            "не гарантировать": {"ai_per_1k": 0.4, "human_per_1k": 0.01, "ratio": 20.0, "score": 8.0},
        },
    }
    sloppy_text = (
        "## План\n\n"
        "Заранее подготовьте стол. Заранее держите копию, заранее считайте урон и заранее ищите ответ.\n"
        "Это не гарантирует победу на 5-м ходу и не гарантирует топ-1.\n"
    )
    hits = O.slop_frequency(sloppy_text, slop, C.morph(), _prose_lines)
    terms = {h["term"] for h in hits}
    assert {"не гарантировать", "заранее"} <= terms
    clean_text = (
        "## План\n\n"
        "Заранее проверьте заходы противника, чтобы не отдать лишнее здоровье на третьем ходу.\n"
        + ("Ставьте сильнейших существ на край стола и держите экономику. " * 25)
    )
    assert O.slop_frequency(clean_text, slop, C.morph(), _prose_lines) == []


def test_owner_findings_include_slop_frequency_when_slop_matches(monkeypatch):
    fake_slop = {
        "unigrams": {
            "обещание": {"ai_per_1k": 0.5, "human_per_1k": 0.0, "ratio": 40.0, "score": 11.0},
        },
        "ngrams": {},
    }
    monkeypatch.setattr(O, "load_slop_frequencies", lambda: fake_slop)
    text = "## Введение\n\nПустое обещание победы — обещание без расчёта; очередное обещание и ещё обещание.\n"
    found = [f for f in owner_findings(text, "news") if f["id"] == "owner.slop_frequency"]
    assert len(found) == 1
    assert found[0]["severity"] == "review"
    assert found[0]["meta"]["term"] == "обещание"
