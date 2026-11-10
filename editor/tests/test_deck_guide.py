"""Гайд по колоде: план, пакет опыта игрока, рубрика и однообразные начала.

Тексты и карточки синтетические: эталонный гайд владельца в Git не входит.
"""

import hashlib

import pytest
from test_article_structure import article_plan, structure_assessment
from test_owner_review import rubric
from test_publication_run import TEXT, complete_deletion, handoff, reviews, write

from editorteam import owner_checks as O
from editorteam.article_structure import (
    experience_cards,
    experience_summary,
    validate_plan,
    validate_plan_evidence,
    validate_plan_review,
)
from editorteam.owner_review import (
    CATEGORIES,
    DECK_GUIDE_CATEGORIES,
    assignment,
    is_deck_guide,
    validate_rubric,
)
from editorteam.publication_review import validate_handoff
from editorteam.publication_run import (
    configure_context,
    export,
    init_run,
    next_task,
    status,
    submit,
)

BASE = {"question": "Что здесь решает игрок?", "contribution": "Ответ на вопрос читателя.", "claim_ids": []}


def section(sid, role, depends_on=(), card_ids=(), claims=()):
    return {
        "id": sid,
        **BASE,
        "claim_ids": list(claims),
        "depends_on": list(depends_on),
        "role": role,
        "card_ids": list(card_ids),
    }


def deck_plan(**changes):
    plan = {
        "genre": "deck_guide",
        "reader_question": "Как играть колоду?",
        "main_answer": "Сначала механика, затем карты и мастерство.",
        "sections": [
            section("intro", "intro"),
            section("mechanics", "mechanics", ["intro"], claims=["CLM-1"]),
            section("cards", "cards", ["mechanics"]),
            section("mastery-order", "mastery", ["mechanics", "cards"], ["EXP-1"]),
            section("against", "against", ["mechanics"]),
        ],
    }
    plan.update(changes)
    return plan


def card(card_id, form, *, first_person=False):
    return {
        "card_id": card_id,
        "kind": "observed",
        "status": "supported",
        "question": "Когда выполнять действие?",
        "advice_form": form,
        "first_person": first_person,
        "fields": {
            "action": {"text": "Выполняйте действие", "claim_ids": ["CLM-1"], "evidence_refs": ["SRC-1"]}
        },
    }


def pack_handoff(*cards):
    result = handoff()
    result["chapters"][0]["decision_cards"] = list(cards)
    return result


# ── план ────────────────────────────────────────────────────────────────


def test_deck_plan_accepts_the_decision_order_and_legacy_plans_stay_valid():
    validate_plan(deck_plan())
    validate_plan(article_plan())  # прежний план без genre/role/card_ids
    legacy = article_plan()
    legacy["sections"][0]["role"] = "cards"  # роль и без genre допустима, но не обязана
    validate_plan(legacy)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda p: p["sections"][1].update(role="cards"), "exactly one mechanics"),
        (lambda p: p["sections"].__setitem__(2, section("cards", "cards", ["intro"])), "must depend on the mechanics"),
        (lambda p: p["sections"].insert(1, section("early", "early", ["intro"])), "mechanics must follow the intro"),
        (lambda p: p["sections"].__setitem__(3, section("m", "mastery", ["mechanics"])), "must name its experience card_ids"),
        (lambda p: p["sections"][2].update(role="plan"), "role is unknown"),
        (lambda p: p["sections"][2].pop("role"), "every section needs a role"),
        (lambda p: p["sections"][2].update(card_ids=["A", "A"]), "card_ids"),
        (lambda p: p.update(genre="meta_report"), "genre"),
    ],
)
def test_deck_plan_rejects_a_misplaced_or_missing_mechanics_section(mutate, message):
    plan = deck_plan()
    mutate(plan)
    with pytest.raises(ValueError, match=message):
        validate_plan(plan)


def test_dependency_on_mechanics_may_be_indirect():
    plan = deck_plan()
    plan["sections"][4] = section("against", "against", ["cards"])  # cards зависит от mechanics
    validate_plan(plan)


def test_plan_review_catches_actual_order_where_cards_precede_the_explanation():
    plan = deck_plan()
    plan["sections"] = plan["sections"][1:3]
    plan["sections"][1] = section("cards", "cards", ["mechanics"])
    plan["sections"][0]["depends_on"] = []
    text = "Карты по ролям.\n\nКак работает колода.\n"
    rows = [
        {"id": "mechanics", "block_ids": ["b002"], "status": "clear", "reason": "Объяснение после карт."},
        {"id": "cards", "block_ids": ["b001"], "status": "clear", "reason": "Карты."},
    ]
    assert "before its prerequisite" in " ".join(validate_plan_review(plan, text, rows))
    rows[0]["block_ids"], rows[1]["block_ids"] = ["b001"], ["b002"]
    assert validate_plan_review(plan, text, rows) == []


# ── пакет опыта ─────────────────────────────────────────────────────────


def test_plan_cards_must_exist_and_mastery_needs_a_threshold_or_an_order():
    plan = deck_plan()
    plan["sections"][1]["claim_ids"] = ["CLM-1"]
    good = pack_handoff(card("EXP-1", "order"))
    assert validate_plan_evidence(plan, good) == []
    assert "unknown experience cards" in " ".join(validate_plan_evidence(plan, pack_handoff(card("EXP-9", "order"))))
    trap_only = pack_handoff(card("EXP-1", "trap"))
    assert "threshold or order" in " ".join(validate_plan_evidence(plan, trap_only))


def test_old_bundle_without_experience_cannot_back_a_mastery_section():
    plan = deck_plan()
    plan["sections"][1]["claim_ids"] = ["CLM-1"]
    errors = validate_plan_evidence(plan, handoff())
    assert "unknown experience cards" in " ".join(errors)
    summary = experience_summary(handoff())
    assert summary["cards"] == 0 and not summary["mastery_allowed"]
    assert "писать не из чего" in summary["note"]
    # без раздела мастерства план без опыта допустим: редактор работает со старым bundle
    plan = deck_plan()
    plan["sections"] = [s for s in plan["sections"] if s["role"] != "mastery"]
    plan["sections"][1]["claim_ids"] = ["CLM-1"]
    assert validate_plan_evidence(plan, handoff()) == []


def test_experience_summary_counts_forms_and_first_person():
    cards = [card("A", "threshold", first_person=True), card("B", "trap"), card("C", "order")]
    summary = experience_summary(pack_handoff(*cards))
    assert summary["cards"] == 3
    assert summary["coverage"]["threshold"] == ["A"] and summary["coverage"]["skill_gated"] == []
    assert summary["first_person_card_ids"] == ["A"]
    assert summary["mastery_card_ids"] == ["A", "C"] and summary["mastery_allowed"]
    assert len(experience_cards(pack_handoff(*cards, {**card("D", "trap"), "advice_form": "tip"}))) == 3


def test_handoff_accepts_missing_fields_and_rejects_invalid_ones():
    assert validate_handoff(handoff(), "test") == []
    assert validate_handoff(pack_handoff(card("EXP-1", "order")), "test") == []
    bad = pack_handoff(card("EXP-1", "tip"))
    assert "advice_form" in " ".join(validate_handoff(bad, "test"))
    bad = pack_handoff({**card("EXP-1", "order"), "first_person": "yes"})
    assert "first_person" in " ".join(validate_handoff(bad, "test"))


# ── рубрика ─────────────────────────────────────────────────────────────


def deck_rubric(text):
    return rubric(text) + [
        {"id": key, "status": "clear", "quote": text, "reason": "Синтетический гайд проверен."}
        for key in DECK_GUIDE_CATEGORIES
    ]


def test_deck_rubric_requires_three_extra_rows_with_quotes():
    text = "Сохраняйте ресурс при угрозе поражения."
    assert validate_rubric(text, deck_rubric(text), deck_guide=True) == []
    errors = validate_rubric(text, rubric(text), deck_guide=True)  # прежний отзыв из десяти строк
    assert all(f"missing category {key}" in " ".join(errors) for key in DECK_GUIDE_CATEGORIES)
    assert validate_rubric(text, rubric(text)) == []  # обычная статья — прежняя рубрика
    assert validate_rubric(text, deck_rubric(text))  # лишние строки вне гайда — ошибка
    for key in DECK_GUIDE_CATEGORIES:
        rows = deck_rubric(text)
        row = next(r for r in rows if r["id"] == key)
        row["quote"] = "Выдуманная цитата"
        assert any(key in e for e in validate_rubric(text, rows, deck_guide=True)), key


@pytest.mark.parametrize("key", DECK_GUIDE_CATEGORIES)
def test_negative_deck_verdict_is_evidence_but_demands_repair(key):
    text = "Сохраняйте ресурс при угрозе поражения."
    rows = deck_rubric(text)
    next(r for r in rows if r["id"] == key).update(status="issue", reason="Совет без причины.")
    assert validate_rubric(text, rows, allow_unresolved=True, deck_guide=True) == []
    errors = " ".join(validate_rubric(text, rows, deck_guide=True))
    assert "repair required" in errors and key in errors


def test_assignment_lists_extra_categories_only_for_a_deck_plan():
    text = "Текст."
    plain = assignment(text, {"article_plan": article_plan()})
    assert plain["categories"] == list(CATEGORIES) and "deck_guide" not in plain
    deck = assignment(text, {"article_plan": deck_plan()})
    assert deck["categories"] == [*CATEGORIES, *DECK_GUIDE_CATEGORIES]
    assert set(DECK_GUIDE_CATEGORIES) <= set(deck["criteria"])
    assert "первое лицо" in deck["deck_guide"].lower() or "Первое лицо" in deck["deck_guide"]
    assert is_deck_guide({"article_plan": deck_plan()}) and not is_deck_guide(None)


def test_new_reviewer_categories_are_known_to_owner_eval():
    from editorteam.owner_eval import NEEDS_REVIEWER

    assert set(DECK_GUIDE_CATEGORIES) <= set(NEEDS_REVIEWER)
    assert all(NEEDS_REVIEWER[key] for key in DECK_GUIDE_CATEGORIES)


# ── native run ──────────────────────────────────────────────────────────


def deck_setup(tmp_path):
    run = tmp_path / "run"
    init_run(run, brief="Гайд", patch="test", profile="guide", shortcodes="off")
    plan = {
        "genre": "deck_guide",
        "reader_question": "Когда сохранять ресурс?",
        "main_answer": "При слабой позиции, кроме угрозы поражения.",
        "sections": [
            section("mechanics", "mechanics", claims=["CLM-1"]),
            section("mastery-order", "mastery", ["mechanics"], ["EXP-1"]),
        ],
    }
    context = {
        "schema_version": 1,
        "profile": "guide",
        "article_plan": plan,
        "requirements": [{"id": "conditions", "instruction": "Сохрани условие и исключение."}],
        "style_examples": [],
        "style_note": "Одно предложение в тесте, сравнение стиля не требуется.",
    }
    configure_context(run, artifact=write(tmp_path, "task-context.json", context))
    rows = [
        {
            "id": "one",
            "source": "mcp",
            "url": "https://example.org/guide",
            "text": TEXT,
            "access": "full",
            "sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
            "retrieved_at": "2026-10-10T12:00:00Z",
        }
    ]
    submit(run, stage="sources", artifact=write(tmp_path, "sources.json", rows))
    submit(run, stage="research", artifact=write(tmp_path, "handoff.json", pack_handoff(card("EXP-1", "order"))))
    return run


def deck_run(tmp_path):
    run = deck_setup(tmp_path)
    submit(run, stage="draft", artifact=write(tmp_path, "draft.md", TEXT))
    complete_deletion(run)
    return run


def test_author_task_carries_deck_rules_and_the_experience_pack(tmp_path):
    task = next_task(deck_setup(tmp_path))
    assert task["stage"] == "draft"
    principles = " ".join(task["craft_guidance"]["principles"])
    for phrase in ("«>»", "first_person=true", "писать не из чего", "после вступления"):
        assert phrase in principles, phrase
    assert "Гайд по колоде" in task["instructions"]
    pack = task["deck_guide"]["experience_pack"]
    assert pack["mastery_card_ids"] == ["EXP-1"] and pack["coverage"]["order"] == ["EXP-1"]
    assert pack["first_person_card_ids"] == []


def test_native_deck_guide_needs_the_three_extra_rows_before_export(tmp_path):
    run = deck_run(tmp_path)
    assert next_task(run)["deck_guide"]["experience_pack"]["mastery_allowed"] is True
    fact, literary = reviews(run)
    fact["decision_cards_checked"] = True  # в handoff есть карточки опыта
    submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    literary_task = next_task(run)
    assert literary_task["owner_review_assignment"]["categories"][-3:] == list(DECK_GUIDE_CATEGORIES)
    # прежний отзыв из десяти строк читается, но не пропускает гайд по колоде
    state = submit(run, stage="literary_review", artifact=write(tmp_path, "old.json", literary))
    assert state["blocked"] and "missing category advice_has_condition_and_reason" in " ".join(state["blocked"]["errors"])
    with pytest.raises(ValueError):
        export(run, output=tmp_path / "final.md")
    assert status(run)["blocked"]
    literary["owner_checks"] = deck_rubric(TEXT)
    state = submit(
        run, stage="literary_review", artifact=write(tmp_path, "new.json", literary), retry_review=True
    )
    assert not state["blocked"] and state["stage"] == "ready"
    export(run, output=tmp_path / "final.md")


def test_ordinary_run_keeps_the_ten_row_rubric(tmp_path):
    from test_publication_run import prepared

    run = prepared(tmp_path)
    task = next_task(run)
    assert "deck_guide" not in task
    fact, literary = reviews(run)
    submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    state = submit(run, stage="literary_review", artifact=write(tmp_path, "lit.json", literary))
    assert not state["blocked"]
    assert structure_assessment(TEXT)  # импорт используется для общей фикстуры


# ── однообразные начала абзацев ─────────────────────────────────────────

FILLER = "Карта{n} — ключевая часть набора, без неё колода не работает как задумано."


def uniform_section(count):
    return "\n\n".join(FILLER.format(n=chr(1040 + i)) for i in range(count))


def test_uniform_title_openings_are_found_inside_a_section():
    text = "# Основа\n\n" + uniform_section(11) + "\n\n# Сборки\n\nОтдельный абзац без схемы, обычная фраза.\n"
    hits = O.paragraph_openings(text)
    assert len(hits) == 1 and hits[0]["scheme"] == "title"
    assert hits[0]["count"] == 11 and hits[0]["line"] == 3


def test_short_series_headings_and_lists_do_not_trigger():
    assert O.paragraph_openings("# Основа\n\n" + uniform_section(9)) == []
    split = uniform_section(6) + "\n\n## Дальше\n\n" + uniform_section(6)
    assert O.paragraph_openings(split) == []  # заголовок обрывает серию
    listed = "\n".join(f"- {FILLER.format(n=chr(1040 + i))}" for i in range(14))
    assert O.paragraph_openings(listed) == []


def test_one_foreign_paragraph_does_not_hide_the_series():
    rows = [FILLER.format(n=chr(1040 + i)) for i in range(12)]
    rows.insert(5, "Ключевой вывод в одном абзаце без названия и тире, как обычный текст.")
    assert len(O.paragraph_openings("\n\n".join(rows))) == 1
    rows.insert(6, "Второй посторонний абзац подряд, который уже разрывает серию целиком.")
    assert O.paragraph_openings("\n\n".join(rows)) == []


def test_title_series_needs_empty_entries_to_be_reported():
    """«Карта — роль и условие» — авторская форма: сигнал только при пустых записях."""
    full = (
        "Карта{n} — берите её на второй ход против быстрых колод, потому что она "
        "забирает стол соперника раньше, чем он успевает развиться."
    )
    rows = [full.format(n=chr(1040 + i)) for i in range(12)]
    blank = chr(10) * 2
    assert O.paragraph_openings(blank.join(rows)) == []
    rows[3] = FILLER.format(n="Г")
    assert O.paragraph_openings(blank.join(rows)) == []  # одна пустая запись — ещё не серия
    rows[7] = FILLER.format(n="З")
    hits = O.paragraph_openings(blank.join(rows))
    assert len(hits) == 1 and hits[0]["short"] == 2
    assert all("ключевая часть" in quote for quote in hits[0]["quotes"])


def test_same_first_word_series_is_reported():
    rows = [f"Если соперник играет вариант {i}, меняйте план и ждите момента для удара." for i in range(7)]
    hits = O.paragraph_openings("\n\n".join(rows))
    assert len(hits) == 1 and hits[0]["scheme"] == "word" and hits[0]["key"] == "если"


def test_audit_reports_the_new_check_as_review_for_deck_guides(tmp_path):
    from editorteam.cli import owner_findings

    text = "# Основа колоды\n\n" + uniform_section(11)
    findings = [f for f in owner_findings(text, "constructed-guide") if f["id"] == "owner.paragraph_starts"]
    assert len(findings) == 1 and findings[0]["severity"] == "review"
    assert owner_findings(text, "news") == []


def test_only_supported_observed_cards_form_the_pack_and_handoff_gaps_pass_through():
    inference = {**card("EXP-2", "order"), "status": "inference", "kind": "derived"}
    handoff_with_gap = pack_handoff(card("EXP-1", "trap"), inference)
    handoff_with_gap["experience_coverage"] = {"gaps": ["раздел мастерства писать не из чего"]}
    summary = experience_summary(handoff_with_gap)
    assert summary["cards"] == 1 and summary["coverage"]["order"] == []
    assert not summary["mastery_allowed"] and "писать не из чего" in summary["note"]
    assert summary["handoff_gaps"] == ["раздел мастерства писать не из чего"]
    assert experience_summary(handoff())["handoff_gaps"] == []


def test_research_shaped_experience_card_is_accepted_with_its_extra_fields():
    rich = {
        **card("EXP-1", "threshold"),
        "condition": "в колоде осталось 8–10 карт",
        "reason": "добор и обмен успевают прийти",
        "error_cost": "прокрутка встаёт",
        "threshold": {"value": 10, "unit": "карт"},
        "experience_source": {"kind": "author_note", "source_id": "SRC-1", "evidence_id": "EV-1"},
        "first_person": True,
    }
    result = pack_handoff(rich)
    assert validate_handoff(result, "test") == []
    assert experience_summary(result)["first_person_card_ids"] == ["EXP-1"]
