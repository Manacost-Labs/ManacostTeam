"""Отрицания исходника делятся на факты, контраст и риторику.

Обязательными для переплавки остаются только факты. Иначе покрытие тащит в
статью оговорки исходника («не претендует», «не забыть», «нельзя подтвержденно
объявить»), а именно они выдают текст, написанный по шаблону отчёта.
"""

import common as C
import pytest

claims = C.sibling("claims")
semantic_diff = C.sibling("semantic_diff")


@pytest.mark.parametrize(
    "sentence, expected",
    [
        ("Бранн не удваивает активацию Беглеца из стоков, потому что это не боевой клич.", "fact"),
        ("Не оставляйте Мастера брони против Мага.", "fact"),
        ("Заклинание Импровизирующего хозяина больше нельзя применять к божествам.", "fact"),
        ("Тит повторяет хрип, но не заменяет выбранные цели.", "fact"),
        ("Таинственный к'тир выбирает крайние левые заклинания, а не любые три карты.", "contrast"),
        ("В такой партии ценность имеет не просто количество демонов, а полный набор.", "contrast"),
        ("Она не претендует на перечисление каждой возможной комбинации.", "rhetorical"),
        ("Публичной выборки получить не удалось.", "rhetorical"),
        (
            "Не забыть более ранние изменения 22 сентября: Вольная буря требует четырех элементалей.",
            "rhetorical",
        ),
        ("Нельзя подтвержденно объявить свинобразов новой лучшей расой.", "rhetorical"),
        (
            "Для статьи корректнее описать мнение, а не утверждать, что так считают все.",
            "rhetorical",
        ),
    ],
)
def test_negation_type(sentence, expected):
    assert semantic_diff.negation_type(sentence) == expected


def test_extract_marks_type_on_every_negation():
    src = claims.extract(
        "Муллиган\nНе оставляйте Мастера брони против Мага.\n"
        "Не забыть, что Мастер брони дает 5 брони.\n"
    )
    types = {n["type"] for n in src["negations"]}
    assert types == {"fact", "rhetorical"}


def test_rhetorical_negation_is_not_required_after_rebuild():
    source_text = "Муллиган\nНе забыть, что Мастер брони дает 5 брони против Мага.\n"
    src = claims.extract(source_text)
    after = "Муллиган\nМастер брони дает 5 брони против Мага.\n"
    violations, warnings, metrics = claims.coverage(src, after)
    assert violations == []
    assert metrics["negations_total"] == 0
    assert metrics["negations_optional"] >= 1


def test_fact_negation_flip_is_still_a_violation():
    src = claims.extract("Муллиган\nНе оставляйте Мастера брони против Мага.\n")
    flipped = "Муллиган\nОставляйте Мастера брони против Мага.\n"
    violations, _, metrics = claims.coverage(src, flipped)
    assert ("CLAIM_COVERAGE_LOST", "negation") in {(v["kind"], v.get("field")) for v in violations}
    assert metrics["negations_total"] >= 1


def test_old_extract_without_type_is_treated_as_fact():
    src = claims.extract("Муллиган\nНе оставляйте Мастера брони против Мага.\n")
    for n in src["negations"]:
        n.pop("type", None)
    flipped = "Муллиган\nОставляйте Мастера брони против Мага.\n"
    violations, _, _ = claims.coverage(src, flipped)
    assert violations


def test_semantic_drift_ignores_rhetorical_source_sentences():
    before = "Она не претендует на полноту. Мастер брони дает 5 брони."
    after = "Она претендует на полноту. Мастер брони дает 5 брони."
    assert semantic_diff.negation_flips(before, after) == []
    fact_before = "Не оставляйте Мастера брони против Мага."
    fact_after = "Оставляйте Мастера брони против Мага."
    assert semantic_diff.negation_flips(fact_before, fact_after)
