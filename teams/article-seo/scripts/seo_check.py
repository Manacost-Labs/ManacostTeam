#!/usr/bin/env python3
"""Проверка SEO-полей IndexPilot для статьи Манакоста без сети и зависимостей.

Правила повторяют анализ плагина IndexPilot: ширина заголовка, длина описания,
поиск главного запроса с русским стеммером и игровыми синонимами, первый абзац,
слаг, alt картинок, обязательные разделы гайда, краткий ответ и FAQ.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

TITLE_MAX_PX = 580
TITLE_MIN_PX = 200
DESCRIPTION_RANGE = (120, 155)
ANSWER_RANGE = (40, 60)
MAX_RELATED = 4
MAX_FAQ = 10
SLUG_MAX_WORDS = 7
SLUG_MAX_BYTES = 75
DENSITY_RANGE = (0.5, 2.5)
MIN_WORDS = 300
SCHEMA_TYPES = {
    "": "Авто",
    "Article": "Статья",
    "NewsArticle": "Новость",
    "TechArticle": "Гайд",
    "none": "Без пометки",
}
WEIGHTS = {
    "keyword_set": 6,
    "keyword_in_title": 9,
    "keyword_at_title_start": 3,
    "keyword_in_description": 6,
    "keyword_in_slug": 6,
    "keyword_in_first_paragraph": 6,
    "keyword_in_subheadings": 3,
    "keyword_in_image_alt": 3,
    "keyword_density": 6,
    "title_width": 6,
    "description_length": 6,
    "slug_length": 3,
    "content_length": 6,
    "internal_links": 5,
    "external_links": 2,
    "images": 3,
    "single_h1": 3,
    "answer": 3,
    "image_alt": 3,
}
WORD = re.compile(r"[^\W_]+")

# --- Русский стеммер: порт RussianStemmer.php из IndexPilot. -----------------
_RV = re.compile(r"^(.*?[аеиоуыэюя])(.*)$", re.DOTALL)
_PERFECTIVE = re.compile(r"((ив|ивши|ившись|ыв|ывши|ывшись)|((?<=[ая])(в|вши|вшись)))$")
_REFLEXIVE = re.compile(r"(с[яь])$")
_ADJECTIVE = re.compile(
    r"(ее|ие|ые|ое|ими|ыми|ей|ий|ый|ой|ем|им|ым|ом|его|ого|ему|ому|их|ых|ую|юю|ая|яя|ою|ею)$"
)
_PARTICIPLE = re.compile(r"((ивш|ывш|ующ)|((?<=[ая])(ем|нн|вш|ющ|щ)))$")
_VERB = re.compile(
    r"((ила|ыла|ена|ейте|уйте|ите|или|ыли|ей|уй|ил|ыл|им|ым|ен|ило|ыло|ено|ят|ует|уют|ит|ыт|ены|ить|ыть|ишь|ую|ю)"
    r"|((?<=[ая])(ла|на|ете|йте|ли|й|л|ем|н|ло|но|ет|ют|ны|ть|ешь|нно)))$"
)
_NOUN = re.compile(
    r"(а|ев|ов|ие|ье|е|иями|ями|ами|еи|ии|и|ией|ей|ой|ий|й|иям|ям|ием|ем|ам|ом|о|у|ах|иях|ях|ы|ь|ию|ью|ю|ия|ья|я)$"
)
_DERIVATIONAL = re.compile(r"[^аеиоуыэюя][аеиоуыэюя]+[^аеиоуыэюя]+[аеиоуыэюя].*(?<=о)сть?$")
_DERIVATIONAL_END = re.compile(r"ость?$")
_STEMS: dict[str, str] = {}


def _cut(text: str, pattern: re.Pattern) -> tuple[str, bool]:
    result = pattern.sub("", text, count=1)
    return result, result != text


def russian_stem(word: str) -> str:
    word = word.lower().replace("ё", "е")
    if word in _STEMS:
        return _STEMS[word]
    stem = word
    parts = _RV.match(word)
    if parts and parts.group(2):
        start, rv = parts.group(1), parts.group(2)
        rv, cut = _cut(rv, _PERFECTIVE)
        if not cut:
            rv, _ = _cut(rv, _REFLEXIVE)
            rv, cut = _cut(rv, _ADJECTIVE)
            if cut:
                rv, _ = _cut(rv, _PARTICIPLE)
            else:
                rv, cut = _cut(rv, _VERB)
                if not cut:
                    rv, _ = _cut(rv, _NOUN)
        rv, _ = _cut(rv, re.compile(r"и$"))
        if _DERIVATIONAL.search(rv):
            rv, _ = _cut(rv, _DERIVATIONAL_END)
        rv, cut = _cut(rv, re.compile(r"ь$"))
        if not cut:
            rv, _ = _cut(rv, re.compile(r"ейше?$"))
            rv = re.sub(r"нн$", "н", rv)
        stem = start + rv
    _STEMS[word] = stem
    return stem


def english_stem(word: str) -> str:
    word = word.lower()
    length = len(word)
    if length <= 3:
        return word
    if word.endswith("ies") and length > 4:
        return word[:-3] + "y"
    if word.endswith("sses"):
        return word[:-2]
    if word.endswith("ing") and length > 5:
        return word[:-3]
    if word.endswith("ed") and length > 4:
        return word[:-2]
    if word.endswith("s") and not re.search(r"(ss|us|is)$", word):
        return word[:-1]
    return word


def stem(word: str) -> str:
    if re.search(r"[Ѐ-ӿ]", word):
        return russian_stem(word)
    return english_stem(word)


# --- Игровой словарь: синонимы и классы из Lexicon.php. ----------------------
FORMS = {
    "дк": ["дк"],
    "дх": ["дх"],
    "дру": ["дру"],
    "бг": ["бг"],
    "хант": ["хант", "ханта", "ханту", "хантом", "ханте", "ханты", "хантов", "хантам", "хантами", "хантах"],
    "пал": ["пал", "палу", "палом", "пале", "палы", "палов", "палам", "палами", "палах"],
    "прист": ["прист", "приста", "присту", "пристом", "присте", "присты", "пристов", "пристам", "пристами", "пристах"],
    "рога": ["рога", "роги", "роге", "рогу", "рогой"],
    "шам": ["шам", "шама", "шаму", "шамом", "шаме", "шамы", "шамов", "шамам", "шамами", "шамах"],
    "лок": ["лок", "лока", "локу", "локом", "локе", "локи", "локов", "локам", "локами", "локах"],
    "вар": ["вар", "вара", "вару", "варом", "варе", "вары", "варов", "варам", "варами", "варах"],
}
GROUPS = {
    "колода": ["дека", "сборка", "билд", "деклист", "дек"],
    "гайд": ["руководство", "разбор", "гид"],
    "муллиган": ["мулиган", "стартовая рука"],
    "матчап": ["матчапы", "противостояние"],
    "замена": ["замены", "альтернатива"],
}
CLASSES = {
    "Рыцарь смерти": ["дк"],
    "Охотник на демонов": ["дх"],
    "Друид": ["дру"],
    "Охотник": ["хант"],
    "Маг": [],
    "Паладин": ["пал"],
    "Жрец": ["прист"],
    "Разбойник": ["рога"],
    "Шаман": ["шам"],
    "Чернокнижник": ["лок", "варлок"],
    "Воин": ["вар"],
}
STOP_WORDS = {
    "и", "в", "во", "на", "для", "по", "от", "с", "со", "к", "о", "об", "из", "за", "у",
    "the", "a", "an", "of", "for", "in", "on", "to", "and",
}


def split_words(text: str) -> list[str]:
    return WORD.findall(text.lower().replace("ё", "е"))


class Lexicon:
    def __init__(self, extra: dict[str, list[str]] | None = None) -> None:
        self.forms: dict[str, str] = {}
        self.rules: dict[str, list[tuple[tuple[str, ...], str]]] = {}
        groups = {key: list(value) for key, value in GROUPS.items()}
        for canonical, aliases in (extra or {}).items():
            groups.setdefault(canonical, []).extend(aliases)
        for canonical, aliases in groups.items():
            self._add(canonical, [canonical, *aliases])
        for name, aliases in CLASSES.items():
            self._add(name, [name, *aliases])
        for rules in self.rules.values():
            rules.sort(key=lambda rule: -len(rule[0]))

    def _add(self, value: str, aliases: list[str]) -> None:
        for alias in aliases:
            words = split_words(alias)
            if not words:
                continue
            if len(words) == 1 and words[0] in FORMS:
                for form in FORMS[words[0]]:
                    self.forms[form] = value
                continue
            stems = tuple(russian_stem(word) for word in words)
            self.rules.setdefault(stems[0], []).append((stems, value))

    def canonical_words(self, text: str) -> list[str]:
        words = split_words(text)
        result: list[str] = []
        index = 0
        while index < len(words):
            word = words[index]
            for stems, value in self.rules.get(russian_stem(word), []):
                window = words[index : index + len(stems)]
                if tuple(russian_stem(item) for item in window) == stems:
                    result.extend(split_words(value))
                    index += len(stems)
                    break
            else:
                if word in self.forms:
                    result.extend(split_words(self.forms[word]))
                else:
                    result.append(word)
                index += 1
        return result


class Matcher:
    def __init__(self, lexicon: Lexicon) -> None:
        self.lexicon = lexicon

    def stems(self, text: str) -> list[str]:
        return [stem(word) for word in self.lexicon.canonical_words(text)]

    def keyword_stems(self, keyword: str) -> list[str]:
        return self._significant(self.lexicon.canonical_words(keyword))

    @staticmethod
    def _significant(words: list[str]) -> list[str]:
        significant = [word for word in words if word not in STOP_WORDS]
        return [stem(word) for word in (significant or words)]

    @staticmethod
    def _find(text: list[str], keyword: list[str], limit: int) -> list[int]:
        found: list[int] = []
        if not keyword or not text:
            return found
        window = len(keyword) + 2
        index = 0
        while index < len(text) and len(found) < limit:
            if text[index] not in keyword:
                index += 1
                continue
            remaining: dict[str, int] = {}
            for item in keyword:
                remaining[item] = remaining.get(item, 0) + 1
            last = -1
            for offset in range(window):
                if index + offset >= len(text):
                    break
                current = text[index + offset]
                if remaining.get(current):
                    remaining[current] -= 1
                    last = index + offset
            if not any(remaining.values()):
                found.append(index)
                index = last + 1
            else:
                index += 1
        return found

    def position(self, text: str, keyword: str) -> int:
        found = self._find(self.stems(text), self.keyword_stems(keyword), 1)
        return found[0] if found else -1

    def count(self, text: str, keyword: str) -> int:
        return len(self._find(self.stems(text), self.keyword_stems(keyword), 10**9))

    def contains(self, text: str, keyword: str) -> bool:
        return self.position(text, keyword) >= 0

    def length(self, keyword: str) -> int:
        return len(self.keyword_stems(keyword))

    def in_slug(self, slug: str, keyword: str) -> bool:
        slug_words = [word for word in slug.lower().split("-") if word]

        def covered(stems: list[str]) -> bool:
            if not stems:
                return False
            for item in stems:
                latin = slugify(item)
                if not latin or not any(word.startswith(latin) for word in slug_words):
                    return False
            return True

        plain = self._significant(WORD.findall(keyword.lower()))
        return covered(plain) or covered(self.keyword_stems(keyword))


# --- Транслитерация слага и ширина заголовка. --------------------------------
TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "zh",
    "з": "z", "и": "i", "й": "j", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "cz",
    "ч": "ch", "ш": "sh", "щ": "shh", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}


def slugify(text: str) -> str:
    latin = "".join(TRANSLIT.get(char, char) for char in text.lower())
    return re.sub(r"[^a-z0-9]+", "-", latin).strip("-")


def title_width(text: str) -> int:
    width = 0.0
    for char in text:
        if char in "—–":
            width += 20.0
        elif char in " .,:;!|'`ijltfrI()[]":
            width += 5.6
        elif char in "mwMWжшщмыюЖШЩМЫЮ@%":
            width += 16.0
        elif char in "гт":
            width += 8.6
        elif char.isdigit():
            width += 11.1
        elif char.isupper() and char.lower() != char:
            width += 13.6
        else:
            width += 10.6
    return int(width + 0.5)


# --- Разбор статьи (HTML или Markdown). --------------------------------------
_PAIRED = re.compile(r"\[([a-z_][\w-]*)\b[^\]]*\](.*?)\[/\1\]", re.DOTALL | re.IGNORECASE)
_SINGLE = re.compile(r"\[/?[a-z_][\w-]*(?:\s[^\]]*)?\]", re.IGNORECASE)


def reduce_shortcodes(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = _PAIRED.sub(lambda match: match.group(2), text)
    return _SINGLE.sub(" ", text)


def word_count(text: str) -> int:
    return len(WORD.findall(reduce_shortcodes(text)))


def answer_words(text: str) -> int:
    plain = reduce_shortcodes(re.sub(r"<[^>]+>", " ", text))
    return sum(1 for token in plain.split() if WORD.search(token))


class Article:
    def __init__(self) -> None:
        self.paragraphs: list[str] = []
        self.headings: list[tuple[int, str]] = []
        self.images: list[dict] = []
        self.links: list[dict] = []
        self.lists = 0
        self.has_p = False
        self.text_parts: list[str] = []

    @property
    def plain(self) -> str:
        return reduce_shortcodes(" ".join(self.text_parts))

    def first_paragraph(self) -> str | None:
        if self.has_p:
            for paragraph in self.paragraphs:
                text = reduce_shortcodes(paragraph).strip()
                if WORD.search(text):
                    return text
            return ""
        heading_free = [part for part in self.paragraphs]
        words = " ".join(reduce_shortcodes(" ".join(heading_free)).split()).split(" ")
        return " ".join(words[:60])


class _HtmlArticle(HTMLParser):
    def __init__(self, article: Article) -> None:
        super().__init__(convert_charrefs=True)
        self.article = article
        self.stack: list[tuple[str, list[str]]] = []
        self.link: dict | None = None
        self.skip = 0
        self.loose: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = {key: (value or "") for key, value in attrs}
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "p":
            self.article.has_p = True
            self.stack.append(("p", []))
        elif re.fullmatch(r"h[1-6]", tag):
            self.stack.append((tag, []))
        elif tag in ("ul", "ol", "table"):
            self.article.lists += 1
        elif tag == "a":
            self.link = {"href": attributes.get("href", ""), "text": [], "images": [], "aria": attributes.get("aria-label", "")}
        elif tag == "img":
            classes = attributes.get("class", "").split()
            image = {
                "src": attributes.get("src", ""),
                "alt": attrs_value(attrs, "alt"),
                "decorative": "is-decorative" in classes
                or attributes.get("role") == "presentation"
                or attributes.get("aria-hidden") == "true",
            }
            self.article.images.append(image)
            if self.link is not None:
                self.link["images"].append(image)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag == "a" and self.link is not None:
            self.link["text"] = " ".join("".join(self.link["text"]).split())
            self.article.links.append(self.link)
            self.link = None
        elif self.stack and self.stack[-1][0] == tag:
            name, parts = self.stack.pop()
            text = " ".join("".join(parts).split())
            if name == "p":
                self.article.paragraphs.append(text)
            else:
                self.article.headings.append((int(name[1]), text))

    def handle_data(self, data):
        if self.skip:
            return
        self.article.text_parts.append(data)
        if self.stack:
            self.stack[-1][1].append(data)
        elif not self.article.has_p:
            self.loose.append(data)
        if self.link is not None:
            self.link["text"].append(data)


def attrs_value(attrs, name):
    for key, value in attrs:
        if key == name:
            return value or ""
    return None


_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*([^)\s]+)[^)]*\)")
_MD_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(\s*([^)\s]+)[^)]*\)")
_MD_IMAGE_LINK = re.compile(r"\[!\[([^\]]*)\]\([^)]*\)\]\(\s*([^)\s]+)[^)]*\)")


def parse_markdown(source: str) -> Article:
    article = Article()
    article.has_p = True
    for block in re.split(r"\n\s*\n", source):
        lines = [line for line in block.strip().splitlines() if line.strip()]
        if not lines:
            continue
        paragraph: list[str] = []
        for line in lines:
            stripped = line.strip()
            for alt, src in _MD_IMAGE.findall(stripped):
                article.images.append({"src": src, "alt": alt, "decorative": False})
            for match in _MD_IMAGE_LINK.finditer(stripped):
                article.links.append({"href": match.group(2), "text": "", "images": [{"alt": match.group(1)}], "aria": ""})
            rest = _MD_IMAGE.sub("", _MD_IMAGE_LINK.sub("", stripped))
            for match in _MD_LINK.finditer(rest):
                article.links.append({"href": match.group(2), "text": match.group(1).strip(), "images": [], "aria": ""})
            text = _MD_LINK.sub(lambda match: match.group(1), rest)
            heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
            if heading:
                article.headings.append((len(heading.group(1)), text.lstrip("#").strip()))
                article.text_parts.append(text.lstrip("#").strip())
                continue
            if re.match(r"^([-*+]|\d+[.)])\s+", stripped) or stripped.startswith("|"):
                article.lists += 1
                article.text_parts.append(text)
                continue
            paragraph.append(text)
        if paragraph:
            joined = " ".join(paragraph)
            article.paragraphs.append(joined)
            article.text_parts.append(joined)
    return article


def parse_article(source: str) -> Article:
    if re.search(r"<(p|h[1-6]|ul|ol|div|figure|img|a)\b", source, re.IGNORECASE):
        article = Article()
        parser = _HtmlArticle(article)
        parser.feed(source)
        parser.close()
        if not article.has_p:
            # Без <p> плагин берёт первые 60 слов текста без заголовков.
            article.paragraphs = [" ".join(" ".join(parser.loose).split())]
        return article
    return parse_markdown(source)


# --- Тип материала: MaterialType::detect. ------------------------------------
MATERIAL_LABELS = {
    "deck": "Колода",
    "tier_list": "Тир-лист",
    "meta": "Мета-отчёт",
    "patch": "Патч",
    "mulligan": "Муллиган",
    "matchups": "Матчапы",
    "news": "Новость",
    "guide": "Гайд по архетипу",
    "other": "Материал",
}
SECTION_PATTERNS = {
    "deck": ("Состав и код колоды", r"колод|дек|код|состав|сборк|список карт"),
    "mulligan": ("Муллиган", r"муллиган|мулиган|стартов"),
    "strategy": ("Стратегия", r"стратеги|как играть|план игры|тактик"),
    "matchups": ("Матчапы", r"матчап|против"),
    "replacements": ("Замены", r"замен|альтернатив|бюджет"),
    "tiers": ("Список колод или тиров", r"тир|список|лучшие колоды|топ"),
    "changes": ("Что изменилось", r"изменени|что нового|нерф|бафф"),
    "impact": ("Как это повлияет на мету", r"мет|влияни|что это значит"),
}
REQUIRED_SECTIONS = {
    "guide": ["deck", "mulligan", "strategy", "matchups", "replacements"],
    "meta": ["tiers", "changes"],
    "tier_list": ["tiers", "changes"],
    "patch": ["changes", "impact"],
}


def _starts_word(pattern: str, text: str) -> bool:
    return re.search(r"(?<![^\W_])(?:" + pattern + ")", text.lower()) is not None


def detect_material(title: str, categories: list[str], headings: list[tuple[int, str]], post_type: str) -> str:
    if post_type in ("hs_deck", "deck"):
        return "deck"
    haystack = " ".join([title, *categories]).lower()
    for kind, pattern in (
        ("tier_list", r"тир[\s–—-]*лист"),
        ("meta", r"мета[\s–—-]*отч[её]т|обзор меты"),
        ("patch", r"патч|обновлени|нерф|бафф"),
        ("mulligan", r"муллиган|мулиган"),
        ("matchups", r"матчап"),
    ):
        if _starts_word(pattern, haystack):
            return kind
    if any(re.search(r"(?<![^\W_])новости(?![^\W_])", category.lower()) for category in categories):
        return "news"
    if _starts_word(r"гайд|руководств|как играть", haystack):
        return "guide"
    small = [text for level, text in headings if level in (2, 3)]
    if any(_starts_word(SECTION_PATTERNS["mulligan"][1], text) for text in small) and any(
        _starts_word(SECTION_PATTERNS["matchups"][1], text) or _starts_word(SECTION_PATTERNS["strategy"][1], text)
        for text in small
    ):
        return "guide"
    return "other"


# --- Проверки. ---------------------------------------------------------------
VAGUE_ANCHORS = {
    "здесь", "тут", "сюда", "подробнее", "подробно", "детали", "читать", "читать далее",
    "читать дальше", "читать полностью", "далее", "дальше", "по ссылке", "ссылка", "ссылке",
    "ссылку", "ссылочка", "клик", "кликни", "кликните", "жми", "жмите", "нажми", "нажмите",
    "перейти", "перейдите", "перейти по ссылке", "смотреть", "смотрите", "here", "click",
    "click here", "read more", "more", "link",
}
_ALT_JUNK = re.compile(r"^(img|image|dsc|dscn|pxl|photo|screenshot|снимок экрана|скриншот|изображение)[\s_-]*\d", re.IGNORECASE)


def _file_stem(src: str) -> str:
    name = src.split("?")[0].rstrip("/").split("/")[-1]
    return name


def _same_name(alt: str, src: str) -> bool:
    def norm(value: str) -> str:
        return re.sub(r"[\s_-]+", " ", value.lower()).strip()

    name = _file_stem(src)
    base = name.rsplit(".", 1)[0] if "." in name else name
    return bool(alt.strip()) and norm(alt) in (norm(name), norm(base))


def _host(url: str) -> str:
    match = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#:]+)", url.strip(), re.IGNORECASE)
    return match.group(1).lower().removeprefix("www.") if match else ""


def run_checks(article: Article, seo: dict, *, post_title: str, categories: list[str], post_type: str, site: str, lexicon: Lexicon) -> dict:
    matcher = Matcher(lexicon)
    checks: list[dict] = []

    def add(check_id: str, status: str, message: str) -> None:
        checks.append({"id": check_id, "status": status, "message": message})

    keyword = str(seo.get("focus_keyword", "")).strip()
    title = str(seo.get("title", "")).strip()
    description = str(seo.get("description", "")).strip()
    slug = str(seo.get("slug", "")).strip().strip("/").split("/")[-1]
    answer = str(seo.get("answer", "")).strip()
    schema = str(seo.get("schema_type", ""))
    plain = article.plain
    words = word_count(plain)

    # Предлагаемые alt применяются к картинкам до проверки.
    proposed = {item.get("src", ""): item.get("alt", "") for item in seo.get("alts", []) if isinstance(item, dict)}
    for image in article.images:
        if image["src"] in proposed:
            image["alt"] = proposed[image["src"]]

    # Ключевое слово.
    if not keyword:
        add("keyword_set", "red", "Главный запрос не задан.")
    else:
        add("keyword_set", "green", f"Главный запрос: «{keyword}».")
        if matcher.contains(title, keyword):
            add("keyword_in_title", "green", "Ключ есть в заголовке.")
            position = matcher.position(title, keyword)
            if position <= 2:
                add("keyword_at_title_start", "green", "Ключ в первых трёх словах заголовка.")
            else:
                add("keyword_at_title_start", "orange", f"Ключ начинается со слова {position + 1}; перенесите его в первые три слова.")
        else:
            add("keyword_in_title", "red", "Ключа нет в заголовке.")
        add(
            "keyword_in_description",
            "green" if matcher.contains(description, keyword) else "red",
            "Ключ есть в описании." if matcher.contains(description, keyword) else "Ключа нет в описании.",
        )
        if slug:
            in_slug = matcher.in_slug(slug, keyword)
            add("keyword_in_slug", "green" if in_slug else "red", "Ключ есть в адресе." if in_slug else f"Ключа нет в адресе; основы ключа латиницей: {', '.join(slugify(item) for item in matcher.keyword_stems(keyword))}.")
        if words > 0:
            first = article.first_paragraph() or ""
            ok = matcher.contains(first, keyword)
            add("keyword_in_first_paragraph", "green" if ok else "red", "Ключ есть в первом абзаце." if ok else "Ключа нет в первом абзаце: назовите тему в первых предложениях.")
        subheadings = [text for level, text in article.headings if 2 <= level <= 4]
        if subheadings:
            ok = any(matcher.contains(text, keyword) for text in subheadings)
            add("keyword_in_subheadings", "green" if ok else "orange", "Ключ есть в подзаголовке." if ok else "Ключа нет ни в одном подзаголовке H2–H4.")
        elif words >= 300:
            add("keyword_in_subheadings", "orange", "В тексте нет подзаголовков H2–H4.")
        if article.images:
            ok = any(matcher.contains(image.get("alt") or "", keyword) for image in article.images)
            add("keyword_in_image_alt", "green" if ok else "orange", "Ключ есть в alt картинки." if ok else "Ключа нет ни в одном alt: добавьте его к подходящей картинке.")
        if words >= 100:
            count = matcher.count(plain, keyword)
            density = count * matcher.length(keyword) / words * 100 if words else 0.0
            if count == 0 or density > DENSITY_RANGE[1]:
                status = "red"
            elif density < DENSITY_RANGE[0]:
                status = "orange"
            else:
                status = "green"
            add("keyword_density", status, f"Ключ встречается {count} раз, плотность {density:.1f} % (норма 0,5–2,5 %).")

    # Сниппет.
    width = title_width(title)
    if not title or width > TITLE_MAX_PX:
        add("title_width", "red", f"Заголовок {'пуст' if not title else f'шире выдачи: {width} px из {TITLE_MAX_PX}'}.")
    elif width < TITLE_MIN_PX:
        add("title_width", "orange", f"Заголовок короткий: {width} px.")
    else:
        add("title_width", "green", f"Заголовок помещается: {width} px из {TITLE_MAX_PX} (оценка без браузера).")
    if "%" in title or "%" in description:
        add("template_vars", "orange", "В заголовке или описании есть %переменные%: проверка не раскрывает их, сверьте итог в плагине.")
    length = len(description)
    if not description:
        add("description_length", "red", "Описание пустое.")
    elif DESCRIPTION_RANGE[0] <= length <= DESCRIPTION_RANGE[1]:
        add("description_length", "green", f"Длина описания {length} символов.")
    else:
        add("description_length", "orange", f"Описание {length} символов, нужно {DESCRIPTION_RANGE[0]}–{DESCRIPTION_RANGE[1]}.")
    if slug:
        slug_words = len([part for part in slug.split("-") if part])
        if len(slug.encode("utf-8")) <= SLUG_MAX_BYTES and slug_words <= SLUG_MAX_WORDS:
            add("slug_length", "green", f"Адрес короткий: {slug_words} слов.")
        else:
            add("slug_length", "orange", f"Адрес длинный: {slug_words} слов, {len(slug.encode('utf-8'))} байт (норма до 7 слов и 75 байт). У опубликованной записи слаг не меняйте.")

    # Текст.
    if post_type == "post":
        if words >= MIN_WORDS:
            add("content_length", "green", f"Объём текста: {words} слов.")
        else:
            add("content_length", "orange" if words >= MIN_WORDS / 2 else "red", f"Текст короткий: {words} слов из {MIN_WORDS}.")
    if words >= 150:
        internal = [link for link in article.links if link["href"].startswith("/") or (_host(link["href"]) and _host(link["href"]) == site)]
        external = [link for link in article.links if _host(link["href"]) and _host(link["href"]) != site]
        add("internal_links", "green" if internal else "red", f"Внутренних ссылок: {len(internal)}.")
        add("external_links", "green" if external else "orange", f"Ссылок на источники: {len(external)}.")
        add("images", "green" if article.images else "orange", f"Картинок: {len(article.images)}.")
    h1 = [text for level, text in article.headings if level == 1]
    add("single_h1", "red" if h1 else "green", "В тексте есть H1: заголовок записи уже H1." if h1 else "Лишних H1 нет.")

    if schema not in SCHEMA_TYPES:
        add("schema_type", "red", f"Неизвестный тип «{schema}»: допустимы {', '.join(repr(key) for key in SCHEMA_TYPES)}.")
    if schema != "none" and post_type not in ("hs_deck", "deck"):
        count = answer_words(answer)
        if not answer:
            add("answer", "red", "Краткого ответа нет.")
        elif ANSWER_RANGE[0] <= count <= ANSWER_RANGE[1]:
            add("answer", "green", f"Краткий ответ: {count} слов.")
        else:
            add("answer", "orange", f"Краткий ответ: {count} слов, нужно {ANSWER_RANGE[0]}–{ANSWER_RANGE[1]}.")

    content_images = [image for image in article.images if not image["decorative"]]
    bad = []
    for image in content_images:
        alt = image.get("alt")
        if alt is None or not alt.strip() or _same_name(alt, image["src"]) or _ALT_JUNK.search(alt.strip()):
            bad.append(_file_stem(image["src"]) or "(без адреса)")
    if content_images:
        add("image_alt", "red" if bad else "green", f"Картинок без нормального alt: {len(bad)}: {', '.join(bad)}." if bad else "У всех картинок есть alt.")

    vague = []
    for link in article.links:
        if link["href"].startswith("#"):
            continue
        text = re.sub(r"[^\w\s]", "", (link["text"] or "").lower()).strip()
        text = " ".join(text.split())
        if not text and link["images"]:
            if not any((image.get("alt") or "").strip() for image in link["images"]) and not link["aria"].strip():
                vague.append(f"картинка без alt → {link['href']}")
        elif text in VAGUE_ANCHORS or re.fullmatch(r"(нажмите|кликните|читайте|смотрите|жмите|переходите)\s+(здесь|тут|сюда|по ссылке)", text):
            vague.append(f"«{link['text']}» → {link['href']}")
        elif re.match(r"^(https?://|www\.)", (link["text"] or "").strip(), re.IGNORECASE):
            vague.append(f"голый адрес → {link['href']}")
    if vague:
        add("anchor_text", "orange", "Непонятный текст ссылок: " + "; ".join(vague) + ".")

    material = detect_material(post_title, categories, article.headings, post_type)
    add("material_type", "info", f"Тип материала: {MATERIAL_LABELS[material]} (по заголовку записи «{post_title}»).")
    if material in REQUIRED_SECTIONS:
        headings = [text for level, text in article.headings if 2 <= level <= 4]
        missing = [
            SECTION_PATTERNS[key][0]
            for key in REQUIRED_SECTIONS[material]
            if not any(_starts_word(SECTION_PATTERNS[key][1], text) for text in headings)
        ]
        add("material_sections", "orange" if missing else "green", ("Нет разделов: " + ", ".join(missing) + ".") if missing else "Все разделы на месте.")

    if words >= 300 and not article.lists:
        add("readability_lists", "orange", f"В тексте {words} слов и ни одного списка или таблицы.")
    if words >= 300 and not article.headings:
        add("readability_headings", "orange", "В тексте нет подзаголовков.")
    first = article.first_paragraph() if article.has_p else None
    if first and word_count(first) > 80:
        add("readability_first_paragraph", "orange", f"Первый абзац длинный: {word_count(first)} слов (до 80).")

    # Поля, которые плагин хранит без анализа.
    related = seo.get("related", [])
    if isinstance(related, str):
        related = [item.strip() for item in related.split(",")]
    related = [str(item).strip() for item in related if str(item).strip()]
    unique: list[str] = []
    for item in related:
        if item.lower() not in [value.lower() for value in unique]:
            unique.append(item)
    if len(unique) > MAX_RELATED:
        add("related", "red", f"Похожих запросов {len(unique)}: плагин сохранит только первые {MAX_RELATED}.")
    elif keyword and any(matcher.contains(item, keyword) and matcher.contains(keyword, item) for item in unique):
        add("related", "orange", "Похожий запрос повторяет главный.")
    elif unique:
        add("related", "green", f"Похожих запросов: {len(unique)}.")

    faq = seo.get("faq", [])
    if faq:
        problems = []
        complete = [item for item in faq if str(item.get("question", "")).strip() and str(item.get("answer", "")).strip()]
        if len(faq) > MAX_FAQ:
            problems.append(f"вопросов {len(faq)}, максимум {MAX_FAQ}")
        if len(complete) != len(faq):
            problems.append("есть строка без вопроса или ответа — на сайт она не выйдет")
        questions = [" ".join(str(item.get("question", "")).lower().split()) for item in faq]
        if len(set(questions)) != len(questions):
            problems.append("вопросы повторяются")
        for number, item in enumerate(faq, 1):
            question, reply = str(item.get("question", "")), str(item.get("answer", ""))
            if question.strip() and not question.strip().endswith("?"):
                problems.append(f"вопрос {number} без знака вопроса")
            if "[" in question:
                problems.append(f"в вопросе {number} шорткод: пишите карты в вопросе текстом")
            opened = re.findall(r"\[(hs_card|hs_bg)\b", reply)
            closed = re.findall(r"\[/(hs_card|hs_bg)\]", reply)
            if len(opened) != len(closed):
                problems.append(f"в ответе {number} незакрытый шорткод карты")
            for card_id in re.findall(r'\[(?:hs_card|hs_bg)\s+id="([^"]*)"', reply):
                if not re.fullmatch(r"[A-Za-z0-9_]+", card_id):
                    problems.append(f"в ответе {number} подозрительный id «{card_id}»")
            sentences = [part for part in re.split(r"(?<=[.!?…])\s+", reduce_shortcodes(reply).strip()) if WORD.search(part)]
            if len(sentences) > 3:
                problems.append(f"ответ {number} длиннее трёх предложений")
        add("faq", "orange" if problems else "green", ("FAQ: " + "; ".join(problems) + ".") if problems else f"FAQ: {len(complete)} вопросов.")

    earned = sum(WEIGHTS[item["id"]] * {"green": 1, "orange": 0.5}.get(item["status"], 0) for item in checks if item["id"] in WEIGHTS)
    maximum = sum(WEIGHTS[item["id"]] for item in checks if item["id"] in WEIGHTS)
    return {
        "checks": checks,
        "score_estimate": round(earned / maximum * 100) if maximum else None,
        "material": material,
        "words": words,
        "not_checked": [
            "redirected_links: ссылки с редиректом (нужна сеть)",
            "keyword_unique: ключ на других страницах сайта",
            "author_profile и social_image: данные WordPress",
        ],
    }


def render_card(seo: dict, report: dict) -> str:
    related = seo.get("related", [])
    if isinstance(related, list):
        related = ", ".join(str(item) for item in related)
    description = str(seo.get("description", ""))
    lines = [
        "## Вид в поиске",
        f"**Заголовок в поиске** ({title_width(str(seo.get('title', '')))} px из {TITLE_MAX_PX}):",
        str(seo.get("title", "")),
        "",
        f"**Описание в поиске** ({len(description)} символов):",
        description,
        "",
        f"**Главный запрос:** {seo.get('focus_keyword', '')}",
        "",
        f"**Похожие запросы:** {related}",
        "",
        "## Содержание",
        f"**Краткий ответ** ({answer_words(str(seo.get('answer', '')))} слов):",
        str(seo.get("answer", "")),
        "",
        "**Вопросы и ответы:**",
    ]
    for number, item in enumerate(seo.get("faq", []), 1):
        lines += [f"{number}. Вопрос: {item.get('question', '')}", f"   Ответ: {item.get('answer', '')}"]
    lines += ["", f"**Чем считать материал для поисковиков:** {SCHEMA_TYPES.get(str(seo.get('schema_type', '')), seo.get('schema_type', ''))}"]
    if seo.get("og_title") or seo.get("og_description"):
        lines += ["", "## Соцсети", f"**Заголовок:** {seo.get('og_title', '')}", f"**Описание:** {seo.get('og_description', '')}"]
    if seo.get("slug") or seo.get("alts"):
        lines += ["", "## Дополнительно и картинки"]
        if seo.get("slug"):
            lines.append(f"**Адрес:** {seo['slug']}")
        for item in seo.get("alts", []):
            lines.append(f"- {_file_stem(item.get('src', ''))}: alt «{item.get('alt', '')}»")
    fixes = [item for item in report["checks"] if item["status"] in ("red", "orange")]
    lines += ["", f"## Анализ (оценка по проверенным пунктам: {report['score_estimate']})"]
    for item in report["checks"]:
        if item["status"] == "info":
            lines.append(f"- {item['message']}")
    for item in fixes:
        mark = "🔴" if item["status"] == "red" else "🟠"
        lines.append(f"- {mark} {item['message']}")
    lines.append("- Не проверено: " + "; ".join(report["not_checked"]) + ".")
    return "\n".join(lines) + "\n"


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Проверка SEO-полей IndexPilot для статьи.")
    parser.add_argument("article", type=Path, nargs="?", help="Текст статьи: HTML из WordPress или Markdown.")
    parser.add_argument("--seo", type=Path, help="JSON с полями: title, description, focus_keyword, related, answer, faq, schema_type, slug, alts.")
    parser.add_argument("--post-title", default="", help="Заголовок записи (H1) для определения типа материала.")
    parser.add_argument("--category", action="append", default=[], help="Рубрика записи; можно несколько.")
    parser.add_argument("--post-type", default="post")
    parser.add_argument("--site", default="hs-manacost.ru", help="Домен для внутренних ссылок.")
    parser.add_argument("--synonyms", type=Path, help="JSON {канон: [синонимы]} — свои синонимы владельца из настроек плагина.")
    parser.add_argument("--card", action="store_true", help="Вывести карточку для копирования вместо JSON.")
    parser.add_argument("--slugify", metavar="TEXT", help="Только транслитерировать текст в слаг.")
    parser.add_argument("--title-width", metavar="TEXT", help="Только оценить ширину заголовка в px.")
    args = parser.parse_args()
    try:
        if args.slugify is not None:
            print(slugify(args.slugify))
            return 0
        if args.title_width is not None:
            print(title_width(args.title_width))
            return 0
        if args.article is None or args.seo is None:
            raise ValueError("нужны ARTICLE и --seo")
        source = args.article.read_bytes().decode("utf-8")
        seo = json.loads(args.seo.read_text(encoding="utf-8"))
        if not isinstance(seo, dict):
            raise TypeError("--seo должен быть JSON-объектом")
        if not isinstance(seo.get("faq", []), list) or not all(isinstance(item, dict) for item in seo.get("faq", [])):
            raise TypeError("faq — список объектов {question, answer}")
        extra = json.loads(args.synonyms.read_text(encoding="utf-8")) if args.synonyms else None
        article = parse_article(source)
        post_title = args.post_title or next((text for level, text in article.headings if level == 1), "") or str(seo.get("title", ""))
        report = run_checks(
            article,
            seo,
            post_title=post_title,
            categories=args.category,
            post_type=args.post_type,
            site=args.site.lower().removeprefix("www."),
            lexicon=Lexicon(extra),
        )
    except (OSError, UnicodeDecodeError, ValueError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.card:
        print(render_card(seo, report), end="")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if any(item["status"] == "red" for item in report["checks"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
