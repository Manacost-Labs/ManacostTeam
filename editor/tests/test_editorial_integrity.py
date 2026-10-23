"""Concrete regressions from the article audit, without phrase blacklists."""
import hashlib
import json

import pytest

from editorteam import rules
from editorteam.editorial_practices import prepare, validate
from editorteam.server import analyze
from editorteam.server import validate as validate_edit


def preserved_review(original, candidate):
    from test_editorial_practices import assessment
    result = assessment("all", candidate)
    result["original_sha256"] = prepare(candidate, original=original)["original_sha256"]
    result["source_checks"] = []
    result["source_verification"] = "not_performed"
    result["original_factual_checks"] = {"whole_text_checked": True, "internal_consistency": "clear",
        "source_agreement": "not_performed", "issues": []}
    for row in result["preservation_checks"]:
        row["original_quote"] = original
        if original != candidate and row["id"] in {"author_voice", "strengths"}:
            row["change_evidence"] = [{"original_quote": original, "quote": candidate,
                "disposition": "preserved", "reason": "Смысл и авторское обращение сохранены.",
                "benefit": "Устранена опечатка.", "meaning_risk": "Проверено сохранение конкретного предмета совета."}]
    return result


def test_preserved_bad_win_record_is_not_a_validated_fact():
    text = "Игрок взял Легенду со счетом 22-7 (71% винрейта)."
    result = validate_edit(text, text, "hearthstone", "news")
    assert not result["accepted"]
    problem = next(row for row in result["violations"] if row["kind"] == "ARITHMETIC_INCONSISTENCY")
    assert problem["evidence"] in text and "22-7" in problem["evidence"]
    assert "источник" in problem["suggestion"].lower()
    assert "75.86" in problem["message"]


@pytest.mark.parametrize("text", [
    "Игрок закончил со счетом 22-7 (76% винрейта).",
    "На ходах 5-7 план меняется; винрейт колоды — 71%.",
    "Игрок закончил со счетом 0-0 (0% винрейта).",
    "Игрок закончил со счетом 39-16 (примерно 70% побед).",
])
def test_arithmetic_guard_does_not_invent_win_records(text):
    result = analyze(text, "hearthstone", "news")
    assert not [row for row in result["findings"] if row["id"] == "ARITHMETIC_INCONSISTENCY"]


def test_analyzer_and_review_packet_show_original_arithmetic_issue():
    text = "Результат со счетом 22-7 (71% побед)."
    result = analyze(text, "hearthstone", "news")
    assert any(row["id"] == "ARITHMETIC_INCONSISTENCY" for row in result["findings"])
    assert prepare(text, original=text)["original_integrity_hints"]


def test_diagnostic_pass_cannot_claim_publication_readiness():
    text = "Сохраните ресурс, если нет угрозы."
    result = validate_edit(text, text, "hearthstone", "news")
    assert result["review_scope"] == "diagnostics_only"
    assert result["independent_review_required"] is True
    assert result["publication_ready"] is False
    assert result["source_verification"] == "not_performed"


def test_corpus_only_terms_are_advisory_but_localization_norms_remain():
    from editorteam.server import rules_for as prompt_rules
    selected = {row.id: row for row in rules.terminology()}
    assert selected["term.spell"].decision == "advisory"
    assert selected["term.minion"].decision == "advisory"
    assert selected["term.deck"].replacement_for("дека") is None
    packet = prompt_rules("hearthstone", "news")
    assert not {"спел", "миньон", "дека"} & {row["from"] for row in packet["replace"]}
    assert {"спел", "миньон"} <= {row["from"] for row in packet["terminology_advice"]}
    assert any(row["to"] == "Алмаз" for row in packet["replace"])


@pytest.mark.parametrize("original,candidate", [
    ("Появится больше подробностей о мире игры.", "Появится больше подробностей."),
    ("Сборка показывает хорошие результаты по статистике.", "Сборка показывает хорошие результаты."),
])
def test_substantive_loss_cannot_pass_without_contextual_changed_span_review(original, candidate):
    review = preserved_review(original, candidate)
    review["preservation_checks"][-1].pop("change_evidence")
    assert any("change_evidence" in error for error in validate(candidate, review, original=original))
    review = preserved_review(original, candidate)
    review["preservation_checks"][-1]["change_evidence"][0]["disposition"] = "issue"
    assert any("unresolved" in error for error in validate(candidate, review, original=original))


def test_contextual_rephrase_does_not_require_banned_or_mandatory_words():
    original = "По статистике спелл хорошо показывает себя на этом ранге."
    candidate = "На этом ранге спелл показывает хорошие результаты по данным отчёта."
    review = preserved_review(original, candidate)
    assert validate(candidate, review, original=original) == []


def test_unchanged_text_requires_separate_original_fact_review():
    original = "Спелл может помочь, если есть ресурс."
    review = preserved_review(original, original)
    assert validate(original, review, original=original) == []
    del review["original_factual_checks"]
    assert any("original_factual_checks" in error for error in validate(original, review, original=original))


def test_full_preservation_review_requires_explicit_positive_verdict():
    text = "Спелл может помочь."
    review = preserved_review(text, text)
    del review["status"]
    assert any("did not pass" in error for error in validate(text, review, original=text))


@pytest.mark.parametrize("field", ["internal_consistency", "source_agreement"])
def test_malformed_original_fact_status_fails_closed(field):
    text = "Спелл может помочь."
    review = preserved_review(text, text)
    review["original_factual_checks"][field] = []
    assert validate(text, review, original=text)


def test_arithmetic_cannot_be_silently_repaired_from_calculation_alone():
    original = "Игрок взял Легенду со счетом 22-7 (71% винрейта)."
    candidate = original.replace("71%", "76%")
    review = preserved_review(original, candidate)
    review["original_factual_checks"] = {"whole_text_checked": True, "internal_consistency": "issue",
        "source_agreement": "not_performed", "issues": [{"quote": original, "reason": "Процент не соответствует счету.",
        "resolution": "corrected", "correction_quote": candidate, "source_id": "", "evidence_quote": ""}]}
    assert any("full source evidence" in error for error in validate(candidate, review, original=original))


def test_validate_route_can_verify_bound_review_but_rejects_stale_receipt():
    text = "Спелл может помочь, если есть ресурс."
    review = preserved_review(text, text)
    accepted = validate_edit(text, text, "hearthstone", "news", editorial_review=review)
    assert accepted["accepted"] and accepted["independent_review_validated"]
    assert accepted["source_verification"] == "not_performed"
    review["article_sha256"] = "stale"
    blocked = validate_edit(text, text, "hearthstone", "news", editorial_review=review)
    assert not blocked["accepted"] and blocked["independent_review_required"]


@pytest.mark.parametrize("snapshots", [[None], [1], {}, [], [{"url": "bad"}]])
def test_bad_supplied_evidence_fails_closed_without_traceback(snapshots):
    text = "Спелл может помочь."
    assert validate(text, preserved_review(text, text), original=text, snapshots=snapshots)


def test_direct_rewrite_helper_cannot_accept_same_arithmetic_error():
    import common as C

    violations, _, _ = C.sibling("rewrite_gate").analyze(
        "Со счетом 22-7 (71% винрейта).", profile="news")
    assert any(row["kind"] == "ARITHMETIC_INCONSISTENCY" for row in violations)


def test_native_repair_review_requires_original_checks_and_change_evidence(tmp_path):
    from test_publication_run import TEXT, prepared, reviews, write

    from editorteam.publication_run import next_task, revise, submit

    run = prepared(tmp_path)
    revise(run, artifact=write(tmp_path, "revised.md", "# Совет\n\n" + TEXT))
    task = next_task(run)
    assert task["original"] == TEXT
    assert task["editorial_practices"]["original_sha256"]
    factual, _ = reviews(run)
    del factual["original_factual_checks"]
    rejected = submit(run, stage="fact_review", artifact=write(tmp_path, "no-original.json", factual))
    assert any("original_factual_checks" in error for error in rejected["blocked"]["errors"])


def source_correction_review(original, candidate, corrections):
    from test_publication_run import handoff

    review = preserved_review(original, candidate)
    bundle = handoff()
    bundle["sources"][0]["quote"] = candidate
    bundle["claims"][0]["meaning"] = candidate
    snapshots = [{"id": "snapshot", "source": "fixture", "url": "https://example.org/guide",
        "text": candidate, "access": "full", "sha256": hashlib.sha256(candidate.encode()).hexdigest(),
        "retrieved_at": "2026-10-23T12:00:00Z"}]
    packet = prepare(candidate, original=original, handoff=bundle, snapshots=snapshots)
    review.update({key: packet[key] for key in ("article_sha256", "original_sha256", "handoff_sha256", "sources_sha256")})
    review.update(candidate_checked=True, confidence_preserved=True, patch_matches=True,
        unsupported_claims=[], conflicts=[], claims=[{"claim_id": "CLM-1", "status": "supported",
        "action_quote": "Сохраняйте ресурс", "condition_quote": "при слабой позиции",
        "exception_quote": "кроме угрозы поражения", "evidence_refs": ["SRC-1"]}])
    review["source_checks"] = [{"source_id": "SRC-1", "status": "verified", "evidence_quote": candidate,
        "reason": "Прочитан полный snapshot.", "identity_check": "Адрес соответствует handoff.",
        "support_check": "Исправление подтверждено точной цитатой.", "access": "snapshot"}]
    review["original_factual_checks"] = {"whole_text_checked": True, "internal_consistency": "clear",
        "source_agreement": "issue", "issues": [{"quote": before, "correction_quote": after,
        "reason": "Исходное значение расходится с источником.", "resolution": "corrected",
        "source_id": "SRC-1", "evidence_quote": after} for before, after in corrections]}
    return review, bundle, snapshots


def test_source_proved_number_correction_passes_python_validate_and_cli(tmp_path, capsys):
    from test_publication_run import TEXT

    from editorteam.cli import main

    original = "Стоимость карты — 4 маны. " + TEXT
    candidate = "Стоимость карты — 3 маны. " + TEXT
    review, handoff, snapshots = source_correction_review(original, candidate,
        [("Стоимость карты — 4 маны.", "Стоимость карты — 3 маны.")])
    result = validate_edit(original, candidate, "hearthstone", "news", editorial_review=review,
        source_handoff=handoff, source_snapshots=snapshots)
    assert result["accepted"], result
    assert result["independent_review_validated"] and result["source_verification"] == "supplied_sources_checked"
    assert review["original_sha256"] == hashlib.sha256(original.encode()).hexdigest()
    paths = {}
    for name, value in {"before": original, "after": candidate, "review": review,
                        "handoff": handoff, "sources": snapshots}.items():
        paths[name] = tmp_path / name
        paths[name].write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    assert main(["validate-edit", str(paths["before"]), str(paths["after"]), "--profile", "news",
        "--review", str(paths["review"]), "--handoff", str(paths["handoff"]), "--sources", str(paths["sources"]),
        "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["accepted"]


def test_verified_correction_does_not_excuse_an_unrelated_number_change():
    from test_publication_run import TEXT

    original = "Стоимость карты — 4 маны. Запас — 8 монет. " + TEXT
    candidate = "Стоимость карты — 3 маны. Запас — 9 монет. " + TEXT
    review, handoff, snapshots = source_correction_review(original, candidate,
        [("Стоимость карты — 4 маны.", "Стоимость карты — 3 маны.")])
    result = validate_edit(original, candidate, "hearthstone", "news", editorial_review=review,
        source_handoff=handoff, source_snapshots=snapshots)
    assert result["independent_review_validated"]
    assert not result["accepted"]
    assert any(row["kind"] in {"protected_lost", "FACTUAL_SEMANTIC_DRIFT"} for row in result["violations"])


@pytest.mark.parametrize("repeated,overlap", [(True, False), (False, True)])
def test_correction_quotes_must_identify_unique_nonoverlapping_original_spans(repeated, overlap):
    from test_publication_run import TEXT

    before_clause, after_clause = "Стоимость карты — 4 маны. ", "Стоимость карты — 3 маны. "
    original = before_clause * (2 if repeated else 1) + TEXT
    candidate = after_clause * (2 if repeated else 1) + TEXT
    corrections = [(before_clause.strip(), after_clause.strip())]
    if overlap:
        corrections.append(("карты — 4 маны.", "карты — 3 маны."))
    review, handoff, snapshots = source_correction_review(original, candidate, corrections)
    result = validate_edit(original, candidate, "hearthstone", "news", editorial_review=review,
        source_handoff=handoff, source_snapshots=snapshots)
    assert not result["accepted"] and not result["independent_review_validated"]
    assert any("unique" in error or "overlap" in error for error in result["editorial_review_errors"])
    assert "diagnostic_baseline_sha256" not in result


def test_invalid_source_snapshot_never_authorizes_corrected_baseline():
    from test_publication_run import TEXT

    original = "Стоимость карты — 4 маны. " + TEXT
    candidate = "Стоимость карты — 3 маны. " + TEXT
    review, handoff, snapshots = source_correction_review(original, candidate,
        [("Стоимость карты — 4 маны.", "Стоимость карты — 3 маны.")])
    snapshots[0]["sha256"] = "fabricated"
    result = validate_edit(original, candidate, "hearthstone", "news", editorial_review=review,
        source_handoff=handoff, source_snapshots=snapshots)
    assert not result["accepted"] and not result["independent_review_validated"]
    assert "diagnostic_baseline_sha256" not in result


def test_private_baseline_replacements_do_not_cascade():
    from editorteam.editorial_practices import _corrected_original

    ledger = {"original_factual_checks": {"issues": [
        {"quote": "A", "correction_quote": "B", "resolution": "corrected"},
        {"quote": "B", "correction_quote": "C", "resolution": "corrected"},
    ]}}
    assert _corrected_original("First A. Second B.", ledger) == "First B. Second C."
