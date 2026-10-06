"""Типографика: Typograf в узком коридоре — тире и пробелы, слова и разметка нетронуты."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from editorteam import typography as T
from editorteam.card_shortcodes import apply_shortcodes
from editorteam.cli import main
from editorteam.wordpress import Card, HearthstoneFormat

NBSP = "\u00a0"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="нужен Node.js для Typograf")

HOUSE = {
    "quotes": {"decision": "straight"},
    "dashes": {"primary": "—", "normalize_en_to_em": True},
    "numbers": {"range": {"decision": "hyphen"}},
}
NAMES = ("Рыцарь на коне", "Кел'Тузад", "Музыкальный менеджер E.T.C.")
CATALOG = tuple(
    Card(name, f"TEST_{number:03d}", frozenset({HearthstoneFormat.WILD}))
    for number, name in enumerate(NAMES, 1)
)
SAMPLE = (
    "Рыцарь на коне - сильная карта, а Кел'Тузад и Музыкальный менеджер E.T.C. "
    'в 2-3 хода берут "добор". Статы 1/2 и 3/4 остаются, т.е. без дробей...'
)


def fake_runner(text, enabled):
    """Typograf на минималках: «слово - слово» → «слово—слово» с неразрывным пробелом."""
    return text.replace(" - ", f"{NBSP}— "), "fake"


# ── заглушки и защита ─────────────────────────────────────────────────────


def test_protect_and_restore_are_exact():
    text = (
        "---\ntitle: А - Б\n---\n# Заголовок - с тире\n\n"
        "```python\nx = 'a - b'\n```\n"
        "- пункт [ссылка](https://example.com/a--b) и `код - тут`\n"
        '[hs_card id="X_001"]Рыцарь на коне[/hs_card] - карта.\n'
    )
    masked = T.protect(text, NAMES)
    assert "https://" not in masked.text and "```" not in masked.text
    assert "title" not in masked.text and "Заголовок" not in masked.text
    assert masked.restore(masked.text) == text


@pytest.mark.parametrize(
    ("snippet", "kept"),
    [
        ("```\nа - б\n```", "а - б"),
        ("~~~\nа - б\n~~~", "а - б"),
        ("```\nа - б без закрытия", "а - б без закрытия"),
        ("`а - б`", "а - б"),
        ("см. https://example.com/a - b?x=1--2", "https://example.com/a"),
        ("[текст](https://example.com/a--b)", "https://example.com/a--b"),
        ('[hs_card id="CARD_1" x="a - b"]', 'id="CARD_1"'),
        ("# Заголовок - с тире", "Заголовок"),
        ("> чужая цитата - как есть", "чужая цитата"),
        ("<p class='a - b'>", "class="),
        ("a &nbsp; b", "&nbsp;"),
        ("AAECAZ8FHo0DxALhAvwCpQSPBeoF8gXkBvAGnQe8B5kIgQmlCbEK", "AAECAZ8F"),
        ("|---|---|", "|---|"),
        ("<!-- а - б -->", "а - б"),
    ],
)
def test_markup_is_masked(snippet, kept):
    masked = T.protect(f"слово\n{snippet}\nслово")
    assert kept not in masked.text


def test_list_marker_is_masked_but_item_text_is_not():
    masked = T.protect("- пункт один\n  * вложенный\n1. номер\n")
    assert "пункт один" in masked.text and "вложенный" in masked.text and "номер" in masked.text
    assert not any(line.lstrip().startswith(("-", "*", "1.")) for line in masked.text.split("\n"))


def test_shortcode_tags_are_masked_but_card_name_inside_follows_catalog():
    text = '[hs_card id="X_001"]Рыцарь на коне[/hs_card] и Рыцарь на коне'
    assert "hs_card" not in T.protect(text).text
    assert "Рыцарь" in T.protect(text).text  # без каталога имя — обычный текст
    assert "Рыцарь" not in T.protect(text, NAMES).text


def test_card_names_match_whole_words_only_and_prefer_longest():
    names = ("Рыцарь", "Рыцарь на коне")
    assert T.protect("Рыцарь на коне.", names).saved == ("Рыцарь на коне",)
    assert T.protect("Рыцарями и Рыцарь.", names).saved == ("Рыцарь",)
    assert T.protect("Рыцарь на коне.", ("Рыцарь на конец",)).saved == ()


def test_placeholder_prefix_avoids_collision_with_text():
    masked = T.protect("Qzx000000xzQ и `код`")
    assert masked.prefix != "Qzx"
    assert masked.restore(masked.text) == "Qzx000000xzQ и `код`"


def test_damaged_placeholders_are_refused():
    masked = T.protect("`а` и `б`")
    with pytest.raises(T.TypographyError, match="заглушки"):
        masked.restore(masked.text.replace(masked.text.split()[0], "", 1))


# ── проверка «изменились только пробелы и тире» ──────────────────────────


@pytest.mark.parametrize(
    "after",
    [
        "Мир — мой мир",
        f"Мир{NBSP}— мой{NBSP}мир",
        "Мир – мой мир",
        "Мир -- мой мир",
    ],
)
def test_verify_accepts_spaces_replaced_and_dashes_changed(after):
    assert T.verify("Мир - мой мир", after) == []


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("Существо 1/2 с 3/4", "Существо ½ с 3/4"),
        ("Существо 1/2 с 3/4...", "Существо 1/2 с 3/4…"),
        ("Дрек'Тар", "Дрек’Тар"),
        ("Мир мой мир", "Мир, мой мир"),
        ("Мир мой мир", 'Мир "мой" мир'),
        ("т.е. так", "т. е. так"),  # пробел появился
        ("Мир  мой", "Мир мой"),  # пробел пропал
    ],
)
def test_verify_rejects_anything_but_replaced_spaces_and_dashes(before, after):
    assert T.verify(before, after)


def test_verify_rejects_lost_or_added_lines_and_allows_quotes_only_when_asked():
    assert T.verify("а\nб", "а б")
    assert T.verify('"слово"', "«слово»")
    assert T.verify('"слово"', "«слово»", quotes=True) == []


# ── набор правил по решениям издания ─────────────────────────────────────


def test_house_style_enables_only_dashes_and_nbsp():
    enabled = T.enabled_rules(HOUSE)
    assert "ru/dash/main" in enabled
    assert "common/punctuation/quote" not in enabled
    assert set(enabled) == {*T.DASH_RULES, *T.NBSP_RULES}


def test_guillemets_decision_adds_quote_rule_and_dash_switch_removes_dash_rule():
    guillemets = {**HOUSE, "quotes": {"decision": "guillemets"}}
    assert "common/punctuation/quote" in T.enabled_rules(guillemets)
    no_dash = {**HOUSE, "dashes": {"primary": "—", "normalize_en_to_em": False}}
    assert "ru/dash/main" not in T.enabled_rules(no_dash)


def test_default_rules_follow_config_file():
    assert T.enabled_rules() == T.enabled_rules(HOUSE)


def test_rules_that_change_meaning_are_never_enabled():
    variants = [HOUSE, {**HOUSE, "quotes": {"decision": "guillemets"}}, {}]
    for decisions in variants:
        assert not set(T.enabled_rules(decisions)) & set(T.NEVER)
    assert "common/number/fraction" in T.NEVER


# ── стадия целиком, без Node ──────────────────────────────────────────────


def test_typograph_with_runner_counts_changes_and_keeps_protected_text():
    text = "Рыцарь на коне - карта.\n`a - b`\nПусто.\n"
    result = T.typograph(text, decisions=HOUSE, names=NAMES, runner=fake_runner)
    assert result.text == f"Рыцарь на коне{NBSP}— карта.\n`a - b`\nПусто.\n"
    assert (result.lines_changed, result.nbsp_added, result.dashes_added) == (1, 1, 1)
    assert result.changed and result.protected == 2 and result.engine_version == "fake"


def test_typograph_refuses_a_runner_that_changes_words():
    def greedy(text, enabled):
        return text.replace("1/2", "½"), "greedy"

    with pytest.raises(T.TypographyError, match="проверка не пройдена"):
        T.typograph("Существо 1/2 стоит на столе.", decisions=HOUSE, names=(), runner=greedy)


def test_typograph_refuses_a_runner_that_inserts_characters():
    def inserting(text, enabled):
        return text.replace("т.е.", "т. е."), "inserting"

    with pytest.raises(T.TypographyError, match="проверка не пройдена"):
        T.typograph("Это, т.е. колода, сильная.", decisions=HOUSE, names=(), runner=inserting)


def test_plain_headings_are_protected_exactly_as_structure_py_sees_them():
    """Раздел ищется точной строкой: «Как собрать колоду» с неразрывным пробелом не находится."""
    import common as C

    structure = C.sibling("structure")
    guides = sorted((Path(__file__).resolve().parents[2] / "гайды").glob("*.md"))[:3]
    texts = [
        "Как собрать колоду\n\nВ целом колода играет в 2-3 хода.\n\n# Заголовок\n\nСпасибо за внимание\n"
    ] + [guide.read_text(encoding="utf-8") for guide in guides]
    for text in texts:
        markup, _ = T.protected_spans(text)
        lines = text.split("\n")
        starts = [0]
        for line in lines:
            starts.append(starts[-1] + len(line) + 1)
        for index, heading in structure.headings(text):
            start, end = starts[index], starts[index] + len(lines[index])
            assert any(a <= start and end <= b for a, b in markup), lines[index]
    prose = "В целом колода играет в 2-3 хода."
    markup, _ = T.protected_spans(texts[0])
    start = texts[0].index(prose)
    assert not any(a < start + len(prose) and start < b for a, b in markup)


def test_typograph_refuses_a_runner_that_drops_placeholders():
    with pytest.raises(T.TypographyError, match="заглушки"):
        T.typograph("`код` и текст", decisions=HOUSE, names=(), runner=lambda t, e: ("текст", "x"))


def test_missing_node_is_reported_as_unavailable(monkeypatch):
    monkeypatch.setattr(T.shutil, "which", lambda name: None)
    with pytest.raises(T.ToolUnavailable, match="Node.js"):
        T.run_node("текст", T.enabled_rules(HOUSE))


# ── настоящий Typograf ────────────────────────────────────────────────────


@needs_node
def test_real_typograf_applies_house_style():
    result = T.typograph(SAMPLE, decisions=HOUSE, names=NAMES)
    assert result.engine_version.startswith("7.")
    text = result.text
    assert f"Рыцарь на коне{NBSP}— сильная" in text  # тире и неразрывный пробел перед ним
    assert '"добор"' in text and "«" not in text  # кавычки прямые, как в СТИЛЬ.md
    assert "2-3" in text and "1/2" in text and "3/4" in text  # диапазон и статы нетронуты
    assert "Кел'Тузад" in text and "E.T.C." in text and "..." in text
    assert "т.е." in text and f"в{NBSP}2-3" in text  # пробелы только заменяются, не вставляются
    assert len(text.split()) == len(SAMPLE.split())


@needs_node
def test_real_typograf_leaves_plain_headings_alone():
    text = (
        "Как собрать колоду\n\nВ целом колода играет в 2-3 хода - и всё.\n\nСпасибо за внимание\n"
    )
    result = T.typograph(text, decisions=HOUSE, names=()).text
    lines = result.split("\n")
    assert lines[0] == "Как собрать колоду" and lines[4] == "Спасибо за внимание"
    assert lines[2] == f"В{NBSP}целом колода играет в{NBSP}2-3 хода{NBSP}— и{NBSP}всё."


@needs_node
def test_real_typograf_is_idempotent():
    once = T.typograph(SAMPLE, decisions=HOUSE, names=NAMES).text
    again = T.typograph(once, decisions=HOUSE, names=NAMES)
    assert again.text == once and not again.changed


@needs_node
def test_guillemets_decision_converts_quotes_and_passes_verification():
    decisions = {**HOUSE, "quotes": {"decision": "guillemets"}}
    text = T.typograph('Берём "добор" и "Рыцарь на коне".', decisions=decisions, names=NAMES).text
    assert "«добор»" in text and "«Рыцарь на коне»" in text


@needs_node
def test_unknown_rule_is_refused_instead_of_skipped():
    with pytest.raises(T.TypographyError, match="неизвестные правила"):
        T.run_node("текст", ("ru/dash/no-such-rule",))


@needs_node
def test_typography_before_shortcodes_keeps_every_card():
    """Без защиты Typograf вставляет неразрывный пробел в название, и шорткод не ставится."""
    wild = "wild"
    typographed = T.typograph(SAMPLE, decisions=HOUSE, names=NAMES).text
    assert apply_shortcodes(typographed, catalog=CATALOG, game_format=wild).inserted == 3
    naive, _ = T.run_node(SAMPLE, T.enabled_rules(HOUSE))
    assert f"на{NBSP}коне" in naive
    assert apply_shortcodes(naive, catalog=CATALOG, game_format=wild).inserted == 2


@needs_node
def test_typography_after_shortcodes_keeps_tags_and_names_even_with_quote_rule():
    """Правило кавычек превратило бы `id="…"` в `id="…»`; теги шорткода гасятся целиком."""
    html = '<p class="x">[hs_card id="TEST_001"]Рыцарь на коне[/hs_card] - карта, "добор".</p>'
    decisions = {**HOUSE, "quotes": {"decision": "guillemets"}}
    text = T.typograph(html, decisions=decisions, names=NAMES).text
    assert '[hs_card id="TEST_001"]Рыцарь на коне[/hs_card]' in text
    assert '<p class="x">' in text and "«добор»" in text


@needs_node
def test_real_card_catalog_is_protected_in_a_corpus_guide():
    guide = sorted((Path(__file__).resolve().parents[2] / "гайды").glob("*.md"))[0]
    text, _, _ = T.read_document(guide)
    result = T.typograph(text)
    assert result.protected > 100 and result.nbsp_added > 100
    assert T.typograph(result.text).text == result.text
    assert T.verify(text, result.text) == []


# ── команда editor-team typography ───────────────────────────────────────


@needs_node
def test_cli_check_write_and_output(tmp_path, capsys):
    source = tmp_path / "статья.md"
    source.write_text("Колода - сильная, в 2-3 хода.\n", encoding="utf-8")
    assert main(["typography", str(source), "--check"]) == 1
    capsys.readouterr()
    assert source.read_text(encoding="utf-8") == "Колода - сильная, в 2-3 хода.\n"

    target = tmp_path / "готово.md"
    assert main(["--format", "json", "typography", str(source), "--output", str(target)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["changed"] and payload["written"] == str(target)
    assert payload["tool"]["name"] == "typograf" and payload["quotes"] == "straight"
    assert source.read_text(encoding="utf-8") == "Колода - сильная, в 2-3 хода.\n"
    assert target.read_text(encoding="utf-8") == f"Колода{NBSP}— сильная, в{NBSP}2-3 хода.\n"

    assert main(["typography", str(source), "--write"]) == 0
    assert source.read_bytes() == target.read_bytes()
    assert main(["typography", str(source), "--check"]) == 0


@needs_node
def test_cli_keeps_crlf_and_bom(tmp_path):
    source = tmp_path / "статья.md"
    source.write_bytes("﻿Колода - сильная.\r\nВторая строка.\r\n".encode())
    assert main(["typography", str(source), "--write"]) == 0
    raw = source.read_bytes()
    assert (
        raw.startswith(b"\xef\xbb\xbf")
        and b"\r\n" in raw
        and b"\n" not in raw.replace(b"\r\n", b"")
    )
    assert f"Колода{NBSP}— сильная.".encode() in raw


def test_cli_reports_missing_node_with_exit_code_2(tmp_path, capsys, monkeypatch):
    source = tmp_path / "статья.md"
    source.write_text("Колода - сильная.\n", encoding="utf-8")
    monkeypatch.setattr(T.shutil, "which", lambda name: None)
    assert main(["typography", str(source), "--write"]) == 2
    assert "типографика не запущена" in capsys.readouterr().err
    assert source.read_text(encoding="utf-8") == "Колода - сильная.\n"


def test_cli_reports_missing_file(tmp_path, capsys):
    assert main(["typography", str(tmp_path / "нет.md")]) == 2
    assert "типографика отклонена" in capsys.readouterr().err


def test_typograf_assets_match_their_source_record():
    folder = T.RUNNER.parent
    record = json.loads((folder / "SOURCE.json").read_text(encoding="utf-8"))
    library = (folder / "typograf.all.min.js").read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(library).hexdigest() == record["sha256"], (
        "typograf.all.min.js изменён: обновите SOURCE.json"
    )
    assert (folder / record["license_file"]).is_file()
