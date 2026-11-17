"""Связка итоговых файлов публикации: статья, шорткоды, SEO и манифест.

После правок статьи легко получить пакет, где `article.md` уже исправлен, а
`article-shortcodes.md` и `seo.json` остались от прошлой версии. Модуль ловит
это жёстко, до публикации:

* текст без шорткодов посимвольно равен статье (нормализуется только CRLF);
* шорткоды сбалансированы, не вложены, не пусты, тег соответствует формату
  (`hs_bg` — Поля сражений, `hs_card` — остальные), ID есть в каталоге;
* `seo.json` полон для IndexPilot, его `article_sha256` совпадает со статьёй,
  шорткоды в ответах корректны, запреты владельца и тавтология «в лобби с
  <Типом>» не просочились в SEO;
* вёрстка статьи по `editor/СТИЛЬ.md`: без «Обратите внимание» у `[su_panel]`,
  панель обновления раньше блока ссылок, в `[gallery]` не больше 3 карт в ряд,
  жирные режим и предмет во вступлении (предупреждение).

CLI::

    python -m editorteam.publication_bundle verify --article A.md --shortcodes A-shortcodes.md --seo seo.json
    python -m editorteam.publication_bundle stamp-seo --article A.md --seo seo.json
    python -m editorteam.publication_bundle pack --article A.md --shortcodes S.md --seo seo.json --output-dir out/

Отчёт печатается JSON; код выхода 0 — пакет согласован, 1 — есть ошибки.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .publication_context import literal_errors
from .wordpress import Card, ExportError, HearthstoneFormat, load_catalog, parse_format

ARTICLE_NAME = "article.md"
SHORTCODES_NAME = "article-shortcodes.md"
SEO_NAME = "seo.json"
MANIFEST_NAME = "bundle-manifest.json"
BUNDLE_NAMES = (ARTICLE_NAME, SHORTCODES_NAME, SEO_NAME, MANIFEST_NAME)

SEO_REQUIRED = ("title", "description", "focus_keyword", "answer", "faq", "schema_type")
SEO_PLAIN_FIELDS = ("title", "description", "focus_keyword")
SHA256 = re.compile(r"[a-f0-9]{64}")
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,199}")

# любой токен, похожий на тег шорткода карты; строгий разбор — ниже
TAG = re.compile(r"\[(?P<close>/?)(?P<tag>hs_bg|hs_card)\b(?P<attrs>[^\]\n]*)\]", re.IGNORECASE)
TAG_START = re.compile(r"\[/?hs_(?:bg|card)\b", re.IGNORECASE)
OPEN_ATTRS = re.compile(r'\s+id="(?P<id>[A-Za-z0-9_]+)"\s*')

# Типы существ Полей сражений: имя для сообщения и образец любой формы слова.
# Существо типа X появляется только в лобби с X, поэтому «хорош в лобби со
# Зверями» про Зверя — тавтология.
BG_TYPES: dict[str, tuple[str, str]] = {
    "beast": ("Звери", r"звер\w*"),
    "murloc": ("Мурлоки", r"мурлок\w*"),
    "dragon": ("Драконы", r"дракон\w*"),
    "demon": ("Демоны", r"демон\w*"),
    "mech": ("Механизмы", r"механизм\w*"),
    "elemental": ("Элементали", r"элементал\w*"),
    "pirate": ("Пираты", r"пират\w*"),
    "undead": ("Нежить", r"нежит\w*"),
    "quilboar": ("Свинобразы", r"свинобраз\w*"),
    "naga": ("Наги", r"наг(?:а|и|е|у|ой|ам|ами|ах|ов)?"),
}
TYPE_RE = {
    key: re.compile(rf"(?<!\w)(?:{pattern})(?!\w)", re.IGNORECASE)
    for key, (_, pattern) in BG_TYPES.items()
}
TYPE_ALIASES = {"mechanical": "mech", "mechs": "mech", "beasts": "beast", "murlocs": "murloc",
                "dragons": "dragon", "demons": "demon", "elementals": "elemental",
                "pirates": "pirate", "quilboars": "quilboar", "nagas": "naga"}
LOBBY = re.compile(
    r"(?<!\w)в\s+лобби\s+(?:с|со)\s+(?:[\w-]+\s+){0,2}?(?P<type>"
    + "|".join(f"(?:{pattern})" for _, pattern in BG_TYPES.values())
    + r")(?!\w)",
    re.IGNORECASE,
)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


@dataclass
class Issue:
    code: str
    message: str
    file: str = ""
    line: int | None = None
    field: str = ""

    def to_dict(self) -> dict:
        out = {"code": self.code, "message": self.message}
        if self.file:
            out["file"] = self.file
        if self.line is not None:
            out["line"] = self.line
        if self.field:
            out["field"] = self.field
        return out


@dataclass
class BundleReport:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    article_sha256: str | None = None
    format: str | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def codes(self) -> set[str]:
        return {issue.code for issue in self.errors}

    def add(self, code: str, message: str, **where) -> None:
        self.errors.append(Issue(code, message, **where))

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "format": self.format,
            "article_sha256": self.article_sha256,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": list(self.warnings),
        }


@dataclass
class CatalogIndex:
    """ID → форматы и (если каталог их знает) типы существ."""

    formats: dict[str, set[HearthstoneFormat]] = field(default_factory=dict)
    types: dict[str, set[str]] = field(default_factory=dict)

    @classmethod
    def from_cards(cls, cards, types: dict[str, set[str]] | None = None) -> "CatalogIndex":
        index = cls(types=dict(types or {}))
        for card in cards:
            index.formats.setdefault(card.id, set()).update(card.formats)
        return index


# ── основа ───────────────────────────────────────────────────────────────────


def normalize(text: str) -> str:
    """Единственная допустимая нормализация: CRLF → LF."""
    return text.replace("\r\n", "\n")


def article_digest(article: str) -> str:
    """SHA-256 статьи в UTF-8 после нормализации CRLF → LF."""
    return hashlib.sha256(normalize(article).encode("utf-8")).hexdigest()


def strip_shortcodes(text: str) -> str:
    """Снять теги `[hs_bg id=…]`/`[/hs_bg]`/`[hs_card id=…]`/`[/hs_card]`, оставив текст."""
    return TAG.sub("", text)


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _expected_tag(game_format: HearthstoneFormat | None) -> str | None:
    if game_format is None:
        return None
    return "hs_bg" if game_format is HearthstoneFormat.BATTLEGROUNDS else "hs_card"


def first_difference(expected: str, actual: str) -> tuple[int, int, str, str]:
    """(строка, колонка, строка статьи, строка из шорткодов) первого расхождения."""
    left = expected.split("\n")
    right = actual.split("\n")
    for number in range(max(len(left), len(right))):
        a = left[number] if number < len(left) else None
        b = right[number] if number < len(right) else None
        if a != b:
            a_text, b_text = a if a is not None else "<нет строки>", b if b is not None else "<нет строки>"
            column = 1
            if a is not None and b is not None:
                column = next(
                    (i + 1 for i, (x, y) in enumerate(zip(a, b)) if x != y),
                    min(len(a), len(b)) + 1,
                )
            return number + 1, column, a_text, b_text
    return 0, 0, "", ""


# ── шорткоды ─────────────────────────────────────────────────────────────────


def check_shortcodes(
    text: str,
    report: BundleReport,
    *,
    where: dict,
    expected_tag: str | None,
    game_format: HearthstoneFormat | None,
    catalog: CatalogIndex | None,
) -> list[tuple[str, str, str]]:
    """Проверить разметку шорткодов. Возвращает (тег, id, текст) корректных пар."""
    pairs: list[tuple[str, str, str]] = []
    tokens = list(TAG.finditer(text))
    covered = {m.start() for m in tokens}
    for stray in TAG_START.finditer(text):
        if stray.start() not in covered:
            report.add("shortcode_malformed", f"незакрытый тег шорткода «{text[stray.start():stray.start() + 30]}»",
                       line=_line_of(text, stray.start()), **where)
    open_tag: tuple[re.Match, str, str] | None = None
    for token in tokens:
        tag = token.group("tag").lower()
        line = _line_of(text, token.start())
        if token.group("tag") != tag:
            report.add("shortcode_malformed", f"тег в другом регистре: «{token.group(0)}»", line=line, **where)
        if token.group("close"):
            if token.group("attrs").strip():
                report.add("shortcode_malformed", f"у закрывающего тега есть атрибуты: «{token.group(0)}»",
                           line=line, **where)
            if open_tag is None:
                report.add("shortcode_unbalanced", f"закрывающий «{token.group(0)}» без открывающего",
                           line=line, **where)
                continue
            opener, open_name, card_id = open_tag
            open_tag = None
            if open_name != tag:
                report.add("shortcode_unbalanced",
                           f"«{opener.group(0)}» закрыт чужим тегом «{token.group(0)}»", line=line, **where)
                continue
            inner = text[opener.end():token.start()]
            if not inner.strip():
                report.add("shortcode_empty", f"пустой шорткод «{opener.group(0)}»", line=line, **where)
                continue
            if "\n" in inner or "\r" in inner:
                report.add("shortcode_multiline", f"шорткод «{opener.group(0)}» переносит строку",
                           line=line, **where)
                continue
            if card_id:
                pairs.append((tag, card_id, inner))
            continue
        # открывающий
        if open_tag is not None and "\n" in text[open_tag[0].end():token.start()]:
            # шорткод не переносит строку: прошлый тег просто не закрыт
            report.add("shortcode_unbalanced", f"«{open_tag[0].group(0)}» не закрыт",
                       line=_line_of(text, open_tag[0].start()), **where)
            open_tag = None
        if open_tag is not None:
            report.add("shortcode_nested",
                       f"шорткод «{token.group(0)}» вложен в «{open_tag[0].group(0)}»", line=line, **where)
            continue
        attrs = OPEN_ATTRS.fullmatch(token.group("attrs"))
        card_id = attrs.group("id") if attrs else ""
        if not attrs:
            report.add("shortcode_malformed", f"ожидалось {tag} id=\"…\": «{token.group(0)}»", line=line, **where)
        if expected_tag and tag != expected_tag:
            mode = "Полей сражений" if expected_tag == "hs_bg" else "этого формата"
            report.add("shortcode_wrong_tag",
                       f"«{token.group(0)}»: для {mode} нужен тег [{expected_tag}]", line=line, **where)
        if card_id and catalog is not None:
            formats = catalog.formats.get(card_id)
            if formats is None:
                report.add("shortcode_unknown_id", f"ID {card_id} нет в каталоге", line=line, **where)
            elif game_format is not None and game_format not in formats:
                report.add("shortcode_wrong_format",
                           f"ID {card_id} не подтверждён каталогом для формата {game_format.value}",
                           line=line, **where)
            elif game_format is None:
                bg = HearthstoneFormat.BATTLEGROUNDS
                supported = bg in formats if tag == "hs_bg" else bool(formats - {bg})
                if not supported:
                    report.add("shortcode_wrong_format",
                               f"ID {card_id} не подтверждён каталогом для [{tag}]", line=line, **where)
        open_tag = (token, tag, card_id)
    if open_tag is not None:
        report.add("shortcode_unbalanced", f"«{open_tag[0].group(0)}» не закрыт",
                   line=_line_of(text, open_tag[0].start()), **where)
    return pairs


# ── SEO ──────────────────────────────────────────────────────────────────────


def _types_of(raw: object) -> set[str]:
    values = raw if isinstance(raw, list) else [raw]
    found: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        word = value.strip().casefold()
        if word in {"all", "все", "всё", "любой"}:
            found.update(BG_TYPES)
            continue
        word = TYPE_ALIASES.get(word, word)
        if word in BG_TYPES:
            found.add(word)
            continue
        found.update(key for key, rx in TYPE_RE.items() if rx.fullmatch(value.strip()))
    return found


def load_catalog_index(path: Path) -> CatalogIndex:
    cards = load_catalog(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("cards") if isinstance(raw, dict) else raw
    types: dict[str, set[str]] = {}
    for entry in entries or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        for key in ("types", "type", "races", "race", "tribe", "minion_types"):
            if key in entry:
                types.setdefault(entry["id"], set()).update(_types_of(entry[key]))
    return CatalogIndex.from_cards(cards, types)


def lobby_tautologies(
    text: str, *, context: str = "", catalog: CatalogIndex | None = None
) -> list[str]:
    """Фразы «в лобби с <Типом>» про существо того же типа.

    Тип существа узнаётся по каталогу (поле types у ID шорткода) или по
    самому тексту: тип назван ещё раз в том же предложении или в `context`
    (вопрос FAQ), например «Зверь… хорош в лобби со Зверями».
    """
    found = []
    context_plain = strip_shortcodes(context)
    context_ids = [m.group("id") for m in re.finditer(r'\[hs_bg\s+id="(?P<id>[A-Za-z0-9_]+)"\]', context)]
    for sentence in SENTENCE_SPLIT.split(text):
        plain = strip_shortcodes(sentence)
        ids = context_ids + [
            m.group("id") for m in re.finditer(r'\[hs_bg\s+id="(?P<id>[A-Za-z0-9_]+)"\]', sentence)
        ]
        for match in LOBBY.finditer(plain):
            kind = next(key for key, rx in TYPE_RE.items() if rx.fullmatch(match.group("type")))
            elsewhere = any(
                not (match.start() <= other.start() < match.end())
                for other in TYPE_RE[kind].finditer(plain)
            ) or bool(TYPE_RE[kind].search(context_plain))
            by_catalog = catalog is not None and any(kind in catalog.types.get(i, ()) for i in ids)
            if elsewhere or by_catalog:
                found.append(f"«{' '.join(match.group(0).split())}» про существо типа {BG_TYPES[kind][0]}")
    return found


def check_seo(
    seo: object,
    report: BundleReport,
    *,
    article: str | None,
    require_hash: bool,
    check_hash: bool = True,
    expected_tag: str | None,
    game_format: HearthstoneFormat | None,
    catalog: CatalogIndex | None,
    article_ids: set[str] | None,
    author_context: dict | None,
    seo_file: str = SEO_NAME,
) -> None:
    where = {"file": seo_file}
    if not isinstance(seo, dict):
        report.add("seo_invalid", "seo.json должен быть объектом", **where)
        return
    for name in SEO_REQUIRED:
        if name not in seo:
            report.add("seo_missing_field", f"нет обязательного поля IndexPilot «{name}»", field=name, **where)
    for name in (*SEO_PLAIN_FIELDS, "schema_type"):
        if name in seo and (not isinstance(seo[name], str) or not seo[name].strip()):
            report.add("seo_invalid_field", f"поле «{name}» должно быть непустой строкой", field=name, **where)
    for name in SEO_PLAIN_FIELDS:
        if isinstance(seo.get(name), str) and TAG_START.search(seo[name]):
            report.add("seo_shortcode_in_plain_field", f"в «{name}» шорткод: поле выводится как текст",
                       field=name, **where)
    if "answer" in seo:
        answer = seo["answer"]
        if not isinstance(answer, str) or (not answer.strip() and seo.get("schema_type") != "none"):
            report.add("seo_invalid_field", "«answer» должен быть непустой строкой", field="answer", **where)
    faq = seo.get("faq")
    if "faq" in seo and not isinstance(faq, list):
        report.add("seo_invalid_field", "«faq» должен быть массивом", field="faq", **where)
        faq = []
    faq = faq or []
    for number, item in enumerate(faq, 1):
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("question"), str) or not item["question"].strip()
            or not isinstance(item.get("answer"), str) or not item["answer"].strip()
        ):
            report.add("seo_invalid_field", f"faq[{number}]: нужны непустые question и answer",
                       field=f"faq[{number}]", **where)

    # свежесть
    stamped = seo.get("article_sha256")
    if stamped is None:
        if require_hash:
            report.add("seo_hash_missing",
                       "в seo.json нет article_sha256: нельзя доказать, что SEO собрано по этой статье "
                       "(stamp-seo)", field="article_sha256", **where)
    elif not isinstance(stamped, str) or not SHA256.fullmatch(stamped):
        report.add("seo_invalid_field", "article_sha256 должен быть 64 hex-символа", field="article_sha256", **where)
    elif check_hash and article is not None and stamped != article_digest(article):
        report.add("stale_seo", "статья изменилась после генерации SEO: article_sha256 не совпадает "
                   "со статьёй; пересобрать SEO и выполнить stamp-seo", field="article_sha256", **where)

    # шорткоды и тексты ответов
    rich: list[tuple[str, str, str]] = []  # (поле, текст, контекст)
    if isinstance(seo.get("answer"), str):
        rich.append(("answer", seo["answer"], ""))
    for number, item in enumerate(faq, 1):
        if not isinstance(item, dict):
            continue
        question = item.get("question") if isinstance(item.get("question"), str) else ""
        if question:
            rich.append((f"faq[{number}].question", question, ""))
        if isinstance(item.get("answer"), str):
            rich.append((f"faq[{number}].answer", item["answer"], question))
    for name, text, _ in rich:
        pairs = check_shortcodes(
            text, report, where={"file": seo_file, "field": name},
            expected_tag=expected_tag, game_format=game_format, catalog=catalog,
        )
        if catalog is None and article_ids is not None:
            for _, card_id, inner in pairs:
                if card_id not in article_ids:
                    report.add("seo_shortcode_unconfirmed",
                               f"шорткод {card_id} («{inner}») не встречается в статье и не подтверждён каталогом",
                               file=seo_file, field=name)

    if author_context is not None:
        texts = [(name, seo[name]) for name in ("title", "description") if isinstance(seo.get(name), str)]
        texts += [(name, text) for name, text, _ in rich]
        for name, text in texts:
            for message in literal_errors(author_context, text):
                report.add("forbidden_literal", f"{name}: {message}", file=seo_file, field=name)

    if game_format is HearthstoneFormat.BATTLEGROUNDS or (game_format is None and expected_tag == "hs_bg"):
        for name, text, context in rich:
            if name.endswith(".question"):
                continue
            for message in lobby_tautologies(text, context=context, catalog=catalog):
                report.add("lobby_tautology",
                           f"{name}: тавтология {message} — существо этого типа и так бывает "
                           f"только в лобби со своим типом", file=seo_file, field=name)


# ── вёрстка Манакоста ────────────────────────────────────────────────────────
# Правила из editor/СТИЛЬ.md («Служебные блоки и ссылки», «Галереи и визуалы»,
# «Вступление и первое упоминание карт»).

MAX_GALLERY_COLUMNS = 3
INTRO_PARAGRAPHS = 3
PANEL = re.compile(r"\[su_panel\b[^\]]*\](?P<body>.*?)\[/su_panel\]", re.IGNORECASE | re.DOTALL)
SU_BLOCK = re.compile(r"\[(su_\w+)\b[^\]]*\].*?\[/\1\]", re.IGNORECASE | re.DOTALL)
PANEL_NOISE = re.compile(r"обратите\s+внимание", re.IGNORECASE)
PANEL_UPDATE = re.compile(
    r"(?<!\w)(?:обновл\w*|патч\w*)|\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа"
    r"|сентября|октября|ноября|декабря)|\d{1,2}\.\d{1,2}\.\d{2,4}",
    re.IGNORECASE,
)
# строка блока ссылок: якорь на раздел статьи или ссылка на Telegram/подборку гайдов,
# причём кроме ссылок в строке почти нет текста (ссылка внутри абзаца — не блок)
SECTION_LINK = re.compile(r"\]\(\s*#|href\s*=\s*[\"']#", re.IGNORECASE)
LINK_MARKUP = re.compile(r"\]\(|<a\s|https?://|t\.me/", re.IGNORECASE)
LINK_TOPIC = re.compile(
    r"t\.me/|telegram|телеграм|больше\s+(?:гайдов|статей|материалов)|все\s+(?:гайды|статьи|материалы)",
    re.IGNORECASE,
)
LINK_TEXT = re.compile(r"!?\[[^\]]*\]\([^)]*\)|<a\b.*?</a>|https?://\S+|t\.me/\S+", re.IGNORECASE)
LINK_LINE_MAX_WORDS = 6
NOISE_LABEL_MAX_WORDS = 5
GALLERY = re.compile(r"\[gallery\b(?P<attrs>[^\]]*)\]", re.IGNORECASE)
GALLERY_COLUMNS = re.compile(r"(?<![\w-])columns\s*=\s*[^\w\s\]]?\s*(?P<n>\d+)", re.IGNORECASE)
BOLD = re.compile(r"\*\*[^*\n]+\*\*|__[^_\n]+__|<(?:strong|b)\b[^>]*>", re.IGNORECASE)
BLOCK_SPLIT = re.compile(r"\n[ \t]*\n")
SERVICE_BLOCK = re.compile(r"(?:\[(?!hs_bg\b|hs_card\b)/?[a-z_]+|!\[|<img\b|<figure\b|<!--|-{3,}\s*$|\*{3,}\s*$|\|)",
                           re.IGNORECASE)


def _line_start(text: str, pos: int) -> int:
    return text.rfind("\n", 0, pos) + 1


def _previous_line(text: str, pos: int) -> str:
    """Последняя непустая строка перед позицией `pos`."""
    for line in reversed(text[:_line_start(text, pos)].split("\n")):
        if line.strip():
            return line
    return ""


def _words(text: str) -> int:
    return len(re.findall(r"[^\W_]+", text))


def _is_link_line(line: str) -> bool:
    """Строка блока ссылок: оглавление, Telegram, «Больше гайдов», а не ссылка внутри абзаца."""
    if not (SECTION_LINK.search(line) or (LINK_MARKUP.search(line) and LINK_TOPIC.search(line))):
        return False
    return _words(LINK_TEXT.sub(" ", line)) <= LINK_LINE_MAX_WORDS


def intro_paragraphs(article: str, limit: int = INTRO_PARAGRAPHS) -> list[str]:
    """Первые абзацы вступления: до первого подзаголовка, без H1 и служебных блоков."""
    text = SU_BLOCK.sub("\n\n", article)
    found: list[str] = []
    for block in BLOCK_SPLIT.split(text):
        block = block.strip()
        if not block:
            continue
        if block.startswith("#"):
            if re.match(r"#\s", block) and not found:
                continue  # H1 — заголовок записи, не вступление
            break
        if SERVICE_BLOCK.match(block):
            continue
        found.append(block)
        if len(found) == limit:
            break
    return found


def check_layout(article: str, report: BundleReport, *, file: str = ARTICLE_NAME) -> None:
    """Вёрстка статьи для WordPress: панель обновления, ссылки, галереи, вступление."""
    panels = list(PANEL.finditer(article))
    for panel in panels:
        line = _line_of(article, panel.start())
        if PANEL_NOISE.search(panel.group(0)):
            report.add("bundle.banned_panel_noise",
                       "в [su_panel] «Обратите внимание»: панель и так выделяет текст, уберите шумную фразу",
                       file=file, line=line)
        else:
            label = _previous_line(article, panel.start())
            if PANEL_NOISE.search(label) and _words(label) <= NOISE_LABEL_MAX_WORDS:
                report.add("bundle.banned_panel_noise",
                           "над [su_panel] подпись «Обратите внимание»: панель и так выделяет текст, "
                           "уберите шумную фразу", file=file, line=line)

    updates = [panel for panel in panels if PANEL_UPDATE.search(panel.group("body"))]
    if updates:
        first = updates[0]
        for match in re.finditer(r"[^\n]+", article[:first.start()]):
            if _is_link_line(match.group(0)):
                report.add("bundle.panel_order",
                           f"блок ссылок (строка {_line_of(article, match.start())}) стоит раньше панели "
                           f"обновления [su_panel]: поставьте панель с датой и патчем перед ссылками на "
                           f"разделы и Telegram, а ссылки отделите линией ---",
                           file=file, line=_line_of(article, first.start()))
                break

    for gallery in GALLERY.finditer(article):
        columns = GALLERY_COLUMNS.search(gallery.group("attrs"))
        if columns and int(columns.group("n")) > MAX_GALLERY_COLUMNS:
            report.add("bundle.gallery_columns",
                       f"[gallery] с columns={columns.group('n')}: не больше {MAX_GALLERY_COLUMNS} отдельных "
                       f"карт в ряд, иначе они мельчают; 4 и больше — только одной сборной картинкой",
                       file=file, line=_line_of(article, gallery.start()))

    intro = intro_paragraphs(article)
    if intro and not any(BOLD.search(paragraph) for paragraph in intro):
        report.warnings.append(
            "bundle.intro_bold_missing: в первых абзацах вступления нет жирного выделения — "
            "выделите **режим** и **главный предмет** статьи"
        )


# ── сборка проверки ──────────────────────────────────────────────────────────


def _resolve_format(
    game_format: str | HearthstoneFormat | None, shortcodes: str | None, report: BundleReport
) -> tuple[HearthstoneFormat | None, str | None]:
    if game_format:
        selected = parse_format(game_format)
        return selected, _expected_tag(selected)
    tags = {m.group("tag").lower() for m in TAG.finditer(shortcodes or "") if not m.group("close")}
    if len(tags) > 1:
        report.add("shortcode_mixed_tags", "в статье смешаны [hs_bg] и [hs_card]; укажите --format",
                   file=SHORTCODES_NAME)
        return None, None
    if tags == {"hs_bg"}:
        return HearthstoneFormat.BATTLEGROUNDS, "hs_bg"
    if tags:
        report.warnings.append("формат не указан: теги [hs_card] проверены без привязки к Стандарту/Вольному/Арене")
        return None, "hs_card"
    return None, None


def verify_texts(
    article: str,
    *,
    shortcodes: str | None = None,
    seo: object | None = None,
    catalog: CatalogIndex | None = None,
    author_context: dict | None = None,
    game_format: str | HearthstoneFormat | None = None,
    require_seo_hash: bool = False,
    check_seo_hash: bool = True,
    names: dict | None = None,
) -> BundleReport:
    """Проверка связки по уже прочитанным текстам (для тестов и pack)."""
    names = {"article": ARTICLE_NAME, "shortcodes": SHORTCODES_NAME, "seo": SEO_NAME, **(names or {})}
    report = BundleReport()
    article = normalize(article)
    report.article_sha256 = article_digest(article)
    if shortcodes is not None:
        shortcodes = normalize(shortcodes)
    try:
        selected, expected_tag = _resolve_format(game_format, shortcodes, report)
    except ExportError as exc:
        report.add("format_invalid", str(exc))
        return report
    report.format = selected.value if selected else None

    if TAG_START.search(article):
        report.add("article_has_shortcodes", "в статье без шорткодов есть теги шорткодов",
                   file=names["article"], line=_line_of(article, TAG_START.search(article).start()))
    check_layout(article, report, file=names["article"])

    article_ids: set[str] | None = None
    if shortcodes is not None:
        stripped = strip_shortcodes(shortcodes)
        if stripped != article:
            line, column, left, right = first_difference(article, stripped)
            report.add(
                "text_mismatch",
                f"текст без шорткодов расходится со статьёй, строка {line}, позиция {column}: "
                f"статья «{left[:160]}» ≠ шорткоды «{right[:160]}»",
                file=names["shortcodes"], line=line,
            )
        pairs = check_shortcodes(
            shortcodes, report, where={"file": names["shortcodes"]},
            expected_tag=expected_tag, game_format=selected, catalog=catalog,
        )
        article_ids = {card_id for _, card_id, _ in pairs}
    else:
        report.warnings.append("файл с шорткодами не передан: совпадение текста не проверено")
    if catalog is None:
        report.warnings.append("каталог не передан: ID шорткодов не сверены")

    if seo is not None:
        check_seo(
            seo, report, article=article, require_hash=require_seo_hash, check_hash=check_seo_hash,
            expected_tag=expected_tag, game_format=selected, catalog=catalog,
            article_ids=article_ids, author_context=author_context, seo_file=names["seo"],
        )
    else:
        report.warnings.append("seo.json не передан: SEO не проверено")
    return report


def _read_text(path: Path, report: BundleReport, label: str) -> str | None:
    try:
        return path.read_bytes().decode("utf-8-sig")
    except OSError as exc:
        report.add("read_error", f"{label}: не удалось прочитать {path}: {exc.strerror or exc}", file=str(path))
    except UnicodeDecodeError:
        report.add("read_error", f"{label}: {path} не в UTF-8", file=str(path))
    return None


def _read_json(path: Path, report: BundleReport, label: str) -> object | None:
    text = _read_text(path, report, label)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        report.add("json_invalid", f"{label}: некорректный JSON ({exc.msg}, строка {exc.lineno})",
                   file=str(path), line=exc.lineno)
        return None


@dataclass
class _Inputs:
    article: str | None
    shortcodes: str | None = None
    seo: object | None = None
    seo_raw: str | None = None
    catalog: CatalogIndex | None = None
    author_context: dict | None = None


def _load_inputs(args_like: dict, report: BundleReport) -> _Inputs:
    article = _read_text(Path(args_like["article"]), report, "статья")
    inputs = _Inputs(article=article)
    if args_like.get("shortcodes"):
        inputs.shortcodes = _read_text(Path(args_like["shortcodes"]), report, "шорткоды")
    if args_like.get("seo"):
        inputs.seo_raw = _read_text(Path(args_like["seo"]), report, "seo.json")
        if inputs.seo_raw is not None:
            try:
                inputs.seo = json.loads(inputs.seo_raw)
            except json.JSONDecodeError as exc:
                report.add("json_invalid", f"seo.json: некорректный JSON ({exc.msg}, строка {exc.lineno})",
                           file=str(args_like["seo"]), line=exc.lineno)
    if args_like.get("catalog"):
        try:
            inputs.catalog = load_catalog_index(Path(args_like["catalog"]))
        except (ExportError, OSError, json.JSONDecodeError) as exc:
            report.add("catalog_invalid", f"каталог: {exc}", file=str(args_like["catalog"]))
    if args_like.get("author_context"):
        context = _read_json(Path(args_like["author_context"]), report, "author context")
        if context is not None:
            if not isinstance(context, dict) or not isinstance(context.get("requirements"), list):
                report.add("author_context_invalid", "author context: нужен объект с массивом requirements",
                           file=str(args_like["author_context"]))
            else:
                inputs.author_context = context
    return inputs


def verify(
    article: str | Path,
    *,
    shortcodes: str | Path | None = None,
    seo: str | Path | None = None,
    catalog: str | Path | None = None,
    author_context: str | Path | None = None,
    game_format: str | None = None,
    require_seo_hash: bool = False,
) -> BundleReport:
    """Проверить связку файлов на диске."""
    loading = BundleReport()
    paths = {"article": article, "shortcodes": shortcodes, "seo": seo,
             "catalog": catalog, "author_context": author_context}
    inputs = _load_inputs(paths, loading)
    if inputs.article is None or loading.errors:
        return loading
    return verify_texts(
        inputs.article, shortcodes=inputs.shortcodes, seo=inputs.seo, catalog=inputs.catalog,
        author_context=inputs.author_context, game_format=game_format, require_seo_hash=require_seo_hash,
        names={
            "article": Path(article).name,
            "shortcodes": Path(shortcodes).name if shortcodes else SHORTCODES_NAME,
            "seo": Path(seo).name if seo else SEO_NAME,
        },
    )


# ── запись ───────────────────────────────────────────────────────────────────


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _dump_json(data: object) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def stamp_seo(
    article: str | Path,
    seo: str | Path,
    *,
    output: str | Path | None = None,
    game_format: str | None = None,
) -> BundleReport:
    """Записать в seo.json актуальный article_sha256, если поля SEO в порядке."""
    loading = BundleReport()
    inputs = _load_inputs({"article": article, "seo": seo}, loading)
    if inputs.article is None or loading.errors:
        return loading
    report = verify_texts(
        inputs.article, seo=inputs.seo, game_format=game_format, check_seo_hash=False,
        names={"seo": Path(seo).name},
    )
    if report.errors:
        return report
    data = dict(inputs.seo)
    data["article_sha256"] = report.article_sha256
    _atomic_write(Path(output or seo), _dump_json(data))
    return report


def pack(
    article: str | Path,
    output_dir: str | Path,
    *,
    shortcodes: str | Path | None = None,
    seo: str | Path | None = None,
    catalog: str | Path | None = None,
    author_context: str | Path | None = None,
    game_format: str | None = None,
    slug: str | None = None,
    require_seo_hash: bool = True,
) -> tuple[BundleReport, dict | None]:
    """Проверить связку и атомарно записать согласованный пакет с манифестом.

    Если каталога пакета ещё нет, он появляется одним переименованием. Если
    есть, сначала удаляется старый манифест, затем заменяются файлы, и новый
    манифест пишется последним: пакет без манифеста считается недособранным.
    """
    report = verify(
        article, shortcodes=shortcodes, seo=seo, catalog=catalog, author_context=author_context,
        game_format=game_format, require_seo_hash=require_seo_hash,
    )
    if slug is not None and not SLUG.fullmatch(slug):
        report.add("slug_invalid", "slug: только латиница в нижнем регистре, цифры и дефис")
    if report.ok and slug and seo:
        seo_data = json.loads(Path(seo).read_text(encoding="utf-8-sig"))
        seo_slug = str(seo_data.get("slug", "")).strip().strip("/").split("/")[-1]
        if seo_slug and seo_slug != slug:
            report.add("seo_slug_mismatch", f"slug пакета «{slug}» не совпадает со slug в seo.json «{seo_slug}»",
                       file=Path(seo).name, field="slug")
    if not report.ok:
        return report, None

    files: dict[str, bytes] = {
        ARTICLE_NAME: normalize(Path(article).read_bytes().decode("utf-8-sig")).encode("utf-8"),
    }
    if shortcodes:
        files[SHORTCODES_NAME] = normalize(Path(shortcodes).read_bytes().decode("utf-8-sig")).encode("utf-8")
    if seo:
        files[SEO_NAME] = Path(seo).read_bytes().decode("utf-8-sig").encode("utf-8")
    manifest = {
        "schema_version": 1,
        "tool": "editorteam.publication_bundle",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "slug": slug,
        "format": report.format,
        "article_sha256": report.article_sha256,
        "files": {
            name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for name, data in files.items()
        },
        "checks": {
            "text_identical": bool(shortcodes),
            "shortcodes": bool(shortcodes),
            "seo_fresh": bool(seo),
            "catalog": bool(catalog),
            "author_context": bool(author_context),
        },
        "warnings": list(report.warnings),
    }
    files[MANIFEST_NAME] = _dump_json(manifest)

    target = Path(output_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.bundle-", dir=target.parent))
    try:
        for name, data in files.items():
            (staging / name).write_bytes(data)
        if not target.exists():
            os.replace(staging, target)
            return report, manifest
        (target / MANIFEST_NAME).unlink(missing_ok=True)
        for name in BUNDLE_NAMES:
            if name not in files:
                (target / name).unlink(missing_ok=True)
        for name in files:
            if name != MANIFEST_NAME:
                os.replace(staging / name, target / name)
        os.replace(staging / MANIFEST_NAME, target / MANIFEST_NAME)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return report, manifest


# ── CLI ──────────────────────────────────────────────────────────────────────

FORMATS = ("battlegrounds", "standard", "wild", "arena")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m editorteam.publication_bundle",
        description="Сборка и проверка связки статья + шорткоды + seo.json + манифест",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--article", required=True, help="статья без шорткодов (.md)")
        p.add_argument("--shortcodes", help="та же статья с шорткодами (-shortcodes.md)")
        p.add_argument("--seo", help="seo.json для IndexPilot")
        p.add_argument("--catalog", help="каталог карт (JSON) для сверки ID")
        p.add_argument("--author-context", help="author context с forbidden_literals")
        p.add_argument("--format", choices=FORMATS, help="формат: hs_bg для battlegrounds, иначе hs_card")

    verify_p = sub.add_parser("verify", help="проверить связку")
    common(verify_p)
    verify_p.add_argument("--require-seo-hash", action="store_true",
                          help="отсутствие article_sha256 в seo.json — ошибка")

    stamp_p = sub.add_parser("stamp-seo", help="записать article_sha256 в seo.json")
    stamp_p.add_argument("--article", required=True)
    stamp_p.add_argument("--seo", required=True)
    stamp_p.add_argument("--output", help="куда записать (по умолчанию — поверх --seo)")
    stamp_p.add_argument("--format", choices=FORMATS)

    pack_p = sub.add_parser("pack", help="проверить и записать согласованный пакет с манифестом")
    common(pack_p)
    pack_p.add_argument("--output-dir", required=True)
    pack_p.add_argument("--slug")
    pack_p.add_argument("--no-require-seo-hash", action="store_true",
                        help="не требовать article_sha256 (по умолчанию требуется)")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    if args.command == "verify":
        report = verify(
            args.article, shortcodes=args.shortcodes, seo=args.seo, catalog=args.catalog,
            author_context=args.author_context, game_format=args.format,
            require_seo_hash=args.require_seo_hash,
        )
        payload = report.to_dict()
    elif args.command == "stamp-seo":
        report = stamp_seo(args.article, args.seo, output=args.output, game_format=args.format)
        payload = {**report.to_dict(), "written": str(args.output or args.seo) if report.ok else None}
    else:
        report, manifest = pack(
            args.article, args.output_dir, shortcodes=args.shortcodes, seo=args.seo,
            catalog=args.catalog, author_context=args.author_context, game_format=args.format,
            slug=args.slug, require_seo_hash=not args.no_require_seo_hash,
        )
        payload = {**report.to_dict(), "output_dir": str(args.output_dir) if manifest else None,
                   "manifest": manifest}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
