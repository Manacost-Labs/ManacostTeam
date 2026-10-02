import pytest

from editorteam.card_shortcodes import apply_shortcodes
from editorteam.wordpress import Card, ExportError, HearthstoneFormat

CATALOG = (
    Card("Бранн Бронзобород", "CORE_LOE_077", frozenset({HearthstoneFormat.WILD})),
    Card("Бранн Бронзобород", "BG_LOE_077", frozenset({HearthstoneFormat.BATTLEGROUNDS})),
    Card("Монетка", "GAME_005", frozenset({HearthstoneFormat.WILD})),
)


def test_shortcodes_preserve_document_and_route_by_mode():
    text = "# План\n\nБранн Бронзобород помогает.\n"
    result = apply_shortcodes(text, catalog=CATALOG, game_format="battlegrounds")
    assert result.text == '# План\n\n[hs_bg id="BG_LOE_077"]Бранн Бронзобород[/hs_bg] помогает.\n'
    assert result.inserted == 1


def test_existing_markup_code_urls_and_attributes_are_preserved():
    text = (
        "`Бранн Бронзобород`\n```text\nБранн Бронзобород\n```\n"
        '<a title="Бранн Бронзобород">ссылка</a>\n'
        "[ссылка](https://example.com/Бранн-Бронзобород)\n"
        '[hs_card id="CORE_LOE_077"]Бранн Бронзобород[/hs_card]\n'
    )
    result = apply_shortcodes(text, catalog=CATALOG, game_format="wild")
    assert result.text == text
    assert result.inserted == 0


def test_ambiguous_common_noun_needs_explicit_context_confirmation():
    text = "Монетка лежала на столе. Монетка даёт ману."
    result = apply_shortcodes(text, catalog=CATALOG, game_format="wild")
    assert result.text == text
    assert "Монетка" in result.review
    start = text.rindex("Монетка")
    selected = apply_shortcodes(
        text,
        catalog=CATALOG,
        game_format="wild",
        mentions=[{"start": start, "end": start + 7, "card_id": "GAME_005"}],
    )
    assert (
        selected.text
        == 'Монетка лежала на столе. [hs_card id="GAME_005"]Монетка[/hs_card] даёт ману.'
    )


def test_wrong_mode_unknown_ids_and_stale_offsets_are_rejected():
    with pytest.raises(ExportError):
        apply_shortcodes(
            "Бранн",
            catalog=CATALOG,
            game_format="wild",
            mentions=[{"start": 0, "end": 5, "card_id": "BG_LOE_077"}],
        )
    with pytest.raises(ExportError):
        apply_shortcodes(
            "Бранн",
            catalog=CATALOG,
            game_format="wild",
            mentions=[{"start": 0, "end": 5, "card_id": "UNKNOWN"}],
        )
    with pytest.raises(ExportError):
        apply_shortcodes(
            "Бранн",
            catalog=CATALOG,
            game_format="wild",
            mentions=[{"start": 0, "end": 99, "card_id": "CORE_LOE_077"}],
        )


def test_repeat_run_does_not_nest_shortcodes():
    first = apply_shortcodes("Бранн Бронзобород", catalog=CATALOG, game_format="wild")
    second = apply_shortcodes(first.text, catalog=CATALOG, game_format="wild")
    assert second.text == first.text
    assert second.inserted == 0


@pytest.mark.parametrize("text", [" Бранн", "Бранн ", "Бранн[", "Бранн<", "Бранн`"])
def test_reviewed_spans_do_not_capture_whitespace_or_markup(text):
    with pytest.raises(ExportError):
        apply_shortcodes(
            text,
            catalog=CATALOG,
            game_format="wild",
            mentions=[{"start": 0, "end": len(text), "card_id": "CORE_LOE_077"}],
        )
