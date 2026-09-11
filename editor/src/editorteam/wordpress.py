"""Детерминированный экспорт статей Hearthstone в HTML для WordPress."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable


class ExportError(ValueError):
    """Экспорт нельзя выполнить без однозначных входных данных."""


class HearthstoneFormat(str, Enum):
    STANDARD = "standard"
    WILD = "wild"
    ARENA = "arena"
    BATTLEGROUNDS = "battlegrounds"


FORMAT_ALIASES = {
    "стандарт": HearthstoneFormat.STANDARD,
    "standard": HearthstoneFormat.STANDARD,
    "вольный": HearthstoneFormat.WILD,
    "wild": HearthstoneFormat.WILD,
    "арена": HearthstoneFormat.ARENA,
    "arena": HearthstoneFormat.ARENA,
    "поля сражений": HearthstoneFormat.BATTLEGROUNDS,
    "поля": HearthstoneFormat.BATTLEGROUNDS,
    "battlegrounds": HearthstoneFormat.BATTLEGROUNDS,
}
FORMAT_DIRECTIVE = re.compile(r"^\s*формат\s*:\s*(?P<value>.+?)\s*$", re.IGNORECASE)
CARD_HIGHLIGHT_DIRECTIVE = re.compile(r"^\s*подсветка\s+карт\s*$", re.IGNORECASE)
HEADING = re.compile(r"^(?P<level>#{1,6})\s+(?P<text>.+?)\s*$")
SHORTCODE = re.compile(
    r'\[(?:hs_card|hs_bg)\s+id="[A-Za-z0-9_]+"\][^\[<>\r\n]+?\[/(?:hs_card|hs_bg)\]'
)
CARD_ID = re.compile(r"^[A-Za-z0-9_]+$")
BOLD = re.compile(r"\*\*(?P<text>.+?)\*\*")
IMPORTANT_SENTENCE = re.compile(
    r"(?P<sentence>[^.!?…]*(?:основная\s+цель|главная\s+слабость|главный\s+риск|"
    r"ключевая\s+карта|ключевой\s+вывод|приоритет)[^.!?…]*[.!?…])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Card:
    """Одна подтверждённая запись каталога для конкретных игровых форматов."""

    name: str
    id: str
    formats: frozenset[HearthstoneFormat]

    def supports(self, game_format: HearthstoneFormat) -> bool:
        return game_format in self.formats


def parse_format(value: str | HearthstoneFormat) -> HearthstoneFormat:
    """Привести русское или машинное имя формата к единому значению."""
    if isinstance(value, HearthstoneFormat):
        return value
    if not isinstance(value, str):
        raise ExportError("формат в каталоге должен быть строкой")
    normalized = value.strip().casefold()
    try:
        return FORMAT_ALIASES[normalized]
    except KeyError as exc:
        choices = ", ".join(("Стандарт", "Вольный", "Арена", "Поля сражений"))
        raise ExportError(f"неизвестный формат «{value}»; доступны: {choices}") from exc


def _validated_catalog(catalog: Iterable[Card]) -> tuple[Card, ...]:
    """Не дать двум карточкам спорить за одно имя в одном формате."""
    result = tuple(catalog)
    seen: set[tuple[str, HearthstoneFormat]] = set()
    for card in result:
        if not card.name.strip() or not CARD_ID.fullmatch(card.id):
            raise ExportError("в каталоге у карты нужны непустое name и безопасный id")
        for game_format in card.formats:
            key = (card.name, game_format)
            if key in seen:
                raise ExportError(
                    f"неоднозначная запись каталога для «{card.name}» в формате {game_format.value}"
                )
            seen.add(key)
    return result


def load_catalog(path: Path) -> tuple[Card, ...]:
    """Прочитать компактный каталог шорткодов из JSON без сетевых запросов."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ExportError(f"не удалось прочитать каталог: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExportError(f"каталог содержит некорректный JSON: {path}") from exc

    entries = raw.get("cards") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise ExportError("каталог должен быть массивом cards")

    catalog: list[Card] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ExportError(f"запись каталога #{index} должна быть объектом")
        name, card_id, formats = entry.get("name"), entry.get("id"), entry.get("formats")
        if not isinstance(name, str) or not isinstance(card_id, str) or not isinstance(formats, list):
            raise ExportError(f"в записи каталога #{index} нужны name, id и formats")
        catalog.append(Card(name, card_id, frozenset(parse_format(item) for item in formats)))
    return _validated_catalog(catalog)


def _directives(
    source: str, format_override: str | HearthstoneFormat | None
) -> tuple[str, HearthstoneFormat, bool]:
    """Снять только начальные редакторские директивы, сохранив тело статьи."""
    selected = parse_format(format_override) if format_override else HearthstoneFormat.STANDARD
    highlighted = False
    remaining: list[str] = []
    preamble = True
    for line in source.splitlines():
        if preamble:
            if not line.strip():
                continue
            directive = FORMAT_DIRECTIVE.match(line)
            if directive:
                if format_override is None:
                    selected = parse_format(directive.group("value"))
                continue
            if CARD_HIGHLIGHT_DIRECTIVE.match(line):
                highlighted = True
                continue
            preamble = False
        remaining.append(line)
    return "\n".join(remaining).strip(), selected, highlighted


def _shortcode(card: Card, game_format: HearthstoneFormat, matched_name: str) -> str:
    tag = "hs_bg" if game_format is HearthstoneFormat.BATTLEGROUNDS else "hs_card"
    return f'[{tag} id="{card.id}"]{matched_name}[/{tag}]'


def _replace_outside_shortcodes(text: str, pattern: re.Pattern[str], replacement) -> str:
    """Заменить имя только в прозе, сохранив уже вставленные карточки целыми."""
    parts: list[str] = []
    cursor = 0
    for shortcode in SHORTCODE.finditer(text):
        parts.append(pattern.sub(replacement, text[cursor : shortcode.start()]))
        parts.append(shortcode.group(0))
        cursor = shortcode.end()
    parts.append(pattern.sub(replacement, text[cursor:]))
    return "".join(parts)


def _highlight_cards(text: str, catalog: Iterable[Card], game_format: HearthstoneFormat) -> str:
    eligible = [card for card in catalog if card.supports(game_format)]
    for card in sorted(eligible, key=lambda item: len(item.name), reverse=True):
        pattern = re.compile(rf"(?<![\wЁё]){re.escape(card.name)}(?![\wЁё])")
        text = _replace_outside_shortcodes(
            text, pattern, lambda match: _shortcode(card, game_format, match.group(0))
        )
    return text


def _render_inline(text: str, catalog: Iterable[Card], game_format: HearthstoneFormat) -> str:
    """Экранировать текст, не затрагивая уже готовые безопасные шорткоды."""
    parts: list[str] = []
    cursor = 0
    for shortcode in SHORTCODE.finditer(text):
        parts.append(_highlight_cards(html.escape(text[cursor : shortcode.start()], quote=False), catalog, game_format))
        parts.append(shortcode.group(0))
        cursor = shortcode.end()
    parts.append(_highlight_cards(html.escape(text[cursor:], quote=False), catalog, game_format))
    rendered = "".join(parts)
    rendered = BOLD.sub(r"<strong>\g<text></strong>", rendered)

    def emphasize(match: re.Match[str]) -> str:
        sentence = match.group("sentence")
        return sentence if "<strong>" in sentence else f"<strong>{sentence}</strong>"

    return IMPORTANT_SENTENCE.sub(emphasize, rendered)


def render_wordpress_html(
    source: str,
    *,
    catalog: Iterable[Card] = (),
    format_override: str | HearthstoneFormat | None = None,
) -> str:
    """Собрать безопасный HTML-фрагмент, пригодный для вставки в WordPress."""
    article, game_format, highlighted = _directives(source, format_override)
    cards = _validated_catalog(catalog)
    if highlighted and not cards:
        raise ExportError("для «Подсветка карт» передайте каталог карт с ID")

    output: list[str] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{_render_inline(' '.join(paragraph), cards, game_format)}</p>")
            paragraph.clear()

    for line in article.splitlines():
        if not line.strip():
            flush_paragraph()
            continue
        heading = HEADING.match(line)
        if heading:
            flush_paragraph()
            level = len(heading.group("level"))
            output.append(f"<h{level}>{_render_inline(heading.group('text'), cards, game_format)}</h{level}>")
            continue
        paragraph.append(line.strip())
    flush_paragraph()
    return "\n".join(output) + ("\n" if output else "")


def export_html_file(
    source_path: Path,
    destination: Path | None = None,
    *,
    catalog: Iterable[Card] = (),
    format_override: str | HearthstoneFormat | None = None,
) -> Path:
    """Экспортировать статью в UTF-8 файл с расширением ``.html``."""
    output_path = (destination or source_path).with_suffix(".html")
    output_path.write_text(
        render_wordpress_html(
            source_path.read_text(encoding="utf-8"),
            catalog=catalog,
            format_override=format_override,
        ),
        encoding="utf-8",
    )
    return output_path
