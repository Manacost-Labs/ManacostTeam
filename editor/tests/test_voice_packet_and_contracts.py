"""Фаза 2: voice_packet первичного черновика, thesis-card, ослабление confidence_quote
для medium с условием или числом, meta_thesis/entry_weights плана и критерий
uniform_entry_structure с явным блоком grouped. Тексты синтетические."""

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from test_article_structure import article_plan
from test_bg_genre_contracts import pack_handoff, section, tierlist_plan, verdict_card
from test_deck_guide import deck_plan
from test_publication_run import TEXT, complete_deletion, reviews, write

from editorteam.article_structure import validate_plan
from editorteam.owner_review import (
    BG_TIERLIST_CATEGORIES,
    BG_TIERLIST_CRITERIA,
    BG_TIERLIST_GUIDANCE,
)
from editorteam.publication_review import article_hash, handoff_hash, validate_factual
from editorteam.publication_run import (
    STATS_INSIGHTS,
    VOICE_CUES,
    configure_context,
    init_run,
    main,
    next_task,
    submit,
    thesis_card,
)

PROFILE = "battlegrounds-tierlist"
THESIS = "Скачки силы на 3–4-м уровне таверны велики: золото на мелкие характеристики 1-го уровня не тратьте."
WEIGHTS = {"full": ["Музыкант", "Нетопырь"], "brief": ["Бликостраж"], "grouped": ["Черепушка", "Всадник"]}
BUREAUCRACY = ("editorial_practices", "editorial_practices_reference")


def weighted_plan(**changes):
    plan = tierlist_plan(meta_thesis=THESIS)
    plan["sections"][2]["entry_weights"] = deepcopy(WEIGHTS)
    plan.update(changes)
    return plan


def voice_run(tmp_path, plan=None):
    run = tmp_path / "run"
    init_run(run, brief="Тир-лист", patch="test", profile=PROFILE, shortcodes="off")
    source = write(tmp_path, "old-guide.md", "Старый гайд. Ставьте на 2-м ходу, без вариантов.")
    configure_context(run, artifact=write(tmp_path, "task-context.json", {
        "schema_version": 1,
        "profile": PROFILE,
        "article_plan": plan or weighted_plan(),
        "requirements": [{
            "id": "no-stack",
            "instruction": "Не называй магнетизм стеком.",
            "forbidden_literals": ["стек"],
        }],
        "style_note": "Синтетический образец голоса, не одобренный эталон.",
        "style_examples": [{
            "id": "old-guide", "profile": PROFILE, "source": "https://example.org/old-guide",
            "source_path": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "quote": "Ставьте на 2-м ходу, без вариантов.",
            "use_for": "Рубленый вывод после объяснения", "avoid": "Старые игровые факты",
        }],
    }))
    rows = [{
        "id": "one", "source": "mcp", "url": "https://example.org/guide", "text": TEXT, "access": "full",
        "sha256": hashlib.sha256(TEXT.encode()).hexdigest(), "retrieved_at": "2026-10-10T12:00:00Z",
    }]
    submit(run, stage="sources", artifact=write(tmp_path, "sources.json", rows))
    submit(run, stage="research", artifact=write(
        tmp_path, "handoff.json", pack_handoff(verdict_card(), profile=PROFILE)
    ))
    return run


INSIGHTS = {
    "schema_version": "1.0",
    "mode": "battlegrounds",
    "source_urls": ["https://api.kolodahearthstone.com/v1/battlegrounds/minions"],
    "warnings": ["Срез battlegrounds-minions устарел: 30 ч."],
    "insights": {
        "crowd_traps": [{
            "card_id": "BG_X", "dbf_id": 1, "name": "Надзиратель", "tavern_tier": 1,
            "popularity": 8.07, "popularity_rank": 1, "combat_winrate": 57.31, "impact": -0.06,
            "avg_placement_with": 4.38, "avg_placement_without": 4.32, "label": "ловушка толпы",
        }],
        "pure_early_tempo": [{"name": "Бликостраж", "combat_winrate": 58.2, "impact": -0.01, "label": "ранний темп"}],
        "scaling_engines": [],
        "rank_skill_gaps": [],
    },
}


# ── voice_packet ────────────────────────────────────────────────────────


def test_initial_draft_gets_voice_packet_without_review_checklists(tmp_path):
    run = voice_run(tmp_path)
    task = next_task(run)
    assert task["stage"] == "draft" and task["repair"] is None
    voice = task["voice_packet"]
    assert voice["meta_thesis"] == THESIS
    assert voice["voice_cues"] == list(VOICE_CUES) and len(VOICE_CUES) == 5
    assert voice["stats_insights"] == {}
    assert [row["quote"] for row in voice["style_examples"]] == ["Ставьте на 2-м ходу, без вариантов."]
    # бюрократия на черновике не передаётся
    for key in BUREAUCRACY:
        assert key not in task
    assert "editorial_passes" not in task["craft_guidance"]
    assert "reader_quality_checks" not in task["craft_guidance"]
    assert "practice_checks" not in task["instructions"] and "review_schema" not in task["instructions"]
    # требования владельца, план и жанровые правила остаются
    requirement = task["author_context"]["requirements"][0]
    assert requirement["forbidden_literals"] == ["стек"]
    assert task["author_context"]["article_plan"]["meta_thesis"] == THESIS
    assert "style_examples" not in task["author_context"]  # перенесены, а не продублированы
    assert BG_TIERLIST_GUIDANCE in task["craft_guidance"]["principles"]
    assert task["bg_tierlist"]["guidance"] == BG_TIERLIST_GUIDANCE
    assert "voice_packet" in task["instructions"] and "Тир-лист Полей сражений" in task["instructions"]
    assert "grouped" in task["instructions"]
    # пакет — свежий снимок, не общее состояние
    voice["voice_cues"].clear()
    assert next_task(run)["voice_packet"]["voice_cues"]


def test_stats_insights_file_reaches_the_author_as_is(tmp_path):
    run = voice_run(tmp_path)
    write(run, STATS_INSIGHTS, INSIGHTS)
    assert next_task(run)["voice_packet"]["stats_insights"] == INSIGHTS
    write(run, STATS_INSIGHTS, ["не словарь"])
    with pytest.raises(ValueError, match="JSON object"):
        next_task(run)


def test_deletion_reviews_and_repair_keep_the_full_strict_set(tmp_path):
    run = voice_run(tmp_path)
    submit(run, stage="draft", artifact=write(tmp_path, "draft.md", TEXT))
    deletion = next_task(run)
    assert deletion["stage"] == "deletion_pass" and "voice_packet" not in deletion
    assert [row["id"] for row in deletion["craft_guidance"]["editorial_passes"]] == ["deletion_pass"]
    assert deletion["deletion_assignment"]["rules"]
    complete_deletion(run)
    fact, literary = reviews(run)
    fact["decision_cards_checked"] = True
    factual_task = next_task(run)
    assert factual_task["stage"] == "fact_review" and "voice_packet" not in factual_task
    assert "editorial_practices" in factual_task
    submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    review = next_task(run)
    assert review["stage"] == "literary_review" and "voice_packet" not in review
    assert review["craft_guidance"]["reader_quality_checks"]
    assert [row["id"] for row in review["craft_guidance"]["editorial_passes"]] == [
        "author", "deletion_pass", "prose",
    ]
    assert "editorial_practices" in review and review["author_context_review_schema"]
    assert review["author_context"]["style_examples"]
    # без строк жанра и образца отзыв отклонён → repair
    state = submit(run, stage="literary_review", artifact=write(tmp_path, "lit.json", literary))
    assert state["blocked"]
    repair = next_task(run)
    assert repair["stage"] == "draft" and repair["repair"]
    assert "voice_packet" not in repair
    assert repair["craft_guidance"]["reader_quality_checks"]
    assert repair["craft_guidance"]["editorial_passes"]
    assert "editorial_practices_reference" in repair
    assert "practice_checks" in repair["instructions"]
    assert repair["author_context"]["style_examples"]


# ── thesis-card ─────────────────────────────────────────────────────────


def test_thesis_card_is_short_and_shows_thesis_contrasts_and_weights(tmp_path):
    run = voice_run(tmp_path)
    card = thesis_card(run)
    assert card.splitlines()[0] == "Тезис: " + THESIS
    assert "stats_insights" in card and "нет" in card  # подсказка шага 0
    assert "tier-1 2/1/2" in card and "full 2 · brief 1 · grouped 2" in card
    write(run, STATS_INSIGHTS, INSIGHTS)
    card = thesis_card(run)
    lines = card.splitlines()
    assert len(lines) <= 12
    assert "Контрасты stats-insights.json: 2, предупреждений: 1" in card
    assert "ловушка толпы: Надзиратель (popularity=8.07, combat_winrate=57.31, impact=-0.06" in card
    assert "ранний темп: Бликостраж" in card
    assert "устарел" in card
    assert "source_urls" not in card


def test_thesis_card_without_plan_fields_and_through_cli(tmp_path, capsys):
    run = voice_run(tmp_path, plan=tierlist_plan())  # прежний план без новых полей
    card = thesis_card(run)
    assert "не задан" in card and "full 0 · brief 0 · grouped 0" in card
    assert main(["thesis-card", str(run)]) == 0
    assert capsys.readouterr().out.strip() == card
    script = Path(__file__).resolve().parents[2] / "teams" / "manacost-publish" / "scripts" / "publish.py"
    result = subprocess.run(
        [sys.executable, str(script), "thesis-card", str(run)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == card


# ── confidence_quote ────────────────────────────────────────────────────


def factual_case(*, confidence="medium", condition="если нет угрозы", action="Сохраните ресурс"):
    text = f"{action}, если нет угрозы, кроме срочного ответа. Иногда полезно. [Источник](https://example.org/guide)"
    handoff = {
        "schema_version": 1, "brief": "Синтетический совет", "patch": "test-patch",
        "status": "research_ready", "style_profile": "guide",
        "sources": [{"source_id": "s", "url": "https://example.org/guide", "quote": "Исходная цитата"}],
        "claims": [{
            "claim_id": "c", "meaning": f"{action} {condition}".strip(), "action": action,
            "condition": condition, "exception": "кроме срочного ответа", "confidence": confidence,
            "patch": "test-patch", "evidence_refs": ["s"],
            "status": "supported_with_conditions" if condition else "supported",
        }],
        "chapters": [{"chapter_id": "ch", "title": "Решение", "required_claim_ids": ["c"], "unresolved_questions": []}],
        "decisions": [{
            "question_id": "q", "chapter_id": "ch", "question": "Когда сохранить ресурс?",
            "required": True, "status": "answered", "claim_ids": ["c"],
        }],
    }
    report = {
        "article_sha256": article_hash(text), "handoff_sha256": handoff_hash(handoff), "status": "pass",
        "confidence_preserved": True, "candidate_checked": True, "patch_matches": True,
        "unsupported_claims": [], "conflicts": [],
        "claims": [{
            "claim_id": "c", "status": "supported", "action_quote": action,
            "condition_quote": "если нет угрозы" if condition else "",
            "exception_quote": "кроме срочного ответа", "confidence_quote": "", "evidence_refs": ["s"],
        }],
    }
    return handoff, text, report


def confidence_errors(handoff, text, report):
    return [error for error in validate_factual(handoff, text, report) if "confidence_quote" in error]


def test_medium_with_found_condition_needs_no_hedge():
    assert validate_factual(*factual_case()) == []


def test_medium_without_condition_or_number_still_needs_confidence_quote():
    handoff, text, report = factual_case(condition="")
    assert confidence_errors(handoff, text, report)
    report["claims"][0]["confidence_quote"] = "Иногда полезно"
    assert validate_factual(handoff, text, report) == []


def test_medium_with_exact_number_in_action_needs_no_hedge():
    handoff, text, report = factual_case(condition="", action="Бейте с шансом 33%")
    assert validate_factual(handoff, text, report) == []


def test_medium_condition_quote_must_be_found_to_close_confidence():
    handoff, text, report = factual_case()
    report["claims"][0]["condition_quote"] = "если угрозы нет вовсе"  # нет в тексте
    errors = validate_factual(handoff, text, report)
    assert any("condition_quote" in error for error in errors)
    assert confidence_errors(handoff, text, report)


def test_low_always_needs_confidence_quote_and_invented_quote_fails():
    handoff, text, report = factual_case(confidence="low", action="Бейте с шансом 33%")
    assert confidence_errors(handoff, text, report)
    report["claims"][0]["confidence_quote"] = "Иногда полезно"
    assert validate_factual(handoff, text, report) == []
    report["claims"][0]["confidence_quote"] = "Выдуманная оговорка"
    assert confidence_errors(handoff, text, report)
    high = factual_case(confidence="high", condition="")
    assert validate_factual(*high) == []


# ── meta_thesis и entry_weights ─────────────────────────────────────────


def test_meta_thesis_and_entry_weights_are_valid_and_legacy_plans_pass():
    validate_plan(weighted_plan())
    plan = article_plan()
    plan["meta_thesis"] = "т" * 600
    plan["sections"][0]["entry_weights"] = {"brief": ["Одна карта"]}
    validate_plan(plan)
    for legacy in (article_plan(), deck_plan(), tierlist_plan()):
        validate_plan(legacy)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda p: p.update(meta_thesis=""), "meta_thesis"),
        (lambda p: p.update(meta_thesis="т" * 601), "meta_thesis"),
        (lambda p: p.update(meta_thesis=["тезис"]), "meta_thesis"),
        (lambda p: p.update(thesis="лишнее поле"), "requires reader_question"),
        (lambda p: p["sections"][2].update(entry_weights=[]), "entry_weights must map"),
        (lambda p: p["sections"][2].update(entry_weights={}), "entry_weights must map"),
        (lambda p: p["sections"][2].update(entry_weights={"middle": ["Карта"]}), "entry_weights must map"),
        (lambda p: p["sections"][2].update(entry_weights={"full": []}), "bounded list"),
        (lambda p: p["sections"][2].update(entry_weights={"full": "Карта"}), "bounded list"),
        (lambda p: p["sections"][2].update(entry_weights={"full": ["к" * 101]}), "bounded list"),
        (lambda p: p["sections"][2].update(entry_weights={"grouped": ["Одна"]}), "at least two"),
        (
            lambda p: p["sections"][2].update(entry_weights={"full": ["Карта"], "brief": ["карта"]}),
            "two weights or sections",
        ),
        (
            lambda p: p["sections"][3].update(entry_weights={"brief": ["Музыкант"]}),
            "two weights or sections",
        ),
    ],
)
def test_invalid_meta_thesis_and_entry_weights_are_rejected(mutate, message):
    plan = weighted_plan()
    mutate(plan)
    with pytest.raises(ValueError, match=message):
        validate_plan(plan)


def test_entry_weights_across_two_tiers_must_not_split_a_card():
    plan = weighted_plan()
    plan["sections"].insert(3, section("tier-2", "tier", ["intro"], ["CLM-1"]))
    plan["sections"][3]["entry_weights"] = {"grouped": ["Нетопырь", "Кабельщик"]}
    with pytest.raises(ValueError, match="two weights or sections"):
        validate_plan(plan)
    plan["sections"][3]["entry_weights"] = {"grouped": ["Призёр", "Кабельщик"]}
    validate_plan(plan)


# ── критерий uniform_entry_structure ────────────────────────────────────


def test_uniform_entry_structure_allows_grouped_block_but_not_fake_bridges():
    assert BG_TIERLIST_CATEGORIES[0] == "uniform_entry_structure"
    criterion = BG_TIERLIST_CRITERIA["uniform_entry_structure"]
    for phrase in ("full и brief", "grouped", "единым правилом выбора", "мостиком", "двумя тирами"):
        assert phrase in criterion, phrase
    for phrase in ("grouped", "ровно в одном тире", "тип существ"):
        assert phrase in BG_TIERLIST_GUIDANCE, phrase
    for text in (criterion, BG_TIERLIST_GUIDANCE, json.dumps(VOICE_CUES, ensure_ascii=False)):
        assert "плем" not in text.lower()
