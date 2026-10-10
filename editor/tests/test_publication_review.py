"""Publication gates bind independent assessments to the exact candidate."""

from copy import deepcopy

import pytest

from editorteam.publication_review import (
    article_hash,
    entity_hints,
    handoff_hash,
    validate_factual,
    validate_handoff,
    validate_literary,
    validate_reviews,
)


@pytest.fixture
def bundle():
    handoff = {
        "schema_version": 1,
        "brief": "Проверка синтетического совета",
        "patch": "test-patch",
        "status": "research_ready",
        "style_profile": "guide",
        "sources": [
            {"source_id": "s", "url": "https://example.org/guide", "quote": "Исходная цитата"}
        ],
        "claims": [
            {
                "claim_id": "c",
                "meaning": "Иногда полезно сохранить ресурс.",
                "action": "Сохраните ресурс",
                "condition": "если нет угрозы",
                "exception": "кроме срочного ответа",
                "confidence": "medium",
                "patch": "test-patch",
                "status": "supported_with_conditions",
                "evidence_refs": ["s"],
            }
        ],
        "chapters": [
            {
                "chapter_id": "ch",
                "title": "Решение",
                "required_claim_ids": ["c"],
                "unresolved_questions": [],
            }
        ],
        "decisions": [
            {
                "question_id": "q",
                "chapter_id": "ch",
                "question": "Когда сохранить ресурс?",
                "required": True,
                "status": "answered",
                "claim_ids": ["c"],
            }
        ],
    }
    text = "Иногда полезно: Сохраните ресурс, если нет угрозы, кроме срочного ответа. [Источник](https://example.org/guide)"
    factual = {
        "article_sha256": article_hash(text),
        "handoff_sha256": handoff_hash(handoff),
        "status": "pass",
        "confidence_preserved": True,
        "patch_matches": True,
        "unsupported_claims": [],
        "conflicts": [],
        "claims": [
            {
                "claim_id": "c",
                "status": "supported",
                "action_quote": "Сохраните ресурс",
                "condition_quote": "если нет угрозы",
                "exception_quote": "кроме срочного ответа",
                "confidence_quote": "Иногда полезно",
                "evidence_refs": ["s"],
            }
        ],
    }
    literary = {
        "article_sha256": article_hash(text),
        "handoff_sha256": handoff_hash(handoff),
        "status": "pass",
        "dimensions": dict.fromkeys(
            ["usefulness", "coherence", "natural_russian", "author_voice"], "pass"
        ),
        "findings": [],
    }
    return handoff, text, factual, literary


def test_valid_independent_reports(bundle):
    h, text, fact, style = bundle
    assert validate_handoff(h, "test-patch") == []
    assert validate_reviews(h, text, fact, style) == []
    assert handoff_hash(h) == handoff_hash(dict(reversed(list(h.items()))))


@pytest.mark.parametrize("field", ["condition_quote", "exception_quote", "confidence_quote"])
def test_required_literal_attestation(bundle, field):
    h, text, fact, _ = bundle
    fact["claims"][0][field] = ""
    assert validate_factual(h, text, fact)
    fact["claims"][0][field] = "Выдуманная цитата"
    assert validate_factual(h, text, fact)


def test_amplified_confidence_report_and_unsupported_advice(bundle):
    h, text, fact, _ = bundle
    fact["confidence_preserved"] = False
    assert validate_factual(h, text, fact)
    fact["confidence_preserved"] = True
    fact["unsupported_claims"] = [{"quote": "Всегда покупайте"}]
    assert validate_factual(h, text, fact)


def test_wrong_patch_and_same_chapter_coverage(bundle):
    h, _, _, _ = bundle
    assert validate_handoff(h, "next-patch")
    h["chapters"].append({"chapter_id": "second", "title": "Вторая", "required_claim_ids": ["c"]})
    assert validate_handoff(h, "test-patch")
    h["decisions"][0]["status"] = "open"
    h["status"] = "research_ready_with_gaps"
    assert validate_handoff(h, "test-patch")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda h: h["sources"][0].update(url="https://user:secret@example.org/guide"),
        lambda h: h["sources"][0].update(quote=""),
        lambda h: h["claims"].append(deepcopy(h["claims"][0])),
        lambda h: h["claims"][0].update(evidence_refs=["missing"]),
        lambda h: h["claims"][0].update(condition=""),
        lambda h: h["decisions"][0].update(required="true"),
    ],
)
def test_handoff_malformed_is_closed(bundle, mutate):
    h, _, _, _ = bundle
    mutate(h)
    assert validate_handoff(h, "test-patch")


def test_prefix_url_spoof_is_not_a_citation(bundle):
    h, text, fact, _ = bundle
    text = text.replace("https://example.org/guide", "https://example.org/guide-attacker")
    fact["article_sha256"] = article_hash(text)
    assert validate_factual(h, text, fact)


def test_hash_drift_and_duplicate_attestations(bundle):
    h, text, fact, style = bundle
    assert validate_reviews(h, text + "!", fact, style)
    style["handoff_sha256"] = "wrong"
    assert validate_reviews(h, text, fact, style)
    fact["claims"].append(deepcopy(fact["claims"][0]))
    assert validate_factual(h, text, fact)


@pytest.mark.parametrize(
    "extra",
    [
        " 95% побед.",
        " [Источник](https://attacker.org)",
        '[hs_card id="TEST"]тишина[/hs_card]',
    ],
)
def test_new_entities_are_rejected_even_with_positive_model_report(bundle, extra):
    h, text, fact, _ = bundle
    text += extra
    fact["article_sha256"] = article_hash(text)
    assert validate_factual(h, text, fact)


def test_literary_finding_independent_from_fact_pass(bundle):
    h, text, fact, style = bundle
    style["findings"] = [
        {
            "severity": "error",
            "category": "coherence",
            "quote": "Сохраните ресурс",
            "reason": "Не объяснён выбор",
            "suggestion": "Добавить объяснение",
        }
    ]
    assert validate_factual(h, text, fact) == []
    assert validate_literary(text, style)
    style["findings"][0]["severity"] = "info"
    assert validate_literary(text, style) == []
    style["findings"][0]["quote"] = "В тексте этого нет"
    assert validate_literary(text, style)


@pytest.mark.parametrize("bad", [None, [], "bad", {"status": "pass"}])
def test_malformed_reports_return_errors_not_crashes(bundle, bad):
    h, text, _, _ = bundle
    assert validate_factual(h, text, bad)
    assert validate_literary(text, bad)
    assert validate_handoff(bad, "test-patch")


@pytest.mark.parametrize(
    "collection,field",
    [
        ("claims", "confidence"),
        ("claims", "status"),
        ("sources", "source_id"),
        ("claims", "evidence_refs"),
        ("chapters", "required_claim_ids"),
        ("decisions", "status"),
        ("decisions", "chapter_id"),
    ],
)
def test_nested_malformed_handoff_is_closed(bundle, collection, field):
    h, _, _, _ = bundle
    h[collection][0][field] = {}
    assert validate_handoff(h, "test-patch")


def test_nested_malformed_findings_are_closed(bundle):
    _, text, _, style = bundle
    style["findings"] = [{"severity": {}, "category": [], "quote": 10}]
    assert validate_literary(text, style)


def test_ordinal_list_composition_is_free(bundle):
    h, text, fact, _ = bundle
    text = "1. " + text
    fact["article_sha256"] = article_hash(text)
    assert validate_factual(h, text, fact) == []


def test_non_utf8_or_non_finite_data_is_closed(bundle):
    h, text, fact, style = bundle
    assert validate_factual(h, "\ud800", fact)
    assert validate_literary("\ud800", style)
    h["metadata"] = float("nan")
    assert validate_handoff(h, "test-patch")
    assert validate_reviews(h, text, fact, style)


def test_real_pilot_inflections_are_semantic_hints_not_invented_facts(bundle):
    h, text, fact, _ = bundle
    h["claims"][0]["meaning"] += " Налаа Искупительница. Колода Hearthstone."
    text += " Архивная статья Колоды Hearthstone упоминает Налаа Искупительницу."
    fact["article_sha256"] = article_hash(text)
    fact["handoff_sha256"] = handoff_hash(h)
    assert validate_factual(h, text, fact) == []
    hints = entity_hints(h, text)
    assert any("Налаа Искупительницу" in hint for hint in hints)
    assert any("Колоды Hearthstone" in hint for hint in hints)


def test_shortcode_names_can_inflect_but_id_and_type_cannot_change(bundle):
    h, text, fact, _ = bundle
    h["claims"][0]["meaning"] += ' [hs_card id="TEST"]Налаа Искупительница[/hs_card]'
    text += ' [hs_card id="TEST"]Налаа Искупительницу[/hs_card]'
    fact["article_sha256"] = article_hash(text)
    fact["handoff_sha256"] = handoff_hash(h)
    assert validate_factual(h, text, fact) == []
    for changed in (text.replace('id="TEST"', 'id="UNKNOWN"'), text.replace("hs_card", "hs_bg")):
        fact["article_sha256"] = article_hash(changed)
        assert validate_factual(h, changed, fact)


def test_idless_and_unknown_names_are_review_hints_never_trusted_evidence(bundle):
    h, text, fact, _ = bundle
    text += " [card]Непроверенная Карта[/card]"
    fact["article_sha256"] = article_hash(text)
    assert entity_hints(h, text)
    fact["unsupported_claims"] = [{"quote": "Непроверенная Карта", "reason": "No source support"}]
    assert validate_factual(h, text, fact)


@pytest.mark.parametrize("tag", ["hs_card", "hs_bg", "cardlink"])
def test_unknown_stable_ids_cannot_hide_behind_an_approved_name(bundle, tag):
    h, text, fact, _ = bundle
    h["claims"][0]["meaning"] += f' [{tag} id="KNOWN"]Налаа Искупительница[/{tag}]'
    text += f' [{tag} id="UNKNOWN"]Налаа Искупительница[/{tag}]'
    fact["article_sha256"] = article_hash(text)
    fact["handoff_sha256"] = handoff_hash(h)
    assert any("card_id" in error for error in validate_factual(h, text, fact))
