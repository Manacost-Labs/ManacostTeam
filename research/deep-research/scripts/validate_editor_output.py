#!/usr/bin/env python3
"""Validate the structure and readability of editor-ready Markdown."""

from __future__ import annotations

import argparse
import ipaddress
import re
import sys
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


MAX_H2_SECTIONS = 15
MAX_SHORT_ANSWER_WORDS = 90
MIN_SHORT_ANSWER_SENTENCES = 2
MAX_SHORT_ANSWER_SENTENCES = 4
MAX_SENTENCE_WORDS = 30
MAX_PARAGRAPH_WORDS = 80
MAX_PARAGRAPH_SENTENCES = 4
MAX_TABLES = 3
MAX_TABLE_COLUMNS = 4

H2_RE = re.compile(r"^\s{0,3}##(?!#)\s+(.+?)\s*#*\s*$")
H1_RE = re.compile(r"^\s{0,3}#(?!#)\s+\S")
ANY_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
FENCE_RE = re.compile(
    r"^\s{0,3}(?:(?:>\s*)|(?:(?:[-+*]|\d+[.)])\s+))*(`{3,}|~{3,})"
)
LINK_DEFINITION_RE = re.compile(r"^\s{0,3}\[(?!\^)[^\]]+\]:\s*\S+")
FOOTNOTE_DEFINITION_RE = re.compile(r"^\s{0,3}\[\^[^\]]+\]:")
LINK_DEFINITION_CAPTURE_RE = re.compile(
    r"^\s{0,3}\[([^\]\n]+)\]:\s*(\S.*)$",
    re.IGNORECASE,
)
INLINE_LINK_RE = re.compile(
    r"!?\[([^\]\n]*)\]\((?:\\.|[^()\n]|\([^()\n]*\))*\)"
)
REFERENCE_LINK_RE = re.compile(r"!?\[([^\]\n]*)\]\[([^\]\n]*)\]")
REFERENCE_OR_SHORTCUT_LINK_RE = re.compile(
    r"!?\[([^\]\n]*)\](?:\[([^\]\n]*)\])?"
)
AUTOLINK_RE = re.compile(r"<https?://[^>]+>", re.IGNORECASE)
BACKTICK_RUN_RE = re.compile(r"`+")
RAW_HTML_BLOCK_TAGS = (
    "address|article|aside|base|basefont|blockquote|body|caption|center|col|"
    "colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|"
    "footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|"
    "link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|pre|"
    "script|search|section|style|summary|table|tbody|td|textarea|tfoot|th|"
    "thead|title|tr|track|ul"
)
RAW_HTML_TYPE1_START_RE = re.compile(
    r"^<(pre|script|style|textarea)(?:\s|>|$)", re.IGNORECASE
)
RAW_HTML_TYPE6_START_RE = re.compile(
    rf"^</?(?:{RAW_HTML_BLOCK_TAGS})(?:\s|/?>|$)", re.IGNORECASE
)
RAW_HTML_TYPE7_START_RE = re.compile(
    r"^(?:</[A-Za-z][A-Za-z0-9-]*\s*>|"
    r"<[A-Za-z][A-Za-z0-9-]*(?:\s+[^<>]*)?\s*/?>)\s*$"
)
HTML_CONTAINER_PREFIX_RE = re.compile(
    r"^[ \t]*(?:(?:(?:[-+*]|\d+[.)])\s+)[ \t]*)*"
)
LIST_CONTAINER_RE = re.compile(
    r"^(?P<indent> {0,3})(?P<marker>[-+*]|\d+[.)])(?P<spacing>[ \t]+)"
)
RAW_URL_RE = re.compile(r"https?://[^\s<>)]+", re.IGNORECASE)
BARE_URL_START_RE = re.compile(r"https?://", re.IGNORECASE)
BARE_URL_MARKDOWN_DELIMITERS = ("***", "___", "**", "__", "~~", "*", "_")
VISIBLE_SOURCE_LINK_START_RE = re.compile(
    r"\[(?:\\.|[^\]\n])+\]\(\s*<?https?://",
    re.IGNORECASE,
)
HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
INLINE_HTML_TAG_START_RE = re.compile(
    r"</?[A-Za-z][A-Za-z0-9-]*(?=[\s/>])"
)
INLINE_CODE_RE = re.compile(r"(`+)(.*?)\1")
INTERNAL_ID_RE = re.compile(
    r"(?<![A-Z0-9_])(?:(?:QRY|SRC|EVD|CLM|COM|CTR|SEM|CHK|LIN)-\d+|"
    r"RES-\d{8}T\d{6}Z-[A-F0-9]{8})(?![A-Z0-9_])",
    re.IGNORECASE,
)
INTERNAL_FIELD_NAMES = (
    "additional_search_required", "access_integrity", "accessed_at",
    "attempted_kinds", "audit_status", "audited_at", "authority_match",
    "bundle_validation", "challenging_evidence_ids", "checkpoint_id",
    "claim_id", "claim_ids", "claims_preserved", "claims_sha256",
    "claims_to_remove", "claims_to_rewrite", "citations_preserved",
    "clarity_preservation", "clarity_review", "contradictions_preserved",
    "community_claim_id", "content_bytes", "content_sha256",
    "contradiction_id", "created_at", "critical_issues", "current_context",
    "delivery_status", "embedded_entities", "evidence_id",
    "evidence_type_match", "executed_at", "faithful_paraphrase", "final_url",
    "fingerprint_policy", "fingerprint_reason", "fingerprint_status",
    "fingerprinted_at", "freshness_match", "freshness_risks", "lineage_id",
    "limitations_preserved",
    "localization_gap", "output_profile", "pass_with_warnings",
    "numbers_preserved", "prior_research_ids", "provider_diagnostics", "query_id",
    "ready_with_warnings", "report_sha256", "requested_url", "research_id",
    "resolution_status", "resolved_at", "result_source_ids", "reviewed_at",
    "reviewed_claim_ids", "reviewer_basis", "reviewer_status",
    "saturated_branches", "schema_version", "semantic_audit_id",
    "semantic_support", "snapshot_path", "snapshot_policy", "source_id",
    "source_type", "source_urls", "sources_sha256", "standalone_resolved",
    "scope_preserved", "supporting_evidence_ids", "underrepresented_source_types",
    "unsupported_decision_relevant_claims", "unresolved_contradictions",
    "unresolved_reason", "unsaturated_branches", "updated_at", "not_ready",
)
INTERNAL_SNAKE_CASE_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    + "|".join(re.escape(name) for name in INTERNAL_FIELD_NAMES)
    + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
WORD_RE = re.compile(
    r"[0-9A-Za-zА-Яа-яЁё]+(?:[-‐‑‒–—'’][0-9A-Za-zА-Яа-яЁё]+)*"
)
DECIMAL_DOT_RE = re.compile(r"(?<=\d)\.(?=\d)")
ABBREVIATION_RE = re.compile(
    r"\b(?:т\.?\s*е|т\.?\s*д|т\.?\s*п|и\.?\s*т\.?\s*д|"
    r"др|напр|см|гг?|e\.?\s*g|i\.?\s*e)\.",
    re.IGNORECASE,
)
TABLE_DELIMITER_RE = re.compile(r"^:?-{3,}:?$")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
HORIZONTAL_RULE_RE = re.compile(r"^\s{0,3}(?:([-*_])\s*){3,}$")
MARKDOWN_LINK_TITLE_RE = re.compile(
    r'^(?:"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|'
    r"\((?:\\.|[^()\\])*\))$"
)

SHORT_ANSWER_HEADINGS = {
    "коротко",
    "коротко о главном",
    "кратко",
    "краткий ответ",
    "короткий ответ",
    "главное",
    "главный ответ",
    "главный вывод",
    "краткое резюме",
    "основной вывод",
    "резюме",
    "суть",
    "short answer",
    "in brief",
    "summary",
    "executive summary",
    "key finding",
    "bottom line",
}

SHORT_ANSWER_HEADING_PREFIXES = (
    "коротко",
    "короткий",
    "короткая",
    "кратко",
    "краткий",
    "краткая",
    "главный вывод",
    "основной вывод",
    "краткое резюме",
    "short answer",
    "in brief",
    "summary",
    "executive summary",
    "key finding",
    "bottom line",
)

CONTEXT_MARKER_RE = re.compile(
    r"(?:актуально\s+на|материал\s+актуал(?:ен|ьна|ьно|ьны)|"
    r"актуальность\s*:|по\s+состоянию\s+на|дата\s+среза|"
    r"as[- ]of|current\s+as\s+of)",
    re.IGNORECASE,
)
DATE_INDEPENDENT_RE = re.compile(
    r"(?:не\s+зависит\s+от\s+даты|вневременн\w*|date[- ]independent)",
    re.IGNORECASE,
)
ISO_DATE_CANDIDATE_RE = re.compile(
    r"\b(?P<year>20\d{2})[-./](?P<month>\d{1,2})[-./](?P<day>\d{1,2})\b"
)
NUMERIC_DATE_CANDIDATE_RE = re.compile(
    r"\b(?P<day>\d{1,2})[-./](?P<month>\d{1,2})[-./]"
    r"(?P<year>\d{2}|20\d{2})\b"
)
RU_DATE_CANDIDATE_RE = re.compile(
    r"\b(?P<day>\d{1,2})\s+"
    r"(?P<month>января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря)\s+"
    r"(?P<year>20\d{2})(?:\s+года)?\b",
    re.IGNORECASE,
)
EN_DATE_CANDIDATE_RE = re.compile(
    r"\b(?P<month>january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\s+"
    r"(?P<day>\d{1,2}),?\s+(?P<year>20\d{2})\b",
    re.IGNORECASE,
)
RU_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
EN_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
CONTEXT_VERSION_RE = re.compile(
    r"(?:\b(?:патч|верси\w*|клиент\w*|сезон\w*|баланс\w*|сборк\w*|"
    r"рейтинг\w*|лига\w*|ранг\w*|patch|version|client|season|build)\b"
    r"[^\n.!?]{0,40}\d+(?:\.\d+)*|"
    r"\d+(?:\.\d+)*[^\n.!?]{0,40}"
    r"\b(?:патч|верси\w*|клиент\w*|сезон\w*|баланс\w*|сборк\w*|"
    r"рейтинг\w*|лига\w*|ранг\w*|patch|version|client|season|build)\b)",
    re.IGNORECASE,
)
CONTEXT_BARE_VERSION_RE = re.compile(r"\bv?\d+\.\d+(?:\.\d+)*\b", re.IGNORECASE)

INTERNAL_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<label>(?:"
    + "|".join(
        r"[\s_]+".join(re.escape(part) for part in name.split("_"))
        for name in sorted(INTERNAL_FIELD_NAMES, key=len, reverse=True)
    )
    + r"))\s*:",
    re.IGNORECASE,
)
BRACKET_TOKEN_RE = re.compile(r"\[([^\]\n]+)\]")
UNFINISHED_PLACEHOLDER_PREFIXES = (
    "рабочий заголовок",
    "укажите ",
    "версия патч сезон",
    "в двух четырёх предложениях",
    "кратко объясните",
    "смысловой подзаголовок",
    "изложите один связный вывод",
    "следующий смысловой подзаголовок",
    "добавляйте разделы",
    "условие исключение",
    "что нельзя превращать",
    "опционально",
    "название источника",
    "что именно он подтверждает",
)

LIMITATION_HEADINGS = {
    "что важно не исказить",
    "ограничения",
    "ограничения и неизвестное",
    "что остается неясным",
    "что остаётся неясным",
    "неизвестное и ограничения",
    "limitations",
    "limitations and unknowns",
    "unknowns and limitations",
}

JARGON_PATTERNS = (
    (re.compile(r"\b(?:pivot(?:ing|s)?|пивот\w*)\b", re.IGNORECASE), "pivot/пивот"),
    (re.compile(r"\b(?:scaling|скейлинг\w*)\b", re.IGNORECASE), "scaling/скейлинг"),
    (
        re.compile(r"\b(?:decks?|decklists?|deckstrings?)\b", re.IGNORECASE),
        "deck/decklist/deckstring",
    ),
    (re.compile(r"\b(?:builds?|билд\w*)\b", re.IGNORECASE), "build/билд"),
    (
        re.compile(r"\b(?:mulligans?|муллиган\w*)\b", re.IGNORECASE),
        "mulligan/муллиган",
    ),
    (
        re.compile(r"\b(?:matchups?|матчап\w*)\b", re.IGNORECASE),
        "matchup/матчап",
    ),
    (
        re.compile(r"\b(?:win[ -]?rates?|винрейт\w*)\b", re.IGNORECASE),
        "winrate/win rate/винрейт",
    ),
    (
        re.compile(
            r"\b(?:tier[ -]+lists?|тир[-‐‑‒–— ]?лист\w*)\b",
            re.IGNORECASE,
        ),
        "tier list/тир-лист",
    ),
    (
        re.compile(r"\b(?:high[ -]?roll\w*|хай[- ]?ролл\w*)\b", re.IGNORECASE),
        "high-roll/хайролл",
    ),
    (
        re.compile(r"\b(?:low[ -]?roll\w*|лоу[- ]?ролл\w*)\b", re.IGNORECASE),
        "low-roll/лоуролл",
    ),
    (re.compile(r"\b(?:boards?|борд\w*)\b", re.IGNORECASE), "board/борд"),
    (re.compile(r"\b(?:lobb(?:y|ies)|лобби)\b", re.IGNORECASE), "lobby/лобби"),
    (re.compile(r"\b(?:proxy|прокси)\b", re.IGNORECASE), "proxy/прокси"),
    (re.compile(r"\bpayoffs?\b", re.IGNORECASE), "payoff"),
    (re.compile(r"\benablers?\b", re.IGNORECASE), "enabler"),
    (re.compile(r"\boverlays?\b", re.IGNORECASE), "overlay"),
    (re.compile(r"\bselection[ -]+bias\b", re.IGNORECASE), "selection bias"),
    (
        re.compile(r"\bsurvivorship[ -]+bias\b", re.IGNORECASE),
        "survivorship bias",
    ),
    (
        re.compile(r"\bpresence[ -]+(?:metrics?|метрик\w*)\b", re.IGNORECASE),
        "presence metric/метрика",
    ),
    (
        re.compile(r"\bcausal[ -]+telemetry\b", re.IGNORECASE),
        "causal telemetry",
    ),
    (re.compile(r"\bconfidence[ -]+cap\b", re.IGNORECASE), "confidence cap"),
    (re.compile(r"\bsource[ -]+lineage\b", re.IGNORECASE), "source lineage"),
    (re.compile(r"\b(?:saturation|сатураци\w*)\b", re.IGNORECASE), "saturation"),
    (re.compile(r"\bclaims?\b", re.IGNORECASE), "claim"),
    (re.compile(r"\bevidence\b", re.IGNORECASE), "evidence"),
    (re.compile(r"\bsources?\b", re.IGNORECASE), "source"),
    (re.compile(r"\bquer(?:y|ies)\b", re.IGNORECASE), "query"),
    (re.compile(r"\baudits?\b", re.IGNORECASE), "audit"),
    (re.compile(r"\breadiness\b", re.IGNORECASE), "readiness"),
    (re.compile(r"\bconfidence\b", re.IGNORECASE), "confidence"),
    (re.compile(r"\bfreshness\b", re.IGNORECASE), "freshness"),
    (re.compile(r"\blineage\b", re.IGNORECASE), "lineage"),
    (re.compile(r"\bfingerprints?\b", re.IGNORECASE), "fingerprint"),
    (re.compile(r"\btraceability\b", re.IGNORECASE), "traceability"),
    (re.compile(r"\bas[- ]of\b", re.IGNORECASE), "as-of"),
    (re.compile(r"\b(?:pass|fail)\b", re.IGNORECASE), "internal audit status"),
    (re.compile(r"\b(?:VERY_HIGH|HIGH|MEDIUM|LOW|SPECULATIVE)\b"), "confidence code"),
)


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    line: int | None = None

    def render(self, severity: str) -> str:
        location = f" строка {self.line}:" if self.line is not None else ":"
        return f"- {severity} [{self.code}]{location} {self.message}"


@dataclass(frozen=True)
class Paragraph:
    line: int
    text: str


@dataclass(frozen=True)
class Table:
    line: int
    columns: int
    line_indexes: frozenset[int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown", help="Path to the editor-ready Markdown file")
    return parser.parse_args()


def strip_html_comments(line: str, inside_comment: bool) -> tuple[str, bool]:
    """Remove non-rendered HTML comments while preserving visible text."""
    pieces: list[str] = []
    remaining = line
    while remaining:
        if inside_comment:
            end = remaining.find("-->")
            if end < 0:
                return "".join(pieces), True
            remaining = remaining[end + 3 :]
            inside_comment = False
            continue
        start = remaining.find("<!--")
        if start < 0:
            pieces.append(remaining)
            break
        pieces.append(remaining[:start])
        remaining = remaining[start + 4 :]
        inside_comment = True
    return "".join(pieces), inside_comment


def rendered_lines(markdown: str) -> list[str]:
    """Mask frontmatter while retaining one item per source line."""
    lines = markdown.splitlines()
    masked = list(lines)

    if lines and lines[0].strip() == "---":
        closing = next(
            (
                index
                for index, line in enumerate(lines[1:], start=1)
                if line.strip() in {"---", "..."}
            ),
            None,
        )
        if closing is not None:
            for index in range(closing + 1):
                masked[index] = ""

    return masked


def _strip_blockquote_prefix(line: str) -> tuple[int, str]:
    content = line
    depth = 0
    while True:
        match = re.match(r"^ {0,3}>[ \t]?", content)
        if match is None:
            return depth, content
        depth += 1
        content = content[match.end() :]


def _explicit_list_indent(content: str) -> int | None:
    match = LIST_CONTAINER_RE.match(content)
    if match is None:
        return None
    return len(content[: match.end()].expandtabs(4))


def _line_within_list_scope(line: str, scope: tuple[int, int]) -> bool:
    quote_depth, content = _strip_blockquote_prefix(line)
    if quote_depth != scope[0]:
        return False
    if not content.strip():
        return True
    return _indent_columns(content) >= scope[1]


def _update_list_context(
    line: str, current: tuple[int, int] | None
) -> tuple[int, int] | None:
    quote_depth, content = _strip_blockquote_prefix(line)
    explicit_indent = _explicit_list_indent(content)
    if explicit_indent is not None:
        return quote_depth, explicit_indent
    if current is None or quote_depth != current[0]:
        return None
    if not content.strip() or _indent_columns(content) >= current[1]:
        return current
    return None


def mask_html_comments(lines: list[str]) -> list[str]:
    """Remove real HTML comments after code regions have already been masked."""

    result: list[str] = []
    inside_comment = False
    comment_quote_depth = 0
    current_list: tuple[int, int] | None = None
    comment_list_scope: tuple[int, int] | None = None
    for line in lines:
        quote_depth, _ = _strip_blockquote_prefix(line)
        if inside_comment and (
            quote_depth < comment_quote_depth
            or (
                comment_list_scope is not None
                and not _line_within_list_scope(line, comment_list_scope)
            )
        ):
            inside_comment = False
            comment_list_scope = None
        if not inside_comment:
            current_list = _update_list_context(line, current_list)

        pieces: list[str] = []
        cursor = 0
        while cursor < len(line):
            if inside_comment:
                closing = line.find("-->", cursor)
                if closing < 0:
                    cursor = len(line)
                    break
                cursor = closing + 3
                inside_comment = False
                continue

            opening = line.find("<!--", cursor)
            if opening < 0:
                pieces.append(line[cursor:])
                break
            if is_escaped(line, opening):
                pieces.append(line[cursor : opening + 1])
                cursor = opening + 1
                continue
            pieces.append(line[cursor:opening])
            inside_comment = True
            comment_quote_depth = quote_depth
            comment_list_scope = current_list
            cursor = opening + 4
        result.append("".join(pieces))
    return result


def mask_fenced_code(lines: list[str]) -> list[str]:
    """Mask fenced code for structure/readability metrics, preserving line numbers."""
    result: list[str] = []
    fence_character = ""
    fence_length = 0
    fence_quote_depth = 0
    current_list: tuple[int, int] | None = None
    fence_list_scope: tuple[int, int] | None = None
    for line in lines:
        quote_depth, _ = _strip_blockquote_prefix(line)
        if fence_character and (
            quote_depth < fence_quote_depth
            or (
                fence_list_scope is not None
                and not _line_within_list_scope(line, fence_list_scope)
            )
        ):
            fence_character = ""
            fence_length = 0
            fence_list_scope = None
        if not fence_character:
            current_list = _update_list_context(line, current_list)
        match = FENCE_RE.match(line)
        if fence_character:
            result.append("")
            if (
                match
                and match.group(1)[0] == fence_character
                and len(match.group(1)) >= fence_length
                and not line[match.end() :].strip()
            ):
                fence_character = ""
                fence_length = 0
                fence_list_scope = None
            continue
        if match:
            marker = match.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            fence_quote_depth = quote_depth
            fence_list_scope = current_list
            result.append("")
            continue
        result.append(line)
    return result


def mask_indented_code(lines: list[str]) -> list[str]:
    """Mask indented code while retaining valid list continuations."""

    result: list[str] = []
    active_list: tuple[int, int] | None = None
    list_after_blank = False
    paragraph_open = False
    paragraph_quote_depth = 0
    for line in lines:
        quote_depth, content = _strip_blockquote_prefix(line)
        if quote_depth != paragraph_quote_depth:
            paragraph_open = False
            paragraph_quote_depth = quote_depth

        if not content.strip():
            if active_list is not None and active_list[0] == quote_depth:
                list_after_blank = True
            paragraph_open = False
            result.append(line)
            continue

        list_match = LIST_CONTAINER_RE.match(content)
        if list_match is not None:
            content_indent = len(content[: list_match.end()].expandtabs(4))
            active_list = (quote_depth, content_indent)
            list_after_blank = False
            paragraph_open = True
            result.append(line)
            continue

        leading_columns = _indent_columns(content)
        if active_list is not None and active_list[0] == quote_depth:
            content_indent = active_list[1]
            if leading_columns >= content_indent:
                is_code = leading_columns >= content_indent + 4 and list_after_blank
                result.append("" if is_code else line)
                if not is_code:
                    list_after_blank = False
                    paragraph_open = True
                continue
            active_list = None
            list_after_blank = False
        elif active_list is not None:
            active_list = None
            list_after_blank = False

        is_code = leading_columns >= 4 and not paragraph_open
        result.append("" if is_code else line)
        if not is_code:
            if (
                ANY_HEADING_RE.match(content)
                or HORIZONTAL_RULE_RE.fullmatch(content)
                or FENCE_RE.match(content)
                or LINK_DEFINITION_RE.match(content)
                or FOOTNOTE_DEFINITION_RE.match(content)
                or content.startswith(("<!--", "<?", "<![CDATA["))
                or RAW_HTML_TYPE1_START_RE.match(content.lstrip())
                or RAW_HTML_TYPE6_START_RE.match(content.lstrip())
            ):
                paragraph_open = False
            else:
                paragraph_open = True
    return result


def _indent_columns(value: str) -> int:
    columns = 0
    for character in value:
        if character == " ":
            columns += 1
        elif character == "\t":
            columns += 4 - (columns % 4)
        else:
            break
    return columns


def mask_raw_html_blocks(lines: list[str]) -> list[str]:
    """Mask raw HTML blocks whose contents are not parsed as Markdown."""

    result: list[str] = []
    active_end: re.Pattern[str] | None = None
    ends_on_blank = False
    active_quote_depth = 0
    current_list: tuple[int, int] | None = None
    active_list_scope: tuple[int, int] | None = None
    paragraph_open = False
    paragraph_quote_depth = 0
    for line in lines:
        quote_depth, quote_content = _strip_blockquote_prefix(line)
        if quote_depth != paragraph_quote_depth:
            paragraph_open = False
            paragraph_quote_depth = quote_depth

        if (active_end is not None or ends_on_blank) and (
            quote_depth < active_quote_depth
            or (
                active_list_scope is not None
                and not _line_within_list_scope(line, active_list_scope)
            )
        ):
            active_end = None
            ends_on_blank = False
            active_list_scope = None

        if active_end is None and not ends_on_blank:
            current_list = _update_list_context(line, current_list)

        prefix = HTML_CONTAINER_PREFIX_RE.match(quote_content)
        content = quote_content[prefix.end() :] if prefix is not None else quote_content
        blank = not content.strip()

        if active_end is not None or ends_on_blank:
            if ends_on_blank and blank:
                result.append(line)
                ends_on_blank = False
                active_list_scope = None
                paragraph_open = False
                continue
            result.append("")
            if active_end is not None and active_end.search(content):
                active_end = None
                active_list_scope = None
            paragraph_open = False
            continue

        type1 = RAW_HTML_TYPE1_START_RE.match(content)
        if type1 is not None:
            tag = type1.group(1)
            active_end = re.compile(rf"</{re.escape(tag)}\s*>", re.IGNORECASE)
        elif content.startswith("<?"):
            active_end = re.compile(r"\?>")
        elif content.startswith("<![CDATA["):
            active_end = re.compile(r"\]\]>")
        elif re.match(r"^<![A-Z]", content):
            active_end = re.compile(r">")
        elif RAW_HTML_TYPE6_START_RE.match(content):
            ends_on_blank = True
        elif not paragraph_open and RAW_HTML_TYPE7_START_RE.fullmatch(content):
            ends_on_blank = True
        else:
            result.append(line)
            if blank:
                paragraph_open = False
            elif (
                ANY_HEADING_RE.match(quote_content)
                or HORIZONTAL_RULE_RE.fullmatch(quote_content)
                or LIST_CONTAINER_RE.match(quote_content)
                or LINK_DEFINITION_RE.match(quote_content)
            ):
                paragraph_open = False
            else:
                paragraph_open = True
            continue

        result.append("")
        active_quote_depth = quote_depth
        active_list_scope = current_list
        if active_end is not None and active_end.search(content):
            active_end = None
            active_list_scope = None
        paragraph_open = False
    return result


def _blank_preserving_newlines(value: str) -> str:
    return "".join("\n" if character == "\n" else " " for character in value)


HTML_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def _html_attrs_hide_content(attrs: list[tuple[str, str | None]]) -> bool:
    values = {name.casefold(): value for name, value in attrs}
    if "hidden" in values:
        return True
    aria_hidden = values.get("aria-hidden")
    if isinstance(aria_hidden, str) and aria_hidden.strip().casefold() == "true":
        return True
    style = values.get("style")
    if not isinstance(style, str):
        return False
    for declaration in style.split(";"):
        if ":" not in declaration:
            continue
        property_name, property_value = declaration.split(":", 1)
        normalized_name = property_name.strip().casefold()
        normalized_value = re.sub(r"\s+", "", property_value.casefold())
        if normalized_name == "display" and normalized_value.startswith("none"):
            return True
        if normalized_name == "visibility" and normalized_value.startswith(
            ("hidden", "collapse")
        ):
            return True
    return False


class _HiddenHTMLRangeParser(HTMLParser):
    """Locate HTML elements whose rendered contents are explicitly hidden."""

    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=False)
        self.text = text
        self.line_offsets: list[int] = []
        offset = 0
        for line in text.splitlines(keepends=True):
            self.line_offsets.append(offset)
            offset += len(line)
        if not self.line_offsets:
            self.line_offsets.append(0)
        self.stack: list[tuple[str, int | None]] = []
        self.ranges: list[tuple[int, int]] = []

    def _offset(self) -> int:
        line, column = self.getpos()
        if line - 1 >= len(self.line_offsets):
            return len(self.text)
        return min(self.line_offsets[line - 1] + column, len(self.text))

    def _active_hidden_start(self) -> int | None:
        return next(
            (start for _, start in reversed(self.stack) if start is not None),
            None,
        )

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        start = self._offset()
        active_hidden = self._active_hidden_start()
        hidden_start = (
            start
            if active_hidden is None and _html_attrs_hide_content(attrs)
            else None
        )
        if tag.casefold() in HTML_VOID_TAGS:
            if hidden_start is not None:
                raw_tag = self.get_starttag_text() or ""
                self.ranges.append((hidden_start, start + len(raw_tag)))
            return
        self.stack.append((tag.casefold(), hidden_start))

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if not _html_attrs_hide_content(attrs):
            return
        start = self._offset()
        raw_tag = self.get_starttag_text() or ""
        self.ranges.append((start, start + len(raw_tag)))

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.casefold()
        matching_index = next(
            (
                index
                for index in range(len(self.stack) - 1, -1, -1)
                if self.stack[index][0] == normalized_tag
            ),
            None,
        )
        if matching_index is None:
            return
        popped = self.stack[matching_index:]
        del self.stack[matching_index:]
        hidden_starts = [start for _, start in popped if start is not None]
        if not hidden_starts:
            return
        start = min(hidden_starts)
        closing = self.text.find(">", self._offset())
        end = len(self.text) if closing < 0 else closing + 1
        self.ranges.append((start, end))


def mask_hidden_html_elements(text: str) -> str:
    """Blank explicitly hidden HTML while preserving source line boundaries."""

    parser = _HiddenHTMLRangeParser(text)
    try:
        parser.feed(text)
        parser.close()
    except (AssertionError, ValueError):
        return text
    for _, hidden_start in parser.stack:
        if hidden_start is not None:
            parser.ranges.append((hidden_start, len(text)))
    masked = list(text)
    for start, end in parser.ranges:
        for index in range(max(0, start), min(end, len(masked))):
            if masked[index] != "\n":
                masked[index] = " "
    return "".join(masked)


def mask_inline_code_spans(text: str) -> str:
    """Mask paired CommonMark-style backtick runs while preserving line layout."""

    masked = text
    cursor = 0
    while True:
        opening = BACKTICK_RUN_RE.search(masked, cursor)
        if opening is None:
            return masked
        if is_escaped(masked, opening.start()):
            cursor = opening.end()
            continue
        marker = opening.group(0)
        closing = re.search(
            rf"(?<!`){re.escape(marker)}(?!`)",
            masked[opening.end() :],
        )
        if closing is None:
            cursor = opening.end()
            continue
        closing_start = opening.end() + closing.start()
        closing_end = opening.end() + closing.end()
        masked = (
            masked[: opening.start()]
            + _blank_preserving_newlines(masked[opening.start() : closing_end])
            + masked[closing_end:]
        )
        cursor = closing_end


def code_masked_rendered_lines(markdown: str) -> list[str]:
    """Return rendered source lines with non-clickable code regions blanked."""

    lines = mask_raw_html_blocks(
        mask_indented_code(mask_fenced_code(rendered_lines(markdown)))
    )
    text = mask_hidden_html_elements("\n".join(lines))
    lines = mask_inline_code_spans(text).split("\n")
    return mask_html_comments(lines)


def structural_visibility_lines(markdown: str) -> list[str]:
    """Keep visible block elements while suppressing non-rendered metadata/comments."""

    base = rendered_lines(markdown)
    visible_block_lines: set[int] = set()

    fenced = mask_fenced_code(base)
    visible_block_lines.update(
        index
        for index, (before, after) in enumerate(zip(base, fenced))
        if before.strip() and not after.strip()
    )
    indented = mask_indented_code(fenced)
    visible_block_lines.update(
        index
        for index, (before, after) in enumerate(zip(fenced, indented))
        if before.strip() and not after.strip()
    )
    raw_html = mask_raw_html_blocks(indented)
    visible_block_lines.update(
        index
        for index, (before, after) in enumerate(zip(indented, raw_html))
        if before.strip() and not after.strip()
    )

    result = mask_definition_blocks(mask_html_comments(raw_html))
    for index in visible_block_lines:
        result[index] = "<visible-block>"
    return result


def is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def strip_link_destinations(line: str) -> str:
    """Keep rendered link labels while excluding hidden destinations from prose checks."""
    if LINK_DEFINITION_RE.match(line):
        return ""
    previous = None
    while previous != line:
        previous = line
        line = INLINE_LINK_RE.sub(lambda match: match.group(1), line)
        line = REFERENCE_LINK_RE.sub(lambda match: match.group(1), line)
    line = AUTOLINK_RE.sub("", line)
    line = RAW_URL_RE.sub("", line)
    line = HTML_TAG_RE.sub("", line)
    return line


def visible_lines(markdown: str, *, prose: bool) -> list[str]:
    lines = code_masked_rendered_lines(markdown)
    result: list[str] = []
    for line in lines:
        line = strip_link_destinations(line)
        if prose:
            line = INLINE_CODE_RE.sub("", line)
        result.append(line)
    return result


def normalize_heading(value: str) -> str:
    value = strip_link_destinations(value)
    value = INLINE_CODE_RE.sub(lambda match: match.group(2), value)
    value = re.sub(r"[*_~]", "", value)
    value = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", " ", value)
    return " ".join(value.casefold().split())


def is_short_answer_heading(value: str) -> bool:
    """Accept a known short-answer heading or a descriptive extension of one."""
    normalized = normalize_heading(value)
    if normalized in SHORT_ANSWER_HEADINGS:
        return True
    return any(
        normalized.startswith(prefix + " ")
        for prefix in SHORT_ANSWER_HEADING_PREFIXES
    )


def unfinished_placeholder_lines(lines: list[str]) -> list[int]:
    hits: list[int] = []
    for index, line in enumerate(lines, start=1):
        for match in BRACKET_TOKEN_RE.finditer(line):
            normalized = normalize_heading(match.group(1))
            if any(
                normalized == prefix or normalized.startswith(prefix + " ")
                for prefix in UNFINISHED_PLACEHOLDER_PREFIXES
            ):
                hits.append(index)
                break
    return hits


def has_visible_external_link(markdown: str) -> bool:
    """Return whether a visible Markdown link has an HTTP(S) destination."""
    return bool(visible_external_links(markdown))


def is_safe_external_url(value: str) -> bool:
    if any(ord(character) < 32 or character.isspace() for character in value):
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return False
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    host = parsed.hostname.rstrip(".")
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    labels = ascii_host.split(".")
    return all(
        label
        and len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and re.fullmatch(r"[A-Za-z0-9-]+", label)
        for label in labels
    )


def markdown_link_destination(value: str) -> str | None:
    """Separate a Markdown destination from its optional link title."""

    candidate = value.strip()
    if candidate.startswith("<"):
        closing = candidate.find(">", 1)
        if closing < 0:
            return None
        destination = candidate[1:closing].strip()
        title = candidate[closing + 1 :].strip()
        if title and not MARKDOWN_LINK_TITLE_RE.fullmatch(title):
            return None
        return destination if is_safe_external_url(destination) else None

    nested_parentheses = 0
    escaped = False
    end = len(candidate)
    for index, character in enumerate(candidate):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == "(":
            nested_parentheses += 1
        elif character == ")" and nested_parentheses:
            nested_parentheses -= 1
        elif character.isspace() and nested_parentheses == 0:
            end = index
            break
    destination = candidate[:end]
    title = candidate[end:].strip()
    if title and not MARKDOWN_LINK_TITLE_RE.fullmatch(title):
        return None
    return destination if is_safe_external_url(destination) else None


def mask_definition_blocks(lines: list[str]) -> list[str]:
    """Hide link/footnote definitions and their indented continuation lines."""

    result: list[str] = []
    inside_definition = False
    for line in lines:
        if LINK_DEFINITION_RE.match(line) or FOOTNOTE_DEFINITION_RE.match(line):
            result.append("")
            inside_definition = True
            continue
        if inside_definition and (not line.strip() or line.startswith(("    ", "\t"))):
            result.append("")
            continue
        inside_definition = False
        result.append(line)
    return result


def mask_inline_html_tags(text: str) -> str:
    """Hide tag names/attributes while retaining Markdown-parsed inner text."""

    masked = list(text)
    cursor = 0
    while cursor < len(text):
        opening = text.find("<", cursor)
        if opening < 0:
            break
        if is_escaped(text, opening):
            cursor = opening + 1
            continue
        match = INLINE_HTML_TAG_START_RE.match(text, opening)
        if match is None:
            cursor = opening + 1
            continue

        quote: str | None = None
        closing: int | None = None
        for index in range(match.end(), len(text)):
            character = text[index]
            if quote is not None:
                if character == quote:
                    quote = None
                continue
            if character in {'"', "'"}:
                quote = character
            elif character == ">":
                closing = index
                break
            elif character == "<":
                break
        if closing is None:
            cursor = match.end()
            continue
        for index in range(opening, closing + 1):
            if masked[index] != "\n":
                masked[index] = " "
        cursor = closing + 1
    return "".join(masked)


def extract_inline_external_links(text: str) -> tuple[list[str], str]:
    """Extract top-level inline links and blank every destination/title span."""

    links: list[str] = []
    masked = list(text)
    cursor = 0
    while cursor < len(text):
        bracket = text.find("[", cursor)
        if bracket < 0:
            break
        if is_escaped(text, bracket):
            cursor = bracket + 1
            continue

        starts_with_bang = bracket > 0 and text[bracket - 1] == "!"
        is_image = starts_with_bang and not is_escaped(text, bracket - 1)
        depth = 1
        escaped = False
        label_end: int | None = None
        for index in range(bracket + 1, len(text)):
            character = text[index]
            if escaped:
                escaped = False
                continue
            if character == "\\":
                escaped = True
                continue
            if character == "\n":
                break
            if character == "[":
                depth += 1
            elif character == "]":
                depth -= 1
                if depth == 0:
                    label_end = index
                    break
        if label_end is None or label_end + 1 >= len(text) or text[label_end + 1] != "(":
            cursor = bracket + 1
            continue

        opening = label_end + 1
        parenthesis_depth = 1
        escaped = False
        closing: int | None = None
        for index in range(opening + 1, len(text)):
            character = text[index]
            if escaped:
                escaped = False
                continue
            if character == "\\":
                escaped = True
                continue
            if character == "\n":
                break
            if character == "(":
                parenthesis_depth += 1
            elif character == ")":
                parenthesis_depth -= 1
                if parenthesis_depth == 0:
                    closing = index
                    break
        if closing is None:
            cursor = bracket + 1
            continue

        label = text[bracket + 1 : label_end]
        destination = markdown_link_destination(text[opening + 1 : closing])
        if destination and not is_image and label.strip():
            links.append(destination)
        markup_start = bracket - 1 if is_image else bracket
        for index in range(markup_start, closing + 1):
            if masked[index] != "\n":
                masked[index] = " "
        cursor = closing + 1
    return links, "".join(masked)


def gfm_bare_external_urls(text: str) -> list[str]:
    """Extract GFM-style bare URLs with a word boundary and balanced parentheses."""

    links: list[str] = []
    for match in BARE_URL_START_RE.finditer(text):
        start = match.start()
        opening_delimiter = next(
            (
                delimiter
                for delimiter in BARE_URL_MARKDOWN_DELIMITERS
                if start >= len(delimiter)
                and text[start - len(delimiter) : start] == delimiter
                and not (
                    delimiter.startswith("_")
                    and start > len(delimiter)
                    and text[start - len(delimiter) - 1].isalnum()
                )
            ),
            None,
        )
        if opening_delimiter is None and start > 0 and (
            text[start - 1].isalnum() or text[start - 1] == "_"
        ):
            continue
        if start > 0 and text[start - 1] == "<":
            continue
        depth = 0
        cursor = match.end()
        while cursor < len(text):
            character = text[cursor]
            if character.isspace() or character in {'<', '>', '"', "'"}:
                break
            if character == "(":
                depth += 1
            elif character == ")":
                if depth == 0:
                    break
                depth -= 1
            cursor += 1
        destination = text[start:cursor].rstrip(".,;:!?…»”’]}")
        if opening_delimiter and destination.endswith(opening_delimiter):
            destination = destination[: -len(opening_delimiter)].rstrip(
                ".,;:!?…»”’]}"
            )
        if is_safe_external_url(destination):
            links.append(destination)
    return links


def visible_external_links(markdown: str) -> list[str]:
    """Extract balanced HTTP(S) destinations from visible Markdown links."""
    visible_lines_list = code_masked_rendered_lines(markdown)

    definitions: dict[str, str] = {}
    for line in visible_lines_list:
        match = LINK_DEFINITION_CAPTURE_RE.match(line)
        if match:
            destination = markdown_link_destination(match.group(2))
            if destination:
                definitions[" ".join(match.group(1).casefold().split())] = destination

    scan_lines = mask_definition_blocks(visible_lines_list)
    scan_text = mask_inline_html_tags("\n".join(scan_lines))
    links, scan_text = extract_inline_external_links(scan_text)
    for match in REFERENCE_OR_SHORTCUT_LINK_RE.finditer(scan_text):
        starts_with_bang = match.group(0).startswith("!")
        bracket_index = match.start() + (1 if starts_with_bang else 0)
        if starts_with_bang and not is_escaped(scan_text, match.start()):
            continue
        if is_escaped(scan_text, bracket_index):
            continue
        label = match.group(1)
        raw_identifier = match.group(2)
        identifier = raw_identifier or label
        destination = definitions.get(" ".join(identifier.casefold().split()))
        if destination and label.strip():
            links.append(destination)

    for match in AUTOLINK_RE.finditer(scan_text):
        if is_escaped(scan_text, match.start()):
            continue
        destination = match.group(0)[1:-1]
        if is_safe_external_url(destination):
            links.append(destination)

    raw_url_text = INLINE_LINK_RE.sub(
        lambda match: _blank_preserving_newlines(match.group(0)),
        scan_text,
    )
    links.extend(gfm_bare_external_urls(raw_url_text))
    return list(dict.fromkeys(links))


def _calendar_date_is_valid(year: int, month: int, day: int) -> bool:
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def date_candidates(value: str) -> list[tuple[int, int, int]]:
    """Return calendar-like date candidates in supported publication forms."""

    candidates: list[tuple[int, int, int]] = []
    for match in ISO_DATE_CANDIDATE_RE.finditer(value):
        candidates.append(
            (
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
        )
    for match in NUMERIC_DATE_CANDIDATE_RE.finditer(value):
        year = int(match.group("year"))
        if year < 100:
            year += 2000
        candidates.append(
            (year, int(match.group("month")), int(match.group("day")))
        )
    for match in RU_DATE_CANDIDATE_RE.finditer(value):
        candidates.append(
            (
                int(match.group("year")),
                RU_MONTHS[match.group("month").casefold()],
                int(match.group("day")),
            )
        )
    for match in EN_DATE_CANDIDATE_RE.finditer(value):
        candidates.append(
            (
                int(match.group("year")),
                EN_MONTHS[match.group("month").casefold()],
                int(match.group("day")),
            )
        )
    return candidates


def has_concrete_context(lines: list[str]) -> bool:
    """Require an actual date/version value or an explicit timeless scope."""

    text = "\n".join(lines)
    if DATE_INDEPENDENT_RE.search(text):
        return True
    for match in CONTEXT_MARKER_RE.finditer(text):
        same_line_tail = text[match.end() :].split("\n", 1)[0]
        candidates = date_candidates(same_line_tail)
        if (
            any(_calendar_date_is_valid(*candidate) for candidate in candidates)
            or CONTEXT_VERSION_RE.search(same_line_tail)
            or (not candidates and CONTEXT_BARE_VERSION_RE.search(same_line_tail))
        ):
            return True
    return False


def word_count(value: str) -> int:
    return len(WORD_RE.findall(value))


def sentences(value: str) -> list[str]:
    placeholder = "\ue000"
    protected = DECIMAL_DOT_RE.sub(placeholder, value)
    protected = ABBREVIATION_RE.sub(
        lambda match: match.group(0).replace(".", placeholder), protected
    )
    parts = re.split(r"(?<=[.!?…])(?:[»”\"’')\]}]+)?\s+", protected)
    return [
        part.replace(placeholder, ".").strip()
        for part in parts
        if part.replace(placeholder, ".").strip()
    ]


def split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if "|" not in stripped:
        return []
    cells = re.split(r"(?<!\\)\|", stripped)
    if stripped.startswith("|"):
        cells = cells[1:]
    if stripped.endswith("|"):
        cells = cells[:-1]
    return [cell.strip() for cell in cells]


def find_tables(lines: list[str]) -> list[Table]:
    tables: list[Table] = []
    index = 0
    while index + 1 < len(lines):
        header = split_table_row(lines[index])
        delimiter = split_table_row(lines[index + 1])
        if (
            not header
            or not delimiter
            or not all(TABLE_DELIMITER_RE.fullmatch(cell) for cell in delimiter)
        ):
            index += 1
            continue

        row_indexes = {index, index + 1}
        columns = max(len(header), len(delimiter))
        cursor = index + 2
        while cursor < len(lines):
            row = split_table_row(lines[cursor])
            if not row:
                break
            row_indexes.add(cursor)
            columns = max(columns, len(row))
            cursor += 1
        tables.append(Table(index + 1, columns, frozenset(row_indexes)))
        index = cursor
    return tables


def collect_paragraphs(lines: list[str], table_lines: set[int]) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    current: list[str] = []
    start = 0

    def flush() -> None:
        nonlocal current, start
        text = " ".join(part.strip() for part in current if part.strip())
        if text:
            paragraphs.append(Paragraph(start + 1, text))
        current = []

    for index, line in enumerate(lines):
        stripped = line.strip()
        if (
            not stripped
            or index in table_lines
            or ANY_HEADING_RE.match(line)
            or HORIZONTAL_RULE_RE.fullmatch(line)
        ):
            flush()
            continue
        if LIST_ITEM_RE.match(line):
            flush()
            start = index
            current = [LIST_ITEM_RE.sub("", line, count=1)]
            continue
        if not current:
            start = index
        current.append(re.sub(r"^\s*>\s?", "", line))
    flush()
    return paragraphs


def validate_markdown(markdown: str) -> tuple[list[Finding], list[Finding]]:
    errors: list[Finding] = []
    warnings: list[Finding] = []
    rendered = visible_lines(markdown, prose=False)
    prose = visible_lines(markdown, prose=True)

    structure_lines = rendered
    first_visible_lines = structural_visibility_lines(markdown)
    h2_sections = [
        (index, match.group(1))
        for index, line in enumerate(structure_lines)
        if (match := H2_RE.match(line))
    ]

    h1_indexes = [
        index for index, line in enumerate(structure_lines) if H1_RE.match(line)
    ]
    if not h1_indexes:
        errors.append(
            Finding(
                "missing-title",
                "в начале документа нужен один понятный заголовок H1",
            )
        )
    elif len(h1_indexes) > 1:
        errors.append(
            Finding(
                "multiple-titles",
                f"найдено {len(h1_indexes)} заголовка H1; нужен ровно один",
                h1_indexes[1] + 1,
            )
        )
    else:
        first_visible_index = next(
            (index for index, line in enumerate(first_visible_lines) if line.strip()),
            None,
        )
        if first_visible_index != h1_indexes[0]:
            errors.append(
                Finding(
                    "misplaced-title",
                    "заголовок H1 должен быть первым видимым элементом документа",
                    h1_indexes[0] + 1,
                )
            )

    opening_context_end = h2_sections[1][0] if len(h2_sections) > 1 else len(prose)
    if not has_concrete_context(prose[:opening_context_end]):
        errors.append(
            Finding(
                "missing-as-of-context",
                "укажите конкретную дату или версию через «Актуально на», "
                "«По состоянию на» или явно скажите, что вывод не зависит от даты",
            )
        )

    if not has_visible_external_link(markdown):
        errors.append(
            Finding(
                "missing-source-link",
                "в основном документе нужна хотя бы одна прямая ссылка "
                "на проверенный источник",
            )
        )
    placeholder_lines = unfinished_placeholder_lines(rendered)
    if placeholder_lines:
        errors.append(
            Finding(
                "unfinished-placeholder",
                "удалите или заполните инструкции и примеры из шаблона",
                placeholder_lines[0],
            )
        )
    if len(h2_sections) > MAX_H2_SECTIONS:
        errors.append(
            Finding(
                "too-many-sections",
                f"найдено {len(h2_sections)} основных разделов H2; "
                f"допустимо не более {MAX_H2_SECTIONS}",
            )
        )

    normalized_h2 = {normalize_heading(title) for _, title in h2_sections}
    if not normalized_h2.intersection(LIMITATION_HEADINGS):
        warnings.append(
            Finding(
                "missing-limitations-section",
                "добавьте отдельный раздел с существенными ограничениями "
                "или тем, что нельзя искажать",
            )
        )

    tables = find_tables(prose)
    table_lines = {index for table in tables for index in table.line_indexes}
    paragraphs = collect_paragraphs(prose, table_lines)

    if not h2_sections:
        errors.append(
            Finding(
                "missing-short-answer",
                "в начале документа нужен раздел H2 с коротким ответом",
            )
        )
    else:
        short_index, short_title = h2_sections[0]
        if not is_short_answer_heading(short_title):
            errors.append(
                Finding(
                    "missing-short-answer",
                    "первым основным разделом должен быть короткий ответ, "
                    "например «Коротко»",
                    short_index + 1,
                )
            )
        else:
            next_h2 = h2_sections[1][0] if len(h2_sections) > 1 else len(prose)
            short_paragraphs = [
                item for item in paragraphs if short_index < item.line - 1 < next_h2
            ]
            if not short_paragraphs:
                errors.append(
                    Finding(
                        "empty-short-answer",
                        "раздел с коротким ответом не содержит обычного текста",
                        short_index + 1,
                    )
                )
            else:
                short_text = " ".join(item.text for item in short_paragraphs)
                sentence_total = len(sentences(short_text))
                if not MIN_SHORT_ANSWER_SENTENCES <= sentence_total <= MAX_SHORT_ANSWER_SENTENCES:
                    warnings.append(
                        Finding(
                            "short-answer-length",
                            f"короткий ответ содержит {sentence_total} предложений; "
                            "ориентир — от "
                            f"{MIN_SHORT_ANSWER_SENTENCES} до {MAX_SHORT_ANSWER_SENTENCES}",
                            short_index + 1,
                        )
                    )
                short_words = word_count(short_text)
                if short_words > MAX_SHORT_ANSWER_WORDS:
                    warnings.append(
                        Finding(
                            "short-answer-length",
                            f"короткий ответ содержит {short_words} слов; "
                            "ориентир — не более "
                            f"{MAX_SHORT_ANSWER_WORDS}",
                            short_index + 1,
                        )
                    )

    for index, line in enumerate(rendered, start=1):
        identifiers = sorted(set(INTERNAL_ID_RE.findall(line)), key=str.casefold)
        if identifiers:
            errors.append(
                Finding(
                    "internal-id",
                    "в основном тексте видны внутренние ID: " + ", ".join(identifiers),
                    index,
                )
            )
        internal_fields = sorted(
            set(INTERNAL_SNAKE_CASE_RE.findall(line)), key=str.casefold
        )
        if internal_fields:
            errors.append(
                Finding(
                    "internal-field",
                    "в основном тексте видны служебные поля: "
                    + ", ".join(internal_fields),
                    index,
                )
            )
        internal_labels = sorted(
            set(match.group("label") for match in INTERNAL_LABEL_RE.finditer(line)),
            key=str.casefold,
        )
        if internal_labels:
            errors.append(
                Finding(
                    "internal-field",
                    "в основном тексте видны служебные подписи: "
                    + ", ".join(internal_labels),
                    index,
                )
            )

    jargon: dict[str, int] = {}
    for index, line in enumerate(prose, start=1):
        for pattern, label in JARGON_PATTERNS:
            if label not in jargon and pattern.search(line):
                jargon[label] = index
    if jargon:
        first_line = min(jargon.values())
        warnings.append(
            Finding(
                "untranslated-jargon",
                "проверьте непереведённый исследовательский жаргон: "
                + ", ".join(sorted(jargon, key=str.casefold))
                + "; переведите или объясните термин, если это не официальное "
                "название карты",
                first_line,
            )
        )

    for paragraph in paragraphs:
        words = word_count(paragraph.text)
        sentence_total = len(sentences(paragraph.text))
        if words > MAX_PARAGRAPH_WORDS or sentence_total > MAX_PARAGRAPH_SENTENCES:
            reasons: list[str] = []
            if words > MAX_PARAGRAPH_WORDS:
                reasons.append(
                    f"{words} слов при ориентире не более {MAX_PARAGRAPH_WORDS}"
                )
            if sentence_total > MAX_PARAGRAPH_SENTENCES:
                reasons.append(
                    f"{sentence_total} предложений при ориентире не более "
                    f"{MAX_PARAGRAPH_SENTENCES}"
                )
            warnings.append(
                Finding(
                    "long-paragraph",
                    "плотный абзац: " + "; ".join(reasons),
                    paragraph.line,
                )
            )
        for sentence in sentences(paragraph.text):
            sentence_words = word_count(sentence)
            if sentence_words > MAX_SENTENCE_WORDS:
                warnings.append(
                    Finding(
                        "long-sentence",
                        f"предложение содержит {sentence_words} слов; "
                        "ориентир — не более "
                        f"{MAX_SENTENCE_WORDS}",
                        paragraph.line,
                    )
                )

    if len(tables) > MAX_TABLES:
        warnings.append(
            Finding(
                "too-many-tables",
                f"найдено {len(tables)} таблиц; ориентир — не более {MAX_TABLES}",
            )
        )
    for table in tables:
        if table.columns > MAX_TABLE_COLUMNS:
            warnings.append(
                Finding(
                    "wide-table",
                    f"в таблице {table.columns} колонок; ориентир — не более "
                    f"{MAX_TABLE_COLUMNS}",
                    table.line,
                )
            )

    return errors, warnings


def print_result(errors: list[Finding], warnings: list[Finding]) -> None:
    if errors:
        print("Editor output: FAIL")
    elif warnings:
        print("Editor output: PASS WITH WARNINGS")
    else:
        print("Editor output: PASS")
    for finding in errors:
        print(finding.render("error"))
    for finding in warnings:
        print(finding.render("warning"))


def main() -> int:
    args = parse_args()
    path = Path(args.markdown).expanduser().resolve()
    try:
        markdown = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print("Editor output: FAIL")
        print(f"- error [unreadable-file]: не удалось прочитать {path}: {exc}")
        return 1

    errors, warnings = validate_markdown(markdown)
    print_result(errors, warnings)
    return int(bool(errors))


if __name__ == "__main__":
    sys.exit(main())
