import hashlib
import json
from pathlib import Path

import pytest

from editorteam.publication_run import export, init_run, next_task, revise, status, submit


def test_explicit_preferences_and_initial_task(tmp_path):
    run = tmp_path / "run"
    init_run(run, brief="Практический гайд", patch="test", profile="guide", shortcodes="off")
    assert next_task(run)["stage"] == "sources"
    assert status(run)["shortcodes"] == "off"
    with pytest.raises(ValueError):
        init_run(run, brief="Other", patch="test", profile="guide", shortcodes="off")
    with pytest.raises(ValueError):
        init_run(tmp_path / "bad", brief="Guide", patch="test", profile="guide", shortcodes="")


TEXT = "Сохраняйте ресурс при слабой позиции, кроме угрозы поражения. https://example.org/guide"


def write(tmp_path, name, value):
    path = tmp_path / name
    path.write_text(
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False), encoding="utf-8"
    )
    return path


def handoff():
    return {
        "schema_version": 1,
        "brief": "Практический совет",
        "patch": "test",
        "status": "research_ready",
        "style_profile": "guide",
        "sources": [{"source_id": "SRC-1", "url": "https://example.org/guide", "quote": TEXT}],
        "claims": [
            {
                "claim_id": "CLM-1",
                "meaning": "Сохранение ресурса",
                "action": "Сохраняйте ресурс",
                "condition": "при слабой позиции",
                "exception": "кроме угрозы поражения",
                "confidence": "high",
                "patch": "test",
                "status": "supported_with_conditions",
                "evidence_refs": ["SRC-1"],
            }
        ],
        "chapters": [{"chapter_id": "CH-1", "title": "Решение", "required_claim_ids": ["CLM-1"]}],
        "decisions": [
            {
                "question_id": "Q-1",
                "chapter_id": "CH-1",
                "question": "Когда сохранять ресурс?",
                "required": True,
                "status": "answered",
                "claim_ids": ["CLM-1"],
            }
        ],
    }


def prepared(tmp_path):
    run = tmp_path / "run"
    init_run(run, brief="Гайд", patch="test", profile="guide", shortcodes="off")
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
    submit(run, stage="research", artifact=write(tmp_path, "handoff.json", handoff()))
    submit(run, stage="draft", artifact=write(tmp_path, "draft.md", TEXT))
    return run


def reviews(run):
    task = next_task(run)
    hashes = {key: task[key] for key in ("article_sha256", "handoff_sha256")}
    factual = {
        **hashes,
        "status": "pass",
        "confidence_preserved": True,
        "candidate_checked": True,
        "patch_matches": True,
        "unsupported_claims": [],
        "conflicts": [],
        "claims": [
            {
                "claim_id": "CLM-1",
                "status": "supported",
                "action_quote": "Сохраняйте ресурс",
                "condition_quote": "при слабой позиции",
                "exception_quote": "кроме угрозы поражения",
                "evidence_refs": ["SRC-1"],
            }
        ],
    }
    literary = {
        **hashes,
        "status": "pass",
        "dimensions": dict.fromkeys(
            ("usefulness", "coherence", "natural_russian", "author_voice"), "pass"
        ),
        "findings": [],
        "strengths": [],
        "paragraph_functions": [{"quote": "Сохраняйте ресурс", "function": "Условный совет"}],
        "reader_check": {
            "action": "Сохранить ресурс",
            "reason": "Не расходовать сразу",
            "conditions": "Слабая позиция",
            "alternative": "Угроза поражения",
        },
        "whole_article_checked": True,
    }
    # Synthetic one-sentence evidence only; production never manufactures verdicts.
    from editorteam.editorial_practices import LOGIC, PRESERVATION, catalog

    for owner, report in (("fact_review", factual), ("literary_review", literary)):
        report["practice_checks"] = [
            {"id": p["id"], "status": "clear", "quote": TEXT,
             "reason": "Условный совет подтверждён единственным источником тестового примера."}
            for p in catalog()["practices"] if p["owner"] == owner
        ]
    for field, ids in (("logic_checks", LOGIC), ("preservation_checks", PRESERVATION)):
        literary[field] = [{"id": key, "status": "clear", "quote": TEXT,
                           "reason": "Совет, условие и исключение сохранены в одном предложении."}
                          for key in ids]
    factual["source_checks"] = [{"source_id": "SRC-1", "status": "verified",
        "evidence_quote": TEXT, "reason": "Прочитан тестовый snapshot.",
        "identity_check": "URL совпадает; библиографических идентификаторов нет.",
        "support_check": "Snapshot содержит весь условный совет.", "access": "snapshot"}]
    return factual, literary


def test_v3_missing_practice_blocks_native_flow_and_export(tmp_path):
    run = prepared(tmp_path)
    assert next_task(run)["review_contract_version"] == 3
    fact, _ = reviews(run)
    fact["practice_checks"].pop()
    result = submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    assert any("practice_checks: missing" in e for e in result["blocked"]["errors"])
    with pytest.raises(ValueError, match="both reviews"):
        export(run, output=tmp_path / "article.md")


def test_source_grounding_accepts_equivalent_urls_without_rewriting_sources():
    from editorteam.publication_run import _ground_sources

    source_handoff = handoff()
    source_handoff["sources"][0]["url"] = "https://EXAMPLE.org/guide"
    snapshots = [{"url": "https://example.org/guide", "text": TEXT}]
    assert _ground_sources(source_handoff, snapshots) == []
    assert source_handoff["sources"][0]["url"] == "https://EXAMPLE.org/guide"
    source_handoff["sources"][0]["url"] = "https://example.org/other"
    assert _ground_sources(source_handoff, snapshots)


def test_v2_receipts_remain_compatible(tmp_path):
    run = prepared(tmp_path)
    state_path = run / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["review_contract_version"] = 2
    state_path.write_text(json.dumps(state), encoding="utf-8")
    fact, literary = reviews(run)
    for report in (fact, literary):
        for field in ("practice_checks", "logic_checks", "preservation_checks", "source_checks"):
            report.pop(field, None)
    assert not submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))["blocked"]
    assert not submit(run, stage="literary_review", artifact=write(tmp_path, "lit.json", literary))["blocked"]
    export(run, output=tmp_path / "article.md")


def test_revision_carries_strengths_from_original_review(tmp_path):
    run = prepared(tmp_path)
    fact, literary = reviews(run)
    literary["strengths"] = [{"quote": "Сохраняйте ресурс", "reason": "Прямое действие"}]
    literary["dimensions"]["coherence"] = "needs_work"
    submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    submit(run, stage="literary_review", artifact=write(tmp_path, "lit.json", literary))
    assert next_task(run).get("keep_spans") == literary["strengths"]
    revise(run, artifact=write(tmp_path, "revised.md", "# Совет\n\n" + TEXT))
    assert next_task(run).get("keep_spans") == literary["strengths"]


def test_new_run_requires_extended_review_but_old_runs_remain_compatible(tmp_path):
    run = prepared(tmp_path)
    fact, literary = reviews(run)
    literary.pop("strengths")
    submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    result = submit(run, stage="literary_review", artifact=write(tmp_path, "lit.json", literary))
    assert result["blocked"]


def test_literary_reviewer_does_not_receive_factual_verdict(tmp_path):
    run = prepared(tmp_path)
    fact, _ = reviews(run)
    submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    task = next_task(run)
    assert task["stage"] == "literary_review"
    assert "fact_review" not in task["inputs"]
    assert {"research", "draft"} <= task["inputs"].keys()


def test_craft_guidance_reaches_applicable_stages_without_changing_evidence(tmp_path):
    run = prepared(tmp_path)
    fact, literary = reviews(run)
    factual_task = next_task(run)
    packet = factual_task["chapter_brief"]
    assert "craft_guidance" not in factual_task
    submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    task = next_task(run)
    assert task["craft_guidance"]["role"] == "review"
    assert task["craft_guidance"]["is_factual_evidence"] is False
    assert task["chapter_brief"] == packet
    assert "fact_review" not in task["inputs"]
    literary["dimensions"]["coherence"] = "needs_work"
    submit(run, stage="literary_review", artifact=write(tmp_path, "lit.json", literary))
    repair = next_task(run)
    assert repair["stage"] == "draft"
    assert repair["craft_guidance"]["role"] == "write"
    assert repair["chapter_brief"] == packet
    # A task is a fresh snapshot; a caller cannot change future task policy.
    repair["craft_guidance"]["principles"].clear()
    assert next_task(run)["craft_guidance"]["principles"]
    from editorteam.publication_run import craft_guidance
    for stage in ("sources", "research"):
        assert craft_guidance(stage)["role"] == "research"
        assert craft_guidance(stage)["is_factual_evidence"] is False
    assert craft_guidance("ready") is None


@pytest.mark.parametrize(
    "stage, expected",
    [("sources", ["research"]), ("research", ["research"]),
     ("draft", ["author", "prose"]), ("literary_review", ["author", "prose"])],
)
def test_editorial_passes_are_role_scoped_fresh_guidance(stage, expected):
    from editorteam.publication_run import craft_guidance

    guidance = craft_guidance(stage)
    assert [item["id"] for item in guidance["editorial_passes"]] == expected
    assert all(item["task"].strip() for item in guidance["editorial_passes"])
    assert guidance["is_factual_evidence"] is False
    guidance["editorial_passes"][0]["task"] = "changed by caller"
    assert craft_guidance(stage)["editorial_passes"][0]["task"] != "changed by caller"
    assert craft_guidance("fact_review") is None
    assert craft_guidance("ready") is None


def test_writer_packet_keeps_question_conditions_and_source_context(tmp_path):
    run = prepared(tmp_path)
    task = next_task(run)
    packet = task["chapter_brief"]
    assert packet["handoff_sha256"] == task["handoff_sha256"]
    chapter = packet["chapters"][0]
    assert chapter["questions"][0]["question"] == "Когда сохранять ресурс?"
    claim = chapter["claims"][0]
    assert claim["condition"] == "при слабой позиции"
    assert claim["exception"] == "кроме угрозы поражения"
    assert claim["evidence"][0]["quote"] == TEXT
    assert claim["evidence"][0]["url"] == "https://example.org/guide"
    assert "fact_review" not in packet
    # Derivation is read-only and deterministic, not a second mutable source.
    snapshot = (run / "state.json").read_bytes()
    assert next_task(run)["chapter_brief"] == packet
    assert (run / "state.json").read_bytes() == snapshot


def test_packet_preserves_optional_claims_and_research_limits():
    from editorteam.publication_run import chapter_brief

    bundle = handoff()
    bundle["claims"][0]["research_context"] = {
        "limitations": ["маленькая выборка"], "counterevidence": [{"quote": "Исключение"}]
    }
    bundle["claims"].append({**bundle["claims"][0], "claim_id": "CLM-2"})
    bundle["chapters"][0]["decision_cards"] = [{"question": "Альтернатива?", "gaps": []}]
    packet = chapter_brief(bundle)
    assert packet["chapters"][0]["claims"][0]["research_context"] == bundle["claims"][0]["research_context"]
    assert packet["chapters"][0]["decision_cards"] == bundle["chapters"][0]["decision_cards"]
    assert packet["additional_claims"][0]["claim_id"] == "CLM-2"
    packet["chapters"][0]["claims"][0]["condition"] = "changed"
    assert bundle["claims"][0]["condition"] == "при слабой позиции"


def test_legacy_run_resumes_without_new_review_fields(tmp_path):
    run = prepared(tmp_path)
    state = status(run)
    state.pop("review_contract_version")
    (run / "state.json").write_text(json.dumps(state), encoding="utf-8")
    fact, literary = reviews(run)
    for key in ("strengths", "paragraph_functions", "reader_check", "whole_article_checked"):
        literary.pop(key)
    submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    submit(run, stage="literary_review", artifact=write(tmp_path, "lit.json", literary))
    output = tmp_path / "legacy-final.md"
    export(run, output=output)
    assert output.read_text(encoding="utf-8") == TEXT


def test_shared_handoff_metadata_survives_saved_receipts_and_next_task(tmp_path):
    fixture = json.loads(
        (Path(__file__).resolve().parents[2] / "tests/fixtures/editorial-boundary.json").read_text(
            encoding="utf-8"
        )
    )
    h = fixture["handoff"]
    run = tmp_path / "run"
    init_run(run, brief=h["brief"], patch=h["patch"], profile=h["style_profile"], shortcodes="off")
    text = fixture["source_text"]
    rows = [
        {
            "id": "one",
            "source": "synthetic",
            "url": h["sources"][0]["url"],
            "text": text,
            "access": "full",
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "retrieved_at": "2026-10-19T00:00:00Z",
        }
    ]
    submit(run, stage="sources", artifact=write(tmp_path, "sources.json", rows))
    artifact = write(tmp_path, "handoff.json", h)
    submit(run, stage="research", artifact=artifact)
    for stage in ("draft", "fact_review"):
        task = next_task(run)
        assert task["stage"] == stage
        assert Path(task["inputs"]["research"]).read_bytes() == artifact.read_bytes()
        if stage == "draft":
            submit(run, stage="draft", artifact=write(tmp_path, "draft.md", text))


def test_uncollected_counterevidence_cannot_be_submitted(tmp_path):
    from editorteam.publication_run import _ground_sources

    fixture = json.loads(
        (Path(__file__).resolve().parents[2] / "tests/fixtures/editorial-boundary.json").read_text(
            encoding="utf-8"
        )
    )
    h = fixture["handoff"]
    h["claims"][0]["research_context"]["counterevidence"][0]["quote"] = (
        "A never-collected objection."
    )
    assert _ground_sources(h, [{"url": h["sources"][0]["url"], "text": fixture["source_text"]}])


def test_entity_hints_reach_reviewer_without_approving_a_draft(tmp_path):
    run = prepared(tmp_path)
    revise(run, artifact=write(tmp_path, "with-name.md", TEXT + " Новая Карта"))
    task = next_task(run)
    assert any("Новая Карта" in hint for hint in task["entity_hints"])
    assert "Непроверенные" in task["entity_hints_policy"]
    assert task["role"] == "independent_fact_reviewer"
    with pytest.raises(ValueError, match="both reviews"):
        export(run, output=tmp_path / "final.md")
    factual, _ = reviews(run)
    factual["unsupported_claims"] = ["Новая Карта не подтверждена источником"]
    state = submit(run, stage="fact_review", artifact=write(tmp_path, "rejected.json", factual))
    assert state["blocked"]
    assert state["stage"] == "fact_review"


def test_sequential_submission_and_export_are_real_receipts(tmp_path):
    run = prepared(tmp_path)
    with pytest.raises(ValueError):
        export(run, output=tmp_path / "final.md")
    fact, literary = reviews(run)
    with pytest.raises(ValueError):
        submit(run, stage="literary_review", artifact=write(tmp_path, "literary.json", literary))
    submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    submit(run, stage="literary_review", artifact=tmp_path / "literary.json")
    assert status(run)["stage"] == "ready"
    export(run, output=tmp_path / "final.md")
    assert (tmp_path / "final.md").read_text(encoding="utf-8") == TEXT
    with pytest.raises(FileExistsError):
        export(run, output=tmp_path / "final.md")


def test_review_loss_requires_revision_and_keeps_rejected_report(tmp_path):
    run = prepared(tmp_path)
    fact, _ = reviews(run)
    fact["claims"][0]["condition_quote"] = "Несуществующая цитата"
    result = submit(run, stage="fact_review", artifact=write(tmp_path, "bad.json", fact))
    assert result["blocked"]
    assert result["history"][-1]["accepted"] is False
    assert next_task(run)["stage"] == "draft"
    revised = write(tmp_path, "revision.md", "# Совет\n\n" + TEXT)
    result = revise(run, artifact=revised)
    assert result["stage"] == "fact_review"
    assert "fact_review" not in result["artifacts"]
    assert result["history"][-2]["accepted"] is False
    assert (run / result["history"][-2]["path"]).read_text(encoding="utf-8")
    revise(run, artifact=write(tmp_path, "revision2.md", "# Другой заголовок\n\n" + TEXT))
    with pytest.raises(ValueError, match="budget"):
        revise(run, artifact=revised)


def test_stale_review_and_artifact_drift_fail_closed(tmp_path):
    run = prepared(tmp_path)
    fact, _ = reviews(run)
    fact["article_sha256"] = "0" * 64
    result = submit(run, stage="fact_review", artifact=write(tmp_path, "stale.json", fact))
    assert result["blocked"]
    stored = run / result["artifacts"]["draft"]["path"]
    stored.write_text("drift", encoding="utf-8")
    with pytest.raises(ValueError, match="drift"):
        next_task(run)


def test_handoff_sources_need_real_full_text_quotes(tmp_path):
    run = tmp_path / "run"
    init_run(run, brief="Гайд", patch="test", profile="guide", shortcodes="off")
    rows = [
        {
            "id": "one",
            "source": "mcp",
            "url": "https://example.org/guide",
            "text": "Other text",
            "access": "full",
            "sha256": hashlib.sha256(b"Other text").hexdigest(),
            "retrieved_at": "2026-10-10T12:00:00Z",
        }
    ]
    submit(run, stage="sources", artifact=write(tmp_path, "sources.json", rows))
    with pytest.raises(ValueError, match="source quote"):
        submit(run, stage="research", artifact=write(tmp_path, "handoff.json", handoff()))


def test_receipt_paths_cannot_escape_run(tmp_path):
    run = prepared(tmp_path)
    state = status(run)
    state["history"][0]["path"] = "../sources.json"
    state["artifacts"]["sources"]["path"] = "../sources.json"
    (run / "state.json").write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="escapes"):
        status(run)


@pytest.mark.parametrize("bad", ["hash", "provenance", "excerpt"])
def test_sources_cannot_hide_missing_provenance_or_partial_content(tmp_path, bad):
    run = tmp_path / "run"
    init_run(run, brief="Гайд", patch="test", profile="guide", shortcodes="off")
    row = {
        "id": "one",
        "source": "mcp",
        "url": "https://example.org/guide",
        "text": TEXT,
        "access": "full",
        "sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
        "retrieved_at": "2026-10-10T12:00:00Z",
    }
    if bad == "hash":
        row["sha256"] = "0" * 64
    elif bad == "provenance":
        row["retrieved_at"] = None
    else:
        row["access"] = "excerpt"
    with pytest.raises(ValueError):
        submit(run, stage="sources", artifact=write(tmp_path, "bad.json", [row]))
    assert status(run)["history"] == []


def test_missing_condition_and_missing_citation_cannot_pass(tmp_path):
    run = prepared(tmp_path)
    revised = TEXT.replace("при слабой позиции, ", "").replace(" https://example.org/guide", "")
    revise(run, artifact=write(tmp_path, "missing.md", revised))
    fact, _ = reviews(run)
    result = submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    assert result["blocked"]
    assert any("condition" in error for error in result["blocked"]["errors"])
    assert any("cited" in error for error in result["blocked"]["errors"])


def test_revision_clears_both_reviews_and_preserves_export_and_draft_history(tmp_path):
    run = prepared(tmp_path)
    fact, literary = reviews(run)
    submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    submit(run, stage="literary_review", artifact=write(tmp_path, "literary.json", literary))
    export(run, output=tmp_path / "final.md")
    old = status(run)
    revised = revise(run, artifact=write(tmp_path, "revision.md", "# Совет\n\n" + TEXT))
    assert set(revised["artifacts"]) == {"sources", "research", "draft"}
    assert revised["export"] is None
    assert len(revised["export_history"]) == 1
    assert (tmp_path / "final.md").read_text(encoding="utf-8") == TEXT
    for receipt in old["history"]:
        assert receipt in revised["history"]
        assert (run / receipt["path"]).exists()
    with pytest.raises(ValueError):
        export(run, output=tmp_path / "revised-final.md")


def test_active_operation_lock_prevents_overlapping_mutations(tmp_path):
    run = prepared(tmp_path)
    (run / ".publication.lock").write_text("active", encoding="utf-8")
    with pytest.raises(ValueError, match="locked"):
        revise(run, artifact=write(tmp_path, "revision.md", "# Совет\n\n" + TEXT))
    assert (run / ".publication.lock").read_text(encoding="utf-8") == "active"


def test_bad_report_can_be_rechecked_once_without_changing_good_draft(tmp_path):
    run = prepared(tmp_path)
    fact, _ = reviews(run)
    stale = {**fact, "article_sha256": "0" * 64}
    rejected = submit(run, stage="fact_review", artifact=write(tmp_path, "stale.json", stale))
    assert rejected["blocked"]
    retried = submit(
        run, stage="fact_review", artifact=write(tmp_path, "correct.json", fact), retry_review=True
    )
    assert retried["stage"] == "literary_review"
    assert retried["blocked"] is None
    assert retried["draft_revisions"] == 0
    assert retried["history"][-2]["accepted"] is False


def test_review_recheck_budget_is_bound_to_stage_and_draft_version(tmp_path):
    run = prepared(tmp_path)
    fact, _ = reviews(run)
    fact["status"] = "repair"
    report = write(tmp_path, "bad.json", fact)
    submit(run, stage="fact_review", artifact=report)
    submit(run, stage="fact_review", artifact=report, retry_review=True)
    with pytest.raises(ValueError, match="recheck budget"):
        submit(run, stage="fact_review", artifact=report, retry_review=True)
    assert len(status(run)["history"]) == 5
    revise(run, artifact=write(tmp_path, "revision.md", "# Совет\n\n" + TEXT))
    assert status(run)["review_retries"]["fact_review"] == 0


@pytest.mark.parametrize(
    "other_url", ["https://example.org/guide/", "https://example.org/guide#other"]
)
def test_source_grounding_does_not_trust_unverified_url_aliases(tmp_path, other_url):
    run = tmp_path / "run"
    init_run(run, brief="Гайд", patch="test", profile="guide", shortcodes="off")
    rows = [
        {
            "id": "one",
            "source": "mcp",
            "url": other_url,
            "text": TEXT,
            "access": "full",
            "sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
            "retrieved_at": "2026-10-10T12:00:00Z",
        }
    ]
    submit(run, stage="sources", artifact=write(tmp_path, "sources.json", rows))
    with pytest.raises(ValueError, match="source quote"):
        submit(run, stage="research", artifact=write(tmp_path, "handoff.json", handoff()))


@pytest.mark.parametrize("change", ["missing", "changed"])
def test_external_export_change_does_not_break_resuming_run(tmp_path, change):
    run = prepared(tmp_path)
    fact, literary = reviews(run)
    submit(run, stage="fact_review", artifact=write(tmp_path, "fact.json", fact))
    submit(run, stage="literary_review", artifact=write(tmp_path, "literary.json", literary))
    output = tmp_path / "final.md"
    export(run, output=output)
    if change == "missing":
        output.unlink()
    else:
        output.write_text("User edit", encoding="utf-8")
    assert status(run)["export_status"] == change
    assert next_task(run)["stage"] == "ready"
    export(run, output=tmp_path / "restored.md")
    assert (tmp_path / "restored.md").read_text(encoding="utf-8") == TEXT
    revise(run, artifact=write(tmp_path, "revision.md", "# Совет\n\n" + TEXT))


@pytest.mark.parametrize("invalid", [[], None, {"schema_version": 1, "stage": "ready"}])
def test_malformed_state_returns_controlled_error(tmp_path, invalid):
    run = tmp_path / "run"
    init_run(run, brief="Гайд", patch="test", profile="guide", shortcodes="off")
    (run / "state.json").write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ValueError, match="state"):
        status(run)


def test_saved_research_cannot_be_relabelled_with_a_new_patch(tmp_path):
    run = prepared(tmp_path)
    state = status(run)
    state["patch"] = "new-patch"
    (run / "state.json").write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="patch"):
        next_task(run)


@pytest.mark.parametrize(
    "field,value",
    [
        ("shortcodes", []),
        ("review_retries", {"fact_review": 0, "literary_review": 0, "other": "bad"}),
        ("stage", "sources"),
    ],
)
def test_invalid_state_control_fields_fail_closed(tmp_path, field, value):
    run = prepared(tmp_path)
    state = status(run)
    state[field] = value
    (run / "state.json").write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="state"):
        status(run)
