"""Calendar dates stay facts when surrounding prose or sentence borders change."""

import common as C
import pytest

from editorteam.server import validate

claims = C.sibling("claims")
MONTHS = "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split()


@pytest.mark.parametrize("month", MONTHS)
@pytest.mark.parametrize("space", [" ", "\u00a0"])
def test_calendar_date_context_survives_splitting_and_merging_sentence(month, space):
    before = f"В наборе 5 карт, он появится 14{space}{month}."
    after = f"В наборе 5 карт. Он появится 14{space}{month}."
    assert claims.fact_numbers(before) == claims.fact_numbers(after)
    assert ("14", f"дата: {month}") in claims.fact_numbers(after)


def test_calendar_date_and_equal_card_number_keep_distinct_contexts():
    before = "Маг получит 14 карт 14 июля."
    after = "Маг получит 14 карт. Набор появится 14 июля."
    assert claims.fact_numbers(before) == claims.fact_numbers(after)
    assert ("14", "Маг") in claims.fact_numbers(after)
    assert ("14", "дата: июля") in claims.fact_numbers(after)


@pytest.mark.parametrize("after", ["Набор скоро появится.", "Набор появится 15 июля.", "Набор появится 14 июня."])
def test_removed_or_changed_calendar_date_stays_a_hard_error(after):
    result = validate("Набор появится 14 июля.", after, "hearthstone", "game-guide", depth="переплавка")
    assert not result["accepted"]
    assert any(v["kind"] == "protected_lost" and v.get("signal") == "числа" for v in result["violations"])


def test_editor_gate_does_not_lose_date_when_its_sentence_loses_card_unit():
    before = "В наборе 5 карт, он появится 14 июля."
    after = "В наборе 5 карт. Он появится 14 июля."
    result = validate(before, after, "hearthstone", "game-guide", depth="переплавка")
    assert not any(v["kind"] == "protected_lost" and v.get("signal") == "числа" for v in result["violations"])


@pytest.mark.parametrize("ending", ["", " г.", " года"])
@pytest.mark.parametrize("space", [" ", "\u00a0"])
def test_calendar_year_keeps_its_date_when_sentence_is_split(ending, space):
    date = f"14{space}июля{space}2026{ending}"
    before = f"Маг получит 4 карты {date}."
    after = f"Маг получит 4 карты. Набор появится {date}."
    assert claims.fact_numbers(before) == claims.fact_numbers(after)
    assert ("2026", "год даты: 14 июля") in claims.fact_numbers(after)


@pytest.mark.parametrize("after", ["Набор появится 14 июля.", "Набор появится 14 июля 2027 года."])
def test_calendar_year_cannot_disappear_or_change(after):
    result = validate("Набор появится 14 июля 2026 года.", after, "hearthstone", "game-guide", depth="переплавка")
    assert any(v["kind"] == "protected_lost" and v.get("signal") == "числа" for v in result["violations"])


def test_equal_calendar_day_cannot_hide_a_changed_class_card_count():
    before = "Маг получит 14 карт 14 июля."
    after = "Маг получит 13 карт 14 июля."
    assert ("14", "Маг") in claims.fact_numbers(before) - claims.fact_numbers(after)


@pytest.mark.parametrize("span", ["14–16", "14-16", "с 14 по 16", "с 14 до 16", "14-го–16-го"])
def test_date_range_preserves_both_endpoints_and_their_roles(span):
    facts = claims.fact_numbers(f"Событие пройдёт {span} июля 2026 года.")
    assert ("14", "начало диапазона дат: июля") in facts
    assert ("16", "конец диапазона дат: июля") in facts
    assert ("2026", "год даты: 14–16 июля") in facts


@pytest.mark.parametrize("after", ["Событие пройдёт 13–16 июля.", "Событие пройдёт 16 июля.", "Событие пройдёт 16–14 июля."])
def test_date_range_start_cannot_change_disappear_or_exchange_roles(after):
    result = validate("Событие пройдёт с 14 по 16 июля.", after, "hearthstone", "game-guide", depth="переплавка")
    assert any(v["kind"] == "protected_lost" and v.get("signal") == "числа" for v in result["violations"])


def test_ordinal_calendar_day_keeps_its_factual_date():
    assert claims.fact_numbers("Релиз 14-го июля.") == claims.fact_numbers("Релиз 14 июля.")


def test_reader_date_is_not_discarded_merely_because_it_describes_a_snapshot():
    assert ("14", "дата: июля") in claims.fact_numbers("По срезу от 14 июля Маг получил 4 карты.")
