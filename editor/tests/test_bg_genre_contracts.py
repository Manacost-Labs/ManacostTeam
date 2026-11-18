"""Жанровые контракты Полей сражений: bg_tierlist и bg_guide.

План, карточка verdict, рубрика owner_checks (10+4 и 10+3) и подсказки
автору, research и изолированному литературному отзыву. Тексты синтетические.
"""

import hashlib

import pytest
from test_article_structure import article_plan
from test_deck_guide import deck_plan
from test_owner_review import rubric
from test_publication_run import TEXT, complete_deletion, handoff, reviews, write

from editorteam.article_structure import (
    ADVICE_FORMS,
    MASTERY_FORMS,
    TIERLIST_ROLES,
    experience_summary,
    validate_plan,
    validate_plan_evidence,
)
from editorteam.owner_review import (
    BG_GUIDE_CATEGORIES,
    BG_GUIDE_GUIDANCE,
    BG_PLAYER_POSITION_GUIDANCE,
    BG_TIERLIST_CATEGORIES,
    BG_TIERLIST_GUIDANCE,
    CATEGORIES,
    DECK_GUIDE_CATEGORIES,
    DECK_GUIDE_GUIDANCE,
    assignment,
    categories_for,
    is_deck_guide,
    plan_genre,
    validate_rubric,
)
from editorteam.publication_review import validate_handoff
from editorteam.publication_run import (
    configure_context,
    craft_guidance,
    export,
    init_run,
    next_task,
    status,
    submit,
)

BASE = {"question": "Что здесь решает игрок?", "contribution": "Позиция игрока по существу."}


def section(sid, role=None, depends_on=(), claims=(), card_ids=None):
    row = {"id": sid, **BASE, "depends_on": list(depends_on), "claim_ids": list(claims)}
    if role is not None:
        row["role"] = role
    if card_ids is not None:
        row["card_ids"] = list(card_ids)
    return row


def tierlist_plan(**changes):
    plan = {
        "genre": "bg_tierlist",
        "reader_question": "Какое существо 1-го уровня ставить первым?",
        "main_answer": "Сильнейшие первые ходы и когда от них отказаться.",
        "sections": [
            section("intro", "intro"),
            section("changes", "changes", ["intro"], ["CLM-1"]),
            section("tier-1", "tier", ["intro"], ["CLM-1"], ["VER-1"]),
            section("outro", "conclusion", ["tier-1"]),
        ],
    }
    plan.update(changes)
    return plan


def guide_plan(**changes):
    plan = {
        "genre": "bg_guide",
        "reader_question": "Когда входить в сборку?",
        "main_answer": "Сигнал входа, кривая золота и момент отказа.",
        "sections": [section("entry", claims=["CLM-1"]), section("abort", depends_on=["entry"], claims=["CLM-1"])],
    }
    plan.update(changes)
    return plan


VERDICT = {
    "take_when": "на 1-м ходу без пары в таверне",
    "skip_when": "если на 2-м ходу собирается пара",
    "pivot_or_sell_turn": "продать на 3-м ходу при переходе на 3-й уровень таверны",
    "bad_alternative_omitted": "покупка случайного заклинания ради прибавки к характеристикам",
}


def verdict_card(card_id="VER-1", **changes):
    card = {
        "card_id": card_id,
        "kind": "observed",
        "status": "supported",
        "question": "Когда ставить существо?",
        "advice_form": "verdict",
        "first_person": False,
        "fields": {
            "action": {
                "text": "Ставьте на 1-м ходу",
                "claim_ids": ["CLM-1"],
                "evidence_refs": ["SRC-1"],
            }
        },
        "verdict": dict(VERDICT),
    }
    card.update(changes)
    return card


def pack_handoff(*cards, profile="guide"):
    result = handoff()
    result["style_profile"] = profile
    result["chapters"][0]["decision_cards"] = list(cards)
    return result


def genre_rubric(text, categories):
    return rubric(text) + [
        {"id": key, "status": "clear", "quote": text, "reason": "Синтетическая запись проверена."}
        for key in categories
    ]


# ── план ────────────────────────────────────────────────────────────────


def test_bg_plans_are_valid_and_legacy_plans_stay_valid():
    validate_plan(tierlist_plan())
    validate_plan(guide_plan())
    validate_plan(deck_plan())
    validate_plan(article_plan())  # прежний план без genre/role/card_ids
    assert plan_genre({"article_plan": article_plan()}) is None
    assert plan_genre({"article_plan": tierlist_plan()}) == "bg_tierlist"
    assert plan_genre({"article_plan": guide_plan()}) == "bg_guide"
    assert not is_deck_guide({"article_plan": tierlist_plan()})


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda p: p.update(genre="meta_report"), "genre must be one of"),
        (lambda p: p.update(genre="bg_hero_guide"), "genre must be one of"),
        (lambda p: p["sections"][1].pop("role"), "every section needs a role"),
        (lambda p: p["sections"][2].update(role="changes"), "at least one tier"),
        (lambda p: p["sections"][2].update(claim_ids=[]), "must name claim_ids"),
        (lambda p: p["sections"][1].update(role="mechanics"), "role is unknown"),
        (lambda p: p["sections"][2].update(card_ids=["VER-1", "VER-1"]), "card_ids"),
    ],
)
def test_tierlist_plan_rejects_missing_roles_tiers_and_claims(mutate, message):
    plan = tierlist_plan()
    mutate(plan)
    with pytest.raises(ValueError, match=message):
        validate_plan(plan)


def test_tier_role_is_not_part_of_deck_or_legacy_plans():
    deck = deck_plan()
    deck["sections"][2]["role"] = "tier"
    with pytest.raises(ValueError, match="role is unknown"):
        validate_plan(deck)
    legacy = article_plan()
    legacy["sections"][0]["role"] = "tier"
    with pytest.raises(ValueError, match="role is unknown"):
        validate_plan(legacy)


def test_bg_guide_has_no_mandatory_roles():
    plan = guide_plan()
    plan["sections"][0]["role"] = "intro"  # роль допустима, но не обязательна
    validate_plan(plan)


def test_tier_cards_must_exist_in_the_experience_pack():
    assert validate_plan_evidence(tierlist_plan(), pack_handoff(verdict_card())) == []
    errors = validate_plan_evidence(tierlist_plan(), pack_handoff(verdict_card("VER-9")))
    assert "unknown experience cards" in " ".join(errors)
    plan = tierlist_plan()
    plan["sections"][2].pop("card_ids")  # tier без карточки verdict допустим: claims обязательны
    assert validate_plan_evidence(plan, handoff()) == []
    assert validate_plan_evidence(guide_plan(), handoff()) == []


# ── карточка verdict ────────────────────────────────────────────────────


def test_verdict_extends_the_six_forms_without_changing_mastery():
    assert ADVICE_FORMS[:6] == (
        "threshold",
        "order",
        "prohibition",
        "fallback",
        "trap",
        "skill_gated",
    )
    assert "verdict" in ADVICE_FORMS and "verdict" not in MASTERY_FORMS
    summary = experience_summary(pack_handoff(verdict_card()))
    assert summary["coverage"]["verdict"] == ["VER-1"]
    assert summary["mastery_card_ids"] == [] and not summary["mastery_allowed"]


def test_handoff_accepts_a_complete_verdict_and_rejects_partial_ones():
    assert validate_handoff(pack_handoff(verdict_card()), "test") == []
    for key in VERDICT:
        card = verdict_card()
        card["verdict"].pop(key)
        assert "verdict requires" in " ".join(validate_handoff(pack_handoff(card), "test")), key
    blank = verdict_card()
    blank["verdict"]["skip_when"] = "  "
    assert "verdict requires" in " ".join(validate_handoff(pack_handoff(blank), "test"))
    extra = verdict_card()
    extra["verdict"]["tier"] = "S"
    assert "verdict requires" in " ".join(validate_handoff(pack_handoff(extra), "test"))
    missing = verdict_card()
    missing.pop("verdict")
    assert "verdict requires" in " ".join(validate_handoff(pack_handoff(missing), "test"))
    # прежние формы и старые bundle без advice_form не меняются
    assert validate_handoff(handoff(), "test") == []
    assert validate_handoff(pack_handoff(verdict_card(advice_form="trap")), "test") == []


# ── рубрика owner_checks ────────────────────────────────────────────────


def test_genre_rubrics_have_fourteen_and_thirteen_categories():
    assert len(categories_for("bg_tierlist")) == 14 and len(BG_TIERLIST_CATEGORIES) == 4
    assert len(categories_for("bg_guide")) == 13 and len(BG_GUIDE_CATEGORIES) == 3
    assert categories_for() == CATEGORIES and categories_for(None) == CATEGORIES
    assert (
        categories_for(True) == categories_for("deck_guide") == CATEGORIES + DECK_GUIDE_CATEGORIES
    )
    assert categories_for(False) == CATEGORIES and categories_for("meta_report") == CATEGORIES
    assert set(BG_TIERLIST_CATEGORIES).isdisjoint(BG_GUIDE_CATEGORIES)


@pytest.mark.parametrize(
    "genre, extra", [("bg_tierlist", BG_TIERLIST_CATEGORIES), ("bg_guide", BG_GUIDE_CATEGORIES)]
)
def test_genre_rubric_requires_its_rows_and_rejects_foreign_ones(genre, extra):
    text = "Ставьте существо на 2-м ходу."
    assert validate_rubric(text, genre_rubric(text, extra), genre=genre) == []
    # прежний отзыв из десяти строк
    errors = " ".join(validate_rubric(text, rubric(text), genre=genre))
    assert all(f"missing category {key}" in errors for key in extra)
    assert validate_rubric(text, rubric(text)) == []  # статья без жанра — прежняя рубрика
    assert validate_rubric(text, genre_rubric(text, extra))  # жанровые строки без жанра — ошибка
    # строки чужого жанра
    assert validate_rubric(text, genre_rubric(text, DECK_GUIDE_CATEGORIES), genre=genre)
    rows = genre_rubric(text, extra)
    rows[-1]["quote"] = "Выдуманная цитата"
    assert any(extra[-1] in e for e in validate_rubric(text, rows, genre=genre))
    rows = genre_rubric(text, extra)
    rows[-1].update(status="issue", reason="Совет без условия отказа.")
    assert validate_rubric(text, rows, allow_unresolved=True, genre=genre) == []
    assert "repair required" in " ".join(validate_rubric(text, rows, genre=genre))


def test_deck_guide_flag_keeps_working():
    text = "Сохраняйте ресурс."
    assert validate_rubric(text, genre_rubric(text, DECK_GUIDE_CATEGORIES), deck_guide=True) == []
    assert (
        validate_rubric(text, genre_rubric(text, DECK_GUIDE_CATEGORIES), genre="deck_guide") == []
    )


@pytest.mark.parametrize(
    "plan, genre, extra, guidance",
    [
        (tierlist_plan(), "bg_tierlist", BG_TIERLIST_CATEGORIES, BG_TIERLIST_GUIDANCE),
        (guide_plan(), "bg_guide", BG_GUIDE_CATEGORIES, BG_GUIDE_GUIDANCE),
    ],
)
def test_assignment_lists_genre_rows_criteria_and_guidance(plan, genre, extra, guidance):
    task = assignment("Текст.", {"article_plan": plan})
    assert task["categories"] == [*CATEGORIES, *extra]
    assert set(extra) <= set(task["criteria"]) and all(task["criteria"][key] for key in extra)
    assert task[genre] == guidance and "deck_guide" not in task
    plain = assignment("Текст.", {"article_plan": article_plan()})
    assert plain["categories"] == list(CATEGORIES) and genre not in plain


def test_bg_categories_are_known_to_owner_eval():
    from editorteam.owner_eval import NEEDS_REVIEWER

    for key in (*BG_TIERLIST_CATEGORIES, *BG_GUIDE_CATEGORIES):
        assert NEEDS_REVIEWER.get(key), key


# ── подсказки автору и research ─────────────────────────────────────────


def test_craft_guidance_carries_bg_rules_to_matching_roles():
    for stage in ("draft", "deletion_pass", "literary_review"):
        assert BG_TIERLIST_GUIDANCE in craft_guidance(stage, "bg_tierlist")["principles"]
        assert BG_GUIDE_GUIDANCE in craft_guidance(stage, "bg_guide")["principles"]
        assert BG_PLAYER_POSITION_GUIDANCE not in craft_guidance(stage, "bg_tierlist")["principles"]
    for stage in ("sources", "research"):
        principles = craft_guidance(stage, "bg_tierlist")["principles"]
        assert BG_PLAYER_POSITION_GUIDANCE in principles and BG_TIERLIST_GUIDANCE not in principles
    assert DECK_GUIDE_GUIDANCE in craft_guidance("draft", True)["principles"]  # прежний вызов
    plain = craft_guidance("draft")["principles"]
    assert not {BG_TIERLIST_GUIDANCE, BG_GUIDE_GUIDANCE, BG_PLAYER_POSITION_GUIDANCE} & set(plain)


def test_bg_guidance_asks_for_player_position_and_uses_creature_types():
    for phrase in (
        "когда брать",
        "когда НЕ брать",
        "ход продажи",
        "ловушку",
        "advice_form=verdict",
    ):
        assert phrase in BG_PLAYER_POSITION_GUIDANCE, phrase
    assert "ровно в одном тире" in BG_TIERLIST_GUIDANCE
    assert "момент отказа" in BG_GUIDE_GUIDANCE
    for text in (BG_TIERLIST_GUIDANCE, BG_GUIDE_GUIDANCE, BG_PLAYER_POSITION_GUIDANCE):
        assert "плем" not in text.lower()
    assert "тип существ" in BG_TIERLIST_GUIDANCE and "тип существ" in BG_GUIDE_GUIDANCE


# ── native run ──────────────────────────────────────────────────────────


def bg_setup(tmp_path, *, profile="battlegrounds-tierlist", plan=None, research=True):
    run = tmp_path / "run"
    init_run(run, brief="Тир-лист", patch="test", profile=profile, shortcodes="off")
    context = {
        "schema_version": 1,
        "profile": profile,
        "requirements": [{"id": "conditions", "instruction": "Сохрани условие и исключение."}],
        "style_examples": [],
        "style_note": "Одно предложение в тесте, сравнение стиля не требуется.",
        **({"article_plan": plan} if plan is not None else {}),
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
    if research:
        bundle = pack_handoff(verdict_card(), profile=profile)
        submit(run, stage="research", artifact=write(tmp_path, "handoff.json", bundle))
    return run


def test_research_and_draft_tasks_ask_for_the_player_position(tmp_path):
    run = bg_setup(tmp_path, plan=tierlist_plan(), research=False)
    research = next_task(run)
    assert research["stage"] == "research"
    assert BG_PLAYER_POSITION_GUIDANCE in research["instructions"]
    assert BG_PLAYER_POSITION_GUIDANCE in research["craft_guidance"]["principles"]
    submit(
        run,
        stage="research",
        artifact=write(
            tmp_path, "handoff.json", pack_handoff(verdict_card(), profile="battlegrounds-tierlist")
        ),
    )
    draft = next_task(run)
    assert draft["stage"] == "draft"
    assert (
        "позицией игрока" in draft["instructions"]
        and "Тир-лист Полей сражений" in draft["instructions"]
    )
    assert BG_TIERLIST_GUIDANCE in draft["craft_guidance"]["principles"]
    assert draft["bg_tierlist"]["verdict_card_ids"] == ["VER-1"]
    assert draft["bg_tierlist"]["section_roles"] == list(TIERLIST_ROLES)
    assert "deck_guide" not in draft


def test_native_bg_tierlist_needs_fourteen_rows_before_export(tmp_path):
    run = bg_setup(tmp_path, plan=tierlist_plan())
    submit(run, stage="draft", artifact=write(tmp_path, "draft.md", TEXT))
    complete_deletion(run)
    fact, literary = reviews(run)
    fact["decision_cards_checked"] = True  # в handoff есть карточка verdict
    submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    literary_task = next_task(run)
    assignment_task = literary_task["owner_review_assignment"]
    assert len(assignment_task["categories"]) == 14
    assert assignment_task["categories"][-4:] == list(BG_TIERLIST_CATEGORIES)
    assert BG_TIERLIST_GUIDANCE in literary_task["craft_guidance"]["principles"]
    assert literary_task["editorial_practices"]["owner_review_assignment"] == assignment_task
    # прежний отзыв из десяти строк читается, но не пропускает тир-лист
    state = submit(run, stage="literary_review", artifact=write(tmp_path, "old.json", literary))
    assert state["blocked"] and "missing category uniform_entry_structure" in " ".join(
        state["blocked"]["errors"]
    )
    with pytest.raises(ValueError):
        export(run, output=tmp_path / "final.md")
    assert status(run)["blocked"]
    literary["owner_checks"] = genre_rubric(TEXT, BG_TIERLIST_CATEGORIES)
    state = submit(
        run,
        stage="literary_review",
        artifact=write(tmp_path, "new.json", literary),
        retry_review=True,
    )
    assert not state["blocked"] and state["stage"] == "ready"
    export(run, output=tmp_path / "final.md")


def test_native_bg_guide_needs_thirteen_rows(tmp_path):
    run = bg_setup(tmp_path, profile="battlegrounds-guide", plan=guide_plan())
    submit(run, stage="draft", artifact=write(tmp_path, "draft.md", TEXT))
    complete_deletion(run)
    fact, literary = reviews(run)
    fact["decision_cards_checked"] = True
    submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    categories = next_task(run)["owner_review_assignment"]["categories"]
    assert len(categories) == 13 and categories[-3:] == list(BG_GUIDE_CATEGORIES)
    literary["owner_checks"] = genre_rubric(TEXT, BG_GUIDE_CATEGORIES)
    state = submit(run, stage="literary_review", artifact=write(tmp_path, "lit.json", literary))
    assert not state["blocked"] and state["stage"] == "ready"
    export(run, output=tmp_path / "final.md")


def test_tierlist_profile_without_plan_genre_gets_guidance_but_keeps_ten_rows(tmp_path):
    plan = article_plan()  # старый план без genre
    run = bg_setup(tmp_path, plan=plan)
    draft = next_task(run)
    assert BG_TIERLIST_GUIDANCE in draft["craft_guidance"]["principles"]
    assert "позицией игрока" in draft["instructions"]
    submit(run, stage="draft", artifact=write(tmp_path, "draft.md", TEXT))
    complete_deletion(run)
    fact, literary = reviews(run)
    fact["decision_cards_checked"] = True
    submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    assert next_task(run)["owner_review_assignment"]["categories"] == list(CATEGORIES)
    state = submit(run, stage="literary_review", artifact=write(tmp_path, "lit.json", literary))
    assert not state["blocked"] and state["stage"] == "ready"
