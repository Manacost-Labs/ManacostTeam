"""Regression cases for meaning that survives a superficially tidy edit."""

import common as C
import pytest

from editorteam.server import validate

semantic_diff = C.sibling("semantic_diff")


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
