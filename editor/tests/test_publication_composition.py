"""Composition coverage is provenance, never an automatic quality verdict."""

from copy import deepcopy

import pytest

from editorteam.publication_composition import block_inventory, repair_brief, validate_coverage


def functions(text):
    return [
        {
            "block_id": block["block_id"],
            "block_sha256": block["sha256"],
            "quote": block["text"],
            "function": "Объяснение решения в контексте.",
            "disposition": "retain",
            "reason": "Связь с задачей читателя проверена.",
        }
        for block in block_inventory(text)["blocks"]
    ]


def test_inventory_preserves_every_nonwhitespace_character_and_duplicate_identity():
    text = '# Совет\r\n\r\nОдин и тот же абзац.\r\n\r\nОдин и тот же абзац.\r\n\r\n- Выбор\n- Условие\n\n> Цитата с советом.\n\n```text\n\nстрока кода\n```\n\n[hs_card id="42"]Карта[/hs_card]\n\n<div>Содержательный совет.</div>\n\nТекст с [hs_card id="42"]Карта[/hs_card] внутри.'
    inventory = block_inventory(text)
    covered = set()
    for block in inventory["blocks"]:
        assert text[block["start"] : block["end"]] == block["text"]
        indexes = set(range(block["start"], block["end"]))
        assert not indexes & covered
        covered |= indexes
    assert all(index in covered or char.isspace() for index, char in enumerate(text))
    duplicates = [block for block in inventory["blocks"] if block["text"] == "Один и тот же абзац."]
    assert len(duplicates) == 2
    assert duplicates[0]["sha256"] == duplicates[1]["sha256"]
    assert duplicates[0]["block_id"] != duplicates[1]["block_id"]
    assert {block["kind"] for block in inventory["blocks"]} >= {
        "heading",
        "prose",
        "list",
        "quote",
        "code",
        "shortcode",
    }
    assert validate_coverage(text, functions(text)) == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda rows: rows.pop(),
        lambda rows: rows.append(deepcopy(rows[0])),
        lambda rows: rows[0].update(block_id="phantom"),
        lambda rows: rows[0].update(block_sha256="0" * 64),
        lambda rows: rows[0].update(quote="Фразы нет в тексте."),
        lambda rows: rows[0].update(disposition="structural"),
    ],
)
def test_coverage_rejects_missing_duplicate_stale_or_ungrounded_rows(mutation):
    text = "Первый абзац.\n\nВторой абзац.\n\nТретий абзац."
    rows = functions(text)
    mutation(rows)
    assert validate_coverage(text, rows)


@pytest.mark.parametrize(
    "text",
    [
        "- Содержательный совет.",
        "> Содержательная цитата.",
        "<p>Содержательный HTML.</p>",
        'Совет с [hs_card id="42"]Карта[/hs_card] внутри.',
    ],
)
def test_prose_list_quote_html_and_inline_shortcode_cannot_skip_semantic_review(text):
    rows = functions(text)
    rows[0]["disposition"] = "structural"
    assert validate_coverage(text, rows)


def test_same_quote_in_other_block_does_not_cover_target():
    text = "Уникальный первый.\n\nУникальный второй."
    rows = functions(text)
    rows[0]["quote"] = "Уникальный второй."
    assert validate_coverage(text, rows)


def finding(quote):
    return {
        "severity": "warning",
        "category": "clarity",
        "quote": quote,
        "reason": "Неясен адресат совета.",
        "suggestion": "Уточнить адресата.",
        "benefit": "Читатель понимает, когда действовать.",
        "meaning_risk": "Не изменить условие.",
    }


def test_repair_targets_only_grounded_findings_and_marks_neighbors_as_context():
    text = "Первый абзац.\n\nСпорный совет.\n\nПоследний абзац."
    inventory = block_inventory(text)
    report = {
        "article_sha256": inventory["article_sha256"],
        "findings": [finding("Спорный совет."), finding("Выдуманная цитата.")],
    }
    brief = repair_brief(text, report, keep_spans=[{"quote": "Первый абзац.", "reason": "Ясно."}])
    assert [target["block_ids"] for target in brief["targets"]] == [["b0002"]]
    assert {block["block_id"] for block in brief["targets"][0]["neighbors"]} == {"b0001", "b0003"}
    assert all(block["context_only"] for block in brief["targets"][0]["neighbors"])
    assert len(brief["unresolved_targets"]) == 1
    assert brief["keep_spans"][0]["quote"] == "Первый абзац."
    report["article_sha256"] = "stale"
    assert repair_brief(text, report)["targets"] == []


def test_repair_does_not_guess_between_duplicate_quotes_or_trust_incomplete_findings():
    text = "Совет.\n\nСовет."
    report = {
        "article_sha256": block_inventory(text)["article_sha256"],
        "findings": [finding("Совет."), {"severity": "warning", "quote": "Совет."}],
    }
    brief = repair_brief(text, report)
    assert brief["targets"] == []
    assert len(brief["unresolved_targets"]) == 2


def test_revise_function_without_grounded_finding_requests_review_clarification():
    text = "Совет с условием."
    rows = functions(text)
    rows[0]["disposition"] = "revise"
    report = {
        "article_sha256": block_inventory(text)["article_sha256"],
        "paragraph_functions": rows,
    }
    assert validate_coverage(text, rows)
    brief = repair_brief(text, report)
    assert brief["targets"] == []
    assert brief["unresolved_targets"][0]["block_id"] == "b0001"
    assert "grounded finding" in brief["unresolved_targets"][0]["reason"]
    report["findings"] = [finding(text)]
    brief = repair_brief(text, report)
    assert brief["targets"][0]["block_ids"] == ["b0001"]
    assert brief["unresolved_targets"] == []


def test_structural_blocks_are_explicit_and_unclosed_fence_is_not_an_exemption():
    for text in ("# Заголовок", "```text\n\nexample\n```", '[hs_card id="42"]Карта[/hs_card]'):
        rows = functions(text)
        rows[0]["disposition"] = "structural"
        assert validate_coverage(text, rows) == []
    text = "```text\nНезакрытая вставка.\n\nСодержательный совет."
    assert block_inventory(text)["blocks"][0]["kind"] == "prose"
    rows = functions(text)
    rows[0]["disposition"] = "structural"
    assert validate_coverage(text, rows)


def test_repair_checks_require_current_handoff_and_valid_grounded_check_identity():
    text = "Содержательный совет."
    row = {"id": "invented", "status": "issue", **finding(text), "reader_problem": "Непонятно."}
    report = {
        "article_sha256": block_inventory(text)["article_sha256"],
        "handoff_sha256": "wrong",
        "practice_checks": [row],
    }
    assert repair_brief(text, report, expected_handoff_sha256="current")["targets"] == []
    assert repair_brief(text, report)["targets"] == []
    row["id"] = "substance"
    assert repair_brief(text, report)["targets"][0]["block_ids"] == ["b0001"]
    row["status"] = "unverified"
    assert repair_brief(text, report)["targets"] == []


@pytest.mark.parametrize("prefix", ["", "Вводный абзац.\n"])
def test_backtick_in_fence_info_cannot_exempt_prose_from_semantic_review(prefix):
    text = prefix + "```bad`info\nСодержательный совет.\n```"
    blocks = block_inventory(text)["blocks"]
    assert all(block["kind"] != "code" for block in blocks)
    rows = functions(text)
    for row in rows:
        row["disposition"] = "structural"
    assert validate_coverage(text, rows)


def test_tilde_fence_info_may_contain_a_backtick():
    text = "~~~bad`info\nexample\n~~~"
    assert block_inventory(text)["blocks"][0]["kind"] == "code"
    rows = functions(text)
    rows[0]["disposition"] = "structural"
    assert validate_coverage(text, rows) == []


@pytest.mark.parametrize("suffix", ["\u00a0", "\v"])
def test_non_ascii_or_vertical_whitespace_does_not_close_code_fence(suffix):
    text = "```text\nСодержательный совет.\n```" + suffix + "\n"
    assert block_inventory(text)["blocks"][0]["kind"] == "prose"
    rows = functions(text)
    rows[0]["disposition"] = "structural"
    assert validate_coverage(text, rows)


def test_spaces_and_tabs_before_crlf_close_code_fence():
    text = "```text\r\nexample\r\n``` \t \r\n"
    assert block_inventory(text)["blocks"][0]["kind"] == "code"
    rows = functions(text)
    rows[0]["disposition"] = "structural"
    assert validate_coverage(text, rows) == []


def test_nbsp_after_hash_does_not_exempt_prose_as_a_heading():
    text = "#\u00a0Содержательный совет."
    assert block_inventory(text)["blocks"][0]["kind"] == "prose"
    rows = functions(text)
    rows[0]["disposition"] = "structural"
    assert validate_coverage(text, rows)


@pytest.mark.parametrize("separator", [" ", "\t"])
def test_space_or_tab_after_hash_keeps_valid_heading(separator):
    text = "#" + separator + "Заголовок"
    assert block_inventory(text)["blocks"][0]["kind"] == "heading"
    rows = functions(text)
    rows[0]["disposition"] = "structural"
    assert validate_coverage(text, rows) == []
