"""Insert catalog-confirmed card shortcodes without rewriting the document."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .wordpress import (
    Card,
    ExportError,
    HearthstoneFormat,
    _shortcode,
    _validated_catalog,
    parse_format,
)

AMBIGUOUS_NAMES = frozenset(
    {
        "монетка",
        "размах",
        "ярость",
        "возрождение",
        "оружие",
        "барьер",
        "казнь",
        "озарение",
        "тишина",
        "вихрь",
        "воскрешение",
        "исцеление",
    }
)
PROTECTED = re.compile(
    r"(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1[^\n]*(?:\n|$)"
    r"|^ {0,3}\[(?!\^)[^\]\n]+\]:[^\n]*(?:\n|$)"
    r"|!\[(?:\\.|[^\]\\\n])*\]"
    r"|`+[^`\n]*`+"
    r"|\[(hs_card|hs_bg)\b[^\]]*\].*?\[/\2\]"
    r"|<(code|pre|script|style)\b[^>]*>.*?</\3>"
    r"|<!--.*?-->|<[^>]*>"
    r"|(?<=\]\()[^\n)]*(?=\))|https?://[^\s<>\]\)]+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ShortcodeResult:
    text: str
    inserted: int
    review: tuple[str, ...]


def apply_shortcodes(
    source: str,
    *,
    catalog: Iterable[Card],
    game_format: str | HearthstoneFormat,
    mentions: list[dict] | None = None,
) -> ShortcodeResult:
    """Use exact names, or ONLY explicitly reviewed contextual mention offsets.

    Offsets refer to the original document. Context review can confirm aliases
    and inflected names; this helper checks their IDs, mode and text boundaries.
    """
    selected = parse_format(game_format)
    cards = _validated_catalog(catalog)
    eligible = [card for card in cards if card.supports(selected)]
    protected = [match.span() for match in PROTECTED.finditer(source)]
    replacements: list[tuple[int, int, Card]] = []
    review: set[str] = set()

    def intersects(start: int, end: int, spans: Iterable[tuple[int, int]]) -> bool:
        return any(start < right and end > left for left, right in spans)

    if mentions is not None:
        if not isinstance(mentions, list):
            raise ExportError("mentions must be an array of reviewed spans")
        by_id = {card.id: card for card in eligible}
        for mention in mentions:
            if not isinstance(mention, dict):
                raise ExportError("each mention must be an object")
            start, end, card_id = mention.get("start"), mention.get("end"), mention.get("card_id")
            if (
                type(start) is not int
                or type(end) is not int
                or not 0 <= start < end <= len(source)
            ):
                raise ExportError("mention offsets do not match the original document")
            if not isinstance(card_id, str) or card_id not in by_id:
                raise ExportError("mention ID is not confirmed in the selected game format")
            if (
                not source[start:end].strip()
                or source[start:end] != source[start:end].strip()
                or "\n" in source[start:end]
                or "\r" in source[start:end]
                or any(char in source[start:end] for char in "<>[]`")
            ):
                raise ExportError("a card mention must be nonempty inline text")
            if not isinstance(mention.get("text"), str):
                raise ExportError("each reviewed mention requires its original text")
            if mention["text"] != source[start:end]:
                raise ExportError("mention text changed since context review")
            if (
                start > 0 and re.match(r"\w", source[start - 1]) and re.match(r"\w", source[start])
            ) or (
                end < len(source)
                and re.match(r"\w", source[end - 1])
                and re.match(r"\w", source[end])
            ):
                raise ExportError("a reviewed mention must not split a word")
            if intersects(start, end, protected):
                raise ExportError(
                    "mention overlaps code, a URL, HTML markup, or an existing shortcode"
                )
            if intersects(start, end, ((a, b) for a, b, _ in replacements)):
                raise ExportError("reviewed card mentions overlap")
            replacements.append((start, end, by_id[card_id]))
    else:
        for card in sorted(eligible, key=lambda item: len(item.name), reverse=True):
            pattern = re.compile(rf"(?<![\wЁё]){re.escape(card.name)}(?![\wЁё])")
            for match in pattern.finditer(source):
                start, end = match.span()
                if intersects(start, end, protected):
                    continue
                if card.name.casefold() in AMBIGUOUS_NAMES:
                    review.add(card.name)
                    continue
                if not intersects(start, end, ((a, b) for a, b, _ in replacements)):
                    replacements.append((start, end, card))
    rendered = source
    for start, end, card in sorted(replacements, reverse=True, key=lambda item: item[0]):
        rendered = rendered[:start] + _shortcode(card, selected, source[start:end]) + rendered[end:]
    return ShortcodeResult(rendered, len(replacements), tuple(sorted(review)))
