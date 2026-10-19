"""Regression cases for meaning that survives a superficially tidy edit."""

import common as C
import pytest

from editorteam.server import validate

semantic_diff = C.sibling("semantic_diff")


@pytest.mark.parametrize(
    "before,after,field",
    [
        ("Винрейт колоды ниже 50%.", "Винрейт колоды выше 50%.", "comparison_bound"),
        ("Винрейт колоды не ниже 50%.", "Винрейт колоды не выше 50%.", "comparison_bound"),
        ("Ресурсов должно быть более 5.", "Ресурсов должно быть не менее 5.", "comparison_bound"),
        ("Это лучшая сборка архетипа.", "Это лучшая сборка класса.", "comparison_scope"),
    ],
)
def test_comparison_direction_and_scope_cannot_change_with_same_numbers(before, after, field):
    assert any(item["field"] == field for item in semantic_diff.compare(before, after))


@pytest.mark.parametrize(
    "before,after",
    [
        ("Винрейт колоды ниже 50%.", "Винрейт колоды менее 50%."),
        ("Винрейт колоды не ниже 50%.", "Винрейт колоды не менее 50%."),
        ("Винрейт ниже 50%. Ресурсов больше 5.", "Ресурсов больше 5. Винрейт ниже 50%."),
        ("Выберите класс героя.", "Выберите архетип героя."),
    ],
)
def test_equivalent_comparisons_and_sentence_moves_do_not_trigger_bound_guard(before, after):
    assert not any(
        item["field"].startswith("comparison_") for item in semantic_diff.compare(before, after)
    )


def test_changed_comparison_is_rejected_by_the_editor_gate():
    result = validate(
        "Винрейт колоды ниже 50%.", "Винрейт колоды выше 50%.", "hearthstone", "constructed-guide"
    )
    assert not result["accepted"]
    assert any(item.get("field") == "comparison_bound" for item in result["violations"])


def test_combined_bound_and_threshold_swap_cannot_evade_editor_gate():
    result = validate(
        "Порог ниже 50 ресурсов при запасе 10.",
        "Порог выше 10 ресурсов при запасе 50.",
        "hearthstone",
        "constructed-guide",
    )
    assert not result["accepted"]
    assert any(item.get("field") == "comparison_bound" for item in result["violations"])


@pytest.mark.parametrize(
    "before, after",
    [
        (
            "Бранн удваивает боевой клич Мастера брони.",
            "Бранн не удваивает боевой клич Мастера брони.",
        ),
        ("Не оставляйте Мастера брони против Мага.", "Оставляйте Мастера брони против Мага."),
    ],
)
def test_negation_changes_are_detected_in_both_directions(before, after):
    assert any(item["field"] == "negation" for item in semantic_diff.compare(before, after))


def test_moving_negation_to_a_different_clause_is_not_preservation():
    before = "Бранн не удваивает боевой клич Мастера брони, но повторяет хрип."
    after = "Бранн удваивает боевой клич Мастера брони, но не повторяет хрип."
    assert any(item["field"] == "negation" for item in semantic_diff.compare(before, after))


def test_rhetorical_clause_does_not_hide_a_factual_negation():
    before = "Для статьи: Бранн не удваивает боевой клич Мастера брони."
    after = "Для статьи: Бранн удваивает боевой клич Мастера брони."
    assert any(item["field"] == "negation" for item in semantic_diff.compare(before, after))


def test_same_numbers_cannot_be_swapped_between_facts():
    before = "Мастер брони стоит 3 маны. Боевой якорррь стоит 5 маны."
    after = "Мастер брони стоит 5 маны. Боевой якорррь стоит 3 маны."
    assert any(item["field"] == "number_binding" for item in semantic_diff.compare(before, after))


def test_same_numbers_cannot_exchange_roles_within_a_fact():
    before = "Заклинание стоит 3 маны и наносит 5 урона."
    after = "Заклинание стоит 5 маны и наносит 3 урона."
    assert any(item["field"] == "number_binding" for item in semantic_diff.compare(before, after))


def test_reordering_facts_and_removing_rhetorical_negation_is_allowed():
    before = "Публичную выборку получить не удалось. Мастер брони стоит 3 маны. Боевой якорррь стоит 5 маны."
    after = "Боевой якорррь стоит 5 маны. Мастер брони стоит 3 маны."
    assert semantic_diff.compare(before, after) == []


@pytest.mark.parametrize(
    "after",
    ["Смотрите описание обновления.", "Смотрите [обновление](https://example.org/other)."],
)
def test_deleted_or_replaced_citation_is_rejected_by_the_editor_gate(after):
    before = "Смотрите [обновление](https://example.org/patch)."
    result = validate(before, after, "hearthstone", "constructed-guide")
    assert not result["accepted"]
    assert any(item.get("field") == "links" for item in result["violations"])


def test_equivalent_link_markup_and_merged_repeated_citations_are_allowed():
    before = "[разбор](https://example.org/watch?v=demo&t=120). Ещё [разбор](https://example.org/watch?v=demo&t=120)."
    after = '<a href="https://example.org/watch?v=demo&amp;t=120">Разбор</a>.'
    assert semantic_diff.link_drift(before, after) == []


def test_video_timestamp_and_fragment_are_preserved():
    before = "Источник: https://example.org/video?t=120#turn."
    after = "Источник: https://example.org/video?t=150#turn."
    assert semantic_diff.link_drift(before, after)


def test_parenthesized_url_survives_markdown_to_plain_text():
    before = "[Статья](https://example.org/wiki/Example_(game))."
    after = "Источник: https://example.org/wiki/Example_(game)."
    assert semantic_diff.link_drift(before, after) == []


@pytest.mark.parametrize("wrapper", ["*", "**", "_", "~~"])
def test_emphasized_citation_preserves_exact_destination(wrapper):
    url = "https://example.org/wiki/Example_(game)?t=120#turn"
    after = f"{wrapper}Источник: [разбор]({url}).{wrapper}"
    assert semantic_diff.link_drift(url, after) == []
    result = validate(url, after, "hearthstone", "game-guide")
    assert not any(item.get("field") == "links" for item in result["violations"])
    assert semantic_diff.link_drift(url, after.replace("t=120", "t=150"))


def test_markdown_delimiter_does_not_strip_real_url_asterisk_or_fragment():
    url = "https://example.org/match/*#turn"
    assert semantic_diff.link_drift(url, f"*[разбор]({url}).*") == []
    assert semantic_diff.link_drift(url, "*[разбор](https://example.org/match/#turn).*")
    assert semantic_diff.link_drift(url, "*[разбор](https://example.org/match/*#other).*")


@pytest.mark.parametrize("tail", [".", ",", "?", "]", "}"])
def test_explicit_url_punctuation_is_part_of_the_destination(tail):
    url = "https://example.org/path" + tail
    before = f"[Источник]({url})"
    assert semantic_diff.link_drift(before, "[Источник](https://example.org/path)")
    assert semantic_diff.link_drift(before, f"*[Источник]({url}).*") == []
    assert semantic_diff.link_drift(before, f'<a href="{url}">Источник</a>.') == []
    assert semantic_diff.link_drift(before, f"<{url}>") == []
