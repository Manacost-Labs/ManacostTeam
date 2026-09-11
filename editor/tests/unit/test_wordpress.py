"""WordPress-экспорт сохраняет формат статьи и не угадывает карты."""

import pytest

from editorteam.cli import main
from editorteam.wordpress import (
    Card,
    ExportError,
    HearthstoneFormat,
    export_html_file,
    load_catalog,
    render_wordpress_html,
)

CATALOG = (
    Card("Гадалка", "JAIL_912", frozenset({HearthstoneFormat.ARENA, HearthstoneFormat.WILD})),
    Card("Волна огня", "CS2_032", frozenset({HearthstoneFormat.WILD})),
    Card("Карапуз", "BG_TEST_001", frozenset({HearthstoneFormat.BATTLEGROUNDS})),
)


def test_directives_enable_arena_card_shortcodes_and_keep_unknown_card_plain() -> None:
    source = """Формат: Арена
Подсветка карт

# Квест Жрец

Главная слабость — превращения. Гадалка удерживает стол, а Неизвестная карта нет.
"""

    html = render_wordpress_html(source, catalog=CATALOG)

    assert "Формат:" not in html
    assert "Подсветка карт" not in html
    assert "<h1>Квест Жрец</h1>" in html
    assert '<strong>Главная слабость — превращения.</strong>' in html
    assert '[hs_card id="JAIL_912"]Гадалка[/hs_card]' in html
    assert "Неизвестная карта" in html


def test_format_limits_card_highlighting_and_battlegrounds_uses_bg_shortcode() -> None:
    wild = render_wordpress_html(
        "Формат: Вольный\nПодсветка карт\n\nВолна огня завершает партию.", catalog=CATALOG
    )
    arena = render_wordpress_html(
        "Формат: Арена\nПодсветка карт\n\nВолна огня завершает партию.", catalog=CATALOG
    )
    battlegrounds = render_wordpress_html(
        "Формат: Поля сражений\nПодсветка карт\n\nКарапуз усиливает стол.", catalog=CATALOG
    )

    assert '[hs_card id="CS2_032"]Волна огня[/hs_card]' in wild
    assert "[hs_card" not in arena
    assert '[hs_bg id="BG_TEST_001"]Карапуз[/hs_bg]' in battlegrounds


def test_html_is_escaped_and_existing_shortcodes_are_not_nested() -> None:
    source = (
        'Подсветка карт\n\n[hs_card id="JAIL_912"]Гадалка[/hs_card] <script>alert(1)</script>'
    )

    html = render_wordpress_html(source, catalog=CATALOG)

    assert html.count('[hs_card id="JAIL_912"]Гадалка[/hs_card]') == 1
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_unsafe_existing_shortcode_is_escaped() -> None:
    source = '[hs_card id="JAIL_912"]<script>alert(1)</script>[/hs_card]'

    html = render_wordpress_html(source, catalog=CATALOG)

    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_overlapping_card_names_do_not_create_nested_shortcodes() -> None:
    catalog = (
        Card("Великая Гадалка", "TEST_001", frozenset({HearthstoneFormat.STANDARD})),
        Card("Гадалка", "JAIL_912", frozenset({HearthstoneFormat.STANDARD})),
    )

    html = render_wordpress_html("Подсветка карт\n\nВеликая Гадалка удерживает стол.", catalog=catalog)

    assert '[hs_card id="TEST_001"]Великая Гадалка[/hs_card]' in html
    assert html.count("[hs_card") == 1


def test_explicit_bold_is_not_wrapped_twice_by_the_important_sentence_rule() -> None:
    html = render_wordpress_html("**Основная цель — удержать стол.**", catalog=CATALOG)

    assert html.count("<strong>") == 1
    assert html.count("</strong>") == 1


def test_export_always_writes_utf8_html_file(tmp_path) -> None:
    source = tmp_path / "article.md"
    destination = tmp_path / "article.html"
    source.write_text("# Заголовок\n\nОсновная цель — удержать стол.", encoding="utf-8")

    export_html_file(source, destination, catalog=CATALOG)

    assert destination.suffix == ".html"
    assert destination.read_text(encoding="utf-8") == (
        "<h1>Заголовок</h1>\n<p><strong>Основная цель — удержать стол.</strong></p>\n"
    )


def test_cli_writes_html_to_the_default_destination(tmp_path) -> None:
    source = tmp_path / "article.md"
    catalog = tmp_path / "cards.json"
    source.write_text("Подсветка карт\n\nГадалка удерживает стол.", encoding="utf-8")
    catalog.write_text(
        '{"cards": [{"name": "Гадалка", "id": "JAIL_912", "formats": ["standard"]}]}',
        encoding="utf-8",
    )

    assert main(["wordpress", str(source), "--catalog", str(catalog)]) == 0

    html = source.with_suffix(".html").read_text(encoding="utf-8")
    assert '[hs_card id="JAIL_912"]Гадалка[/hs_card]' in html


def test_cli_flag_overrides_the_format_directive(tmp_path) -> None:
    source = tmp_path / "article.md"
    catalog = tmp_path / "cards.json"
    source.write_text("Формат: Арена\nПодсветка карт\n\nГадалка удерживает стол.", encoding="utf-8")
    catalog.write_text(
        '{"cards": [{"name": "Гадалка", "id": "JAIL_912", "formats": ["standard"]}]}',
        encoding="utf-8",
    )

    assert main(["wordpress", str(source), "--catalog", str(catalog), "--hs-format", "standard"]) == 0

    assert '[hs_card id="JAIL_912"]Гадалка[/hs_card]' in source.with_suffix(".html").read_text(
        encoding="utf-8"
    )


def test_invalid_catalog_is_reported_without_a_traceback(tmp_path, capsys) -> None:
    source = tmp_path / "article.md"
    catalog = tmp_path / "cards.json"
    source.write_text("Подсветка карт\n\nГадалка удерживает стол.", encoding="utf-8")
    catalog.write_text(
        '{"cards": [{"name": "Гадалка", "id": "JAIL_912", "formats": [123]}]}',
        encoding="utf-8",
    )

    assert main(["wordpress", str(source), "--catalog", str(catalog)]) == 2

    assert "wordpress:" in capsys.readouterr().err


def test_catalog_rejects_two_ids_for_the_same_card_and_format(tmp_path) -> None:
    catalog = tmp_path / "cards.json"
    catalog.write_text(
        """{
          "cards": [
            {"name": "Гадалка", "id": "JAIL_912", "formats": ["standard"]},
            {"name": "Гадалка", "id": "TEST_001", "formats": ["standard"]}
          ]
        }""",
        encoding="utf-8",
    )

    with pytest.raises(ExportError, match="неоднознач"):
        load_catalog(catalog)
