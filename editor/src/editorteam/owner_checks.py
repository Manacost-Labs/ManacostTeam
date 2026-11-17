"""Проверки по реальным отклонениям владельца, которые ловятся без модели.

Набор 2026-11-09 (статья об APM-механизмах, 15 отклонений) показал, что
`audit` проверял форму, а текст возвращали за другое. Здесь — то, что
закрывается детерминированно:

- слово-паразит: содержательное существительное встречается в статье во много
  раз чаще, чем у автора («стек» 19 раз на 639 слов, у автора — ни разу);
- повтор одного совета или факта в двух разделах (Портрет битбоксера описан
  и в плане игры, и в аксессуарах);
- слово, которое владелец запретил в требованиях (`forbidden_literals`
  author-context): любое вхождение, в любой форме, — ошибка.

Набор 2026-11-17 (разбор тир-листа 1-х дропов и правки редактора) — языковые
мелочи, которые редактор правил руками: смешение «вы» и «ты», точка и
английский Title Case в заголовке, «гайд на» вместо «гайд по», строчное
«в вольном» и короткое имя карты раньше полного. Все пять работают без
морфологии и внешних API (`voice_checks`).

Пересказ текста карты по предложению — в `card_paraphrase.retellings`.
Пороги сняты с корпусов автора; числа калибровки — в docs/OWNER_EVAL.md.
Плотность страховочных оговорок (R04) не отделяется от нормы автора и
оставлена рецензенту: там же объяснено почему.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable

from editorteam import publication_context

FREQ = Path(__file__).with_name("corpus_nouns_ru.json")

# Слово-паразит. Калибровка 2026-11-10: существительные вне словаря карт,
# корпус corpus-bg 45 + corpus-archive 297 гайдов (1,76 млн слов), каждый
# документ против корпуса без себя. Сигнал при count ≥ 8, ≥ 10 на 1000 слов
# и частоте в 100 раз выше корпусной: corpus-bg 2 из 45, corpus-archive
# 3 из 297, эталоны владельца 0 из 6; «стек» в версиях APM — 9 из 21.
OVERUSE_MIN_COUNT = 8
OVERUSE_MIN_PER_1K = 10.0
OVERUSE_MIN_RATIO = 100.0

# Повтор между разделами: пара предложений из разных разделов, у которых
# ≥ 3 общих смысловых лемм и Жаккар ≥ 0,5. Калибровка: эталоны 1 пара на
# 6 статей (и та — настоящий повтор состава), corpus-bg 3 пары в 1 из 45.
REPEAT_MIN_SHARED = 3
REPEAT_MIN_JACCARD = 0.5
REPEAT_MIN_LEMMAS = 4

_WORD = re.compile(r"[А-Яа-яЁёA-Za-z0-9]+(?:[-’'][А-Яа-яЁёA-Za-z0-9]+)*")
_RU_WORD = re.compile(r"[а-яё]+(?:-[а-яё]+)*", re.I)
_SENT = re.compile(r"(?<=[.!?…])\s+(?=[«\"(]?[А-ЯЁA-Z0-9])")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+·•]|\d+[.)])\s+")
_MARKUP = [
    (re.compile(r"\[/?hs_(?:bg|card)\b[^\]]*\]", re.I), ""),
    (re.compile(r"!\[[^\]]*\]\([^)]*\)|\[IMG[^\]]*\]"), ""),
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
    (re.compile(r"<[^>]+>"), ""),
    (re.compile(r"\*\*|__|`"), ""),
]
_KEEP = frozenset({"NOUN", "ADJF", "ADJS", "VERB", "INFN", "PRTF", "PRTS", "GRND", "NUMR", "ADVB", "COMP"})
_STOP = frozenset(
    "быть это весь свой который мочь такой этот тот ваш наш один так уже ещё еще "
    "очень можно нужно надо стать сам самый другой каждый первый просто также тоже "
    "лишь только даже потом теперь здесь там".split()
)


class _Lemmas:
    """Вероятнейший разбор pymorphy с кешем: (лемма, часть речи)."""

    def __init__(self, morph):
        self.morph = morph
        self._cache: dict[str, tuple[str, str]] = {}

    def __call__(self, word: str) -> tuple[str, str]:
        low = word.lower()
        if low not in self._cache:
            if low.isdigit():
                self._cache[low] = (low, "NUMB")
            else:
                p = self.morph.parse(low)[0]
                self._cache[low] = (p.normal_form, str(p.tag.POS))
        return self._cache[low]


def _strip(line: str) -> str:
    for pattern, repl in _MARKUP:
        line = pattern.sub(repl, line)
    return line


# ── Частоты автора ────────────────────────────────────────────────────────


def build_frequencies(
    documents: Iterable[str], game_texts: Iterable[str], morph, source: str = ""
) -> dict:
    """Снимок: существительные корпуса и словарь игры (названия и тексты карт).

    Словарь игры не бывает словом-паразитом: «звукорегулятор» в статье о
    звукорегуляторах — тема, а не привычка автора.
    """
    lemma = _Lemmas(morph)
    words = 0
    nouns: Counter = Counter()
    for text in documents:
        tokens = _RU_WORD.findall(_strip(text))
        words += len(tokens)
        nouns.update(lw for lw, pos in map(lemma, tokens) if pos == "NOUN")
    game = set()
    for text in game_texts:
        game.update(lw for lw, pos in map(lemma, _RU_WORD.findall(text)) if pos == "NOUN")
    return {
        "_источник": source,
        "words": words,
        "nouns": dict(sorted(nouns.items())),
        "game": sorted(game),
    }


def load_frequencies(path: Path = FREQ) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"нет снимка частот {path}; обновить: editor-team owner-eval --update-frequencies"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def overused_words(text: str, freq: dict, morph, prose: Callable[[str], str]) -> list[dict]:
    """Существительные, которых в тексте в разы больше, чем у автора."""
    lemma = _Lemmas(morph)
    lines = prose(text).split("\n")
    total = 0
    counts: Counter = Counter()
    forms: dict[str, Counter] = {}
    first: dict[str, int] = {}
    for n, line in enumerate(lines, 1):
        for token in _RU_WORD.findall(_strip(line)):
            total += 1
            lw, pos = lemma(token)
            if pos != "NOUN":
                continue
            counts[lw] += 1
            forms.setdefault(lw, Counter())[token.lower()] += 1
            first.setdefault(lw, n)
    if not total:
        return []
    game = set(freq.get("game", ()))
    corpus_words = max(int(freq.get("words", 0)), 1)
    nouns = freq.get("nouns", {})
    out = []
    for lw, count in counts.most_common():
        if count < OVERUSE_MIN_COUNT or lw in game or len(lw) < 3:
            continue
        per_1k = count / total * 1000
        corpus_per_1k = (nouns.get(lw, 0) + 1) / corpus_words * 1000
        ratio = per_1k / corpus_per_1k
        if per_1k < OVERUSE_MIN_PER_1K or ratio < OVERUSE_MIN_RATIO:
            continue
        out.append(
            {
                "lemma": lw,
                "count": count,
                "words": total,
                "per_1k": round(per_1k, 1),
                "corpus_count": nouns.get(lw, 0),
                "corpus_words": corpus_words,
                "ratio": round(ratio),
                "forms": [f for f, _ in forms[lw].most_common(4)],
                "line": first[lw],
            }
        )
    return out


# ── Повтор между разделами ────────────────────────────────────────────────


def _sentences(text: str, lemma: _Lemmas) -> list[tuple[int, int, str, frozenset]]:
    """(раздел, строка, предложение, смысловые леммы) прозы, разделы по заголовкам."""
    out = []
    section = 0
    for n, line in enumerate(text.split("\n"), 1):
        if _HEADING.match(line):
            section += 1
            continue
        clean = _LIST_ITEM.sub("", _strip(line)).strip()
        if not clean or clean.startswith((">", "|")):
            continue
        for chunk in _SENT.split(clean):
            keep = frozenset(
                lw
                for lw, pos in map(lemma, _WORD.findall(chunk))
                if (pos in _KEEP or pos == "NUMB") and lw not in _STOP and len(lw) >= 2
            )
            if len(keep) >= REPEAT_MIN_LEMMAS:
                out.append((section, n, chunk.strip(), keep))
    return out


def section_repeats(text: str, morph, prose: Callable[[str], str] | None = None) -> list[dict]:
    """Пары предложений из разных разделов, которые говорят одно и то же.

    `prose` должен сохранять заголовки: по ним делятся разделы. Код, цитаты
    и таблицы маскируются им же.
    """
    lemma = _Lemmas(morph)
    units = _sentences(prose(text) if prose else text, lemma)
    out = []
    for i, a in enumerate(units):
        for b in units[i + 1 :]:
            if a[0] == b[0]:
                continue
            shared = a[3] & b[3]
            if len(shared) < REPEAT_MIN_SHARED:
                continue
            jaccard = len(shared) / len(a[3] | b[3])
            if jaccard < REPEAT_MIN_JACCARD:
                continue
            out.append(
                {
                    "line": b[1],
                    "first_line": a[1],
                    "quote": b[2],
                    "first_quote": a[2],
                    "shared": sorted(shared),
                    "jaccard": round(jaccard, 2),
                }
            )
    return out


# ── Однообразные начала абзацев ───────────────────────────────────────────

# В большом гайде по колоде эталона 13 абзацев подряд открывались «Карта — …»,
# часть из них пустые («ключевое заклинание, без него колода не существует»).
# Сигнал — серия абзацев одного раздела с одной схемой начала:
#   title: «Короткое название — …», допускается один посторонний абзац подряд;
#   word:  одно и то же первое слово («Если…», «Это…»), строго подряд.
# Калибровка 2026-11-10 (corpus-archive 297, corpus-bg 45, эталоны владельца 6,
# принятая версия, гайд-эталон по колоде) — в editor/docs/OWNER_EVAL.md.
OPENING_MIN_TITLES = 10
OPENING_MAX_GAP = 1
# «Карта — роль и условие» — собственная форма автора: серия сама по себе
# срабатывала на 172 из 297 гайдов архива. Сигнал нужен там, где в серии есть
# пустые записи в одну короткую фразу («ключевая карта, без неё никак»):
# не меньше двух абзацев до 14 слов. Так: архив 47 из 297, corpus-bg 3 из 45,
# гайд-эталон по колоде срабатывает (записи в 11 и 14 слов).
OPENING_SHORT_WORDS = 14
OPENING_MIN_SHORT = 2
OPENING_MIN_SAME_WORD = 6
_OPEN_TITLE_WORDS = 4
_OPEN_DASH = re.compile(r"[—–]|\s-\s")
_OPEN_WORD = re.compile(r"[А-Яа-яЁёA-Za-z0-9]+(?:[-’'][А-Яа-яЁёA-Za-z0-9]+)*")


def _opening(paragraph: str) -> tuple[str, str] | None:
    """(схема, ключ) начала абзаца или None. Схема: «title» либо «word»."""
    head = paragraph.lstrip("«\"“ ")
    if not head or not (head[0].isupper() or head[0].isdigit()):
        return None
    dash = _OPEN_DASH.search(head[:80])
    if dash:
        title = head[: dash.start()].strip()
        words = _OPEN_WORD.findall(title)
        if title and 1 <= len(words) <= _OPEN_TITLE_WORDS and not re.search(r"[.!?:;]", title):
            return "title", "—"
    first = _OPEN_WORD.match(head)
    if first and len(first[0]) >= 2:
        return "word", first[0].lower().replace("ё", "е")
    return None


def _paragraphs(text: str) -> list[tuple[int, str]]:
    """(строка, первая строка абзаца): блоки между пустыми строками."""
    out, start, buffer = [], 0, []
    for n, line in enumerate(text.split("\n") + [""], 1):
        if line.strip():
            if not buffer:
                start = n
            buffer.append(line)
        elif buffer:
            out.append((start, buffer[0]))
            buffer = []
    return out


def paragraph_openings(text: str) -> list[dict]:
    """Серии однообразных начал в пределах раздела.

    Заголовок, список, таблица, цитата и замаскированный код обрывают серию.
    Нужен текст после маскировки с сохранёнными заголовками. Морфология не
    нужна, поэтому проверка работает и в минимальном runtime.
    """
    out: list[dict] = []
    titles: list[tuple[int, str, int]] = []  # (строка, начало, слов в абзаце)
    words: list[tuple[int, str, str]] = []  # (строка, слово, начало)
    gap = 0

    def close_titles() -> None:
        short = [(n, q) for n, q, size in titles if size <= OPENING_SHORT_WORDS]
        if len(titles) >= OPENING_MIN_TITLES and len(short) >= OPENING_MIN_SHORT:
            out.append(
                {
                    "line": titles[0][0],
                    "last_line": titles[-1][0],
                    "count": len(titles),
                    "short": len(short),
                    "scheme": "title",
                    "key": "название — …",
                    "quotes": [q for _, q in short[:3]],
                }
            )
        titles.clear()

    def close_words() -> None:
        if len(words) >= OPENING_MIN_SAME_WORD:
            out.append(
                {
                    "line": words[0][0],
                    "last_line": words[-1][0],
                    "count": len(words),
                    "scheme": "word",
                    "key": words[0][1],
                    "quotes": [q for _, _, q in words[:3]],
                }
            )
        words.clear()

    for n, block in _paragraphs(text):
        if _HEADING.match(block) or _LIST_ITEM.match(block) or block.lstrip().startswith((">", "|")):
            close_titles()
            close_words()
            gap = 0
            continue
        clean = _strip(block).strip()
        opening = _opening(clean) if len(clean) >= 20 else None
        quote = clean[:70]
        if opening and opening[0] == "title":
            titles.append((n, quote, len(clean.split())))
            gap = 0
        elif titles:
            gap += 1
            if gap > OPENING_MAX_GAP:
                close_titles()
                gap = 0
        if opening and opening[0] == "word":
            if words and words[-1][1] != opening[1]:
                close_words()
            words.append((n, opening[1], quote))
        else:
            close_words()
    close_titles()
    close_words()
    return out


# ── Запрещённые владельцем слова ──────────────────────────────────────────


def forbidden_literals(context: dict, text: str) -> list[dict]:
    """Каждое запрещённое слово с первой строкой, где оно встретилось.

    Решение о нарушении принимает `publication_context.literal_errors` (та же
    проверка, что в publication run); здесь добавлены строка и счётчик.
    """
    errors = publication_context.literal_errors(context, text)
    if not errors:
        return []
    out = []
    lines = [_strip(line) for line in text.split("\n")]
    for row in context.get("requirements", []):
        for term in row.get("forbidden_literals", []):
            pattern = publication_context.literal_pattern(term)
            hits = [(n, len(pattern.findall(line))) for n, line in enumerate(lines, 1)]
            hits = [(n, k) for n, k in hits if k]
            message = f"requirement {row['id']}: forbidden literal {term!r}"
            if message not in errors:
                continue
            out.append(
                {
                    "requirement": row["id"],
                    "instruction": row.get("instruction", ""),
                    "term": term,
                    "count": sum(k for _, k in hits) or 1,
                    "line": hits[0][0] if hits else None,
                }
            )
    return out


# ── Язык автора: обращение, заголовки, предлоги, имена карт ──────────────
#
# Замечания редактора к статьям 2026-11: «вы» и «ты» в одном тексте, точка
# в конце заголовка, «Лучшие Тир-1 Существа» английским Title Case, «гайд на
# Мурлоков» вместо «гайд по», «в вольном» строчными, «Геомант» раньше
# «Иглошкур-геоманта». Цитаты, код, шорткоды карт и жирные названия
# маскируются: «Лови яблочко» — имя карты, а не обращение к читателю.

_CYR = "А-Яа-яЁё"
SOFT_HYPHEN = chr(0xAD)
_QUOTE = re.compile(r"«[^«»\n]*»|„[^„“\n]*“|\"[^\"\n]*\"|“[^“”\n]*”")
_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
_URL = re.compile(r"https?://\S+")
_CARD_SHORTCODE = re.compile(r"\[(hs_bg|hs_card)\b[^\]]*\].*?\[/\1\]", re.I | re.S)
_SHORTCODE_ID = re.compile(
    r"\[(hs_bg|hs_card)\b[^\]]*?\bid=\"([^\"]+)\"[^\]]*\](.*?)\[/\1\]", re.I | re.S
)
_SHORTCODE_TAG = re.compile(r"\[/?(?:hs_bg|hs_card)\b[^\]]*\]", re.I)
_BOLD = re.compile(r"\*\*([^*\n]{1,120})\*\*")
_BLOCKQUOTE = re.compile(r"^\s*>.*$", re.M)
_FRONT = re.compile(r"\A---\n.*?\n---\n", re.S)
_HEADING_LINE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")


def _blank(text: str, pattern: re.Pattern[str]) -> str:
    """Заменить совпадения пробелами той же длины: строки и смещения на месте."""
    return pattern.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _masked_voice(text: str) -> str:
    """Текст без фронт-маттера, кода, ссылок, цитат, шорткодов и жирных названий."""
    text = _blank(text, _FRONT)
    for pattern in (_CODE, _URL, _BLOCKQUOTE, _CARD_SHORTCODE, _BOLD, _QUOTE):
        text = _blank(text, pattern)
    return text


def _fold(word: str) -> str:
    return word.lower().replace("ё", "е")


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _hit(code: str, severity: str, category: str, message: str, line: int,
         evidence: str, suggestion: str, **meta) -> dict:
    return {
        "id": code,
        "severity": severity,
        "category": category,
        "message": message,
        "line": line,
        "evidence": evidence,
        "suggestion": suggestion,
        "meta": meta,
    }


# ── «вы» и «ты» в одном тексте ────────────────────────────────────────────

_VY = re.compile(
    rf"(?<![{_CYR}-])(?:вы|вас|вам|вами|ваш|ваша|ваше|ваши|вашего|вашей|вашему|"
    rf"вашим|вашими|ваших|вашу)(?![{_CYR}-])",
    re.I,
)
_TY = re.compile(
    rf"(?<![{_CYR}-])(?:ты|тебя|тебе|тобой|тобою|твой|твоя|твоё|твое|твои|твоего|"
    rf"твоей|твоему|твоим|твоими|твоих|твою)(?![{_CYR}-])",
    re.I,
)
# Риторическое обращение к карте, а не к читателю: «Что с тобой стало,
# Разношерстная фаланга?» — после «ты» в том же вопросе идёт имя через запятую.
_VOCATIVE_TAIL = re.compile(rf"[^.!?\n]*?,\s+[А-ЯЁ][{_CYR}-]*[^.!?\n]*[?!]")


def pronoun_mix(text: str) -> list[dict]:
    """Одновременно «вы» и «ты» вне цитат и названий карт: одна находка на текст.

    Указывает первое вхождение редкой формы — её и надо привести к основной.
    """
    masked = _masked_voice(text)
    vy = list(_VY.finditer(masked))
    ty = [m for m in _TY.finditer(masked) if not _VOCATIVE_TAIL.match(masked, m.end())]
    if not vy or not ty:
        return []
    minor, major = (ty, "вы") if len(ty) <= len(vy) else (vy, "ты")
    first = minor[0]
    return [
        _hit(
            "owner.pronoun_mix", "error", "voice",
            f"смешаны обращения: «вы» {len(vy)} раз, «ты» {len(ty)} раз",
            _line_of(text, first.start()), text[first.start():first.end()],
            f"одно обращение на весь текст: привести к «{major}»",
            vy=len(vy), ty=len(ty),
        )
    ]


# ── Заголовки ─────────────────────────────────────────────────────────────

# Заголовок длиннее 68 знаков обрезается в выдаче и на узком экране.
HEADING_MAX_CHARS = 68
# Title Case: не меньше трёх слов с заглавной после первого, и они — большинство.
TITLE_CASE_MIN_WORDS = 3
TITLE_CASE_MIN_SHARE = 0.6
# Слова с заглавной по норме: классы, режимы, ранги, типы существ.
_CLASS_STEMS = (
    "маг", "жрец", "воин", "паладин", "охотник", "друид", "разбойник", "шаман",
    "чернокнижник", "рыцар", "дк", "онд",
)
_PROPER_STEMS = _CLASS_STEMS + (
    "демон", "поля", "поле", "сражени", "вольн", "стандарт", "арен", "потасовк",
    "дуэл", "наемник", "легенд", "алмаз", "платин", "золот", "серебр", "бронз",
    "свинобраз", "дракон", "пират", "мурлок", "звер", "элементал", "нежит",
    "механизм", "наг", "аберрац", "манакост", "азерот", "альянс", "орд",
)
_HEADING_WORD = re.compile(rf"[{_CYR}A-Za-z0-9]+(?:[-’'][{_CYR}A-Za-z0-9]+)*")
_LATIN = re.compile(r"[A-Za-z]")
_NAME_WORD = re.compile(rf"[{_CYR}]+(?:-[{_CYR}]+)*")
# Имена собственные внутри названий карт («Южных Морей», «Осколок Солнца»):
# в заголовке без шорткода они с заглавной по локализации. Ключ — первые
# пять букв: хвост названия почти не склоняется («Музыканта Южных Морей»).
_PROPER_KEY = 5


@lru_cache(maxsize=1)
def _snapshot_names() -> tuple[str, ...]:
    """Названия карт из снимка HearthstoneJSON; без снимка — пусто, проверки не падают."""
    from editorteam import card_paraphrase

    try:
        names = set(card_paraphrase.load_texts())
        names |= {row["n"] for row in card_paraphrase.load_bg().values()}
    except (OSError, ValueError, KeyError):
        return ()
    return tuple(sorted(names))


@lru_cache(maxsize=1)
def _card_proper_words() -> frozenset[str]:
    """Ключи слов с заглавной не в начале названий карт."""
    out = set()
    for name in _snapshot_names():
        for word in _NAME_WORD.findall(name)[1:]:
            if word[:1].isupper():
                out.add(_fold(word)[:_PROPER_KEY])
    return frozenset(out)


@lru_cache(maxsize=1)
def _known_card_names() -> frozenset[str]:
    return frozenset(" ".join(_fold(name).split()) for name in _snapshot_names())


def _heading_plain(raw: str) -> tuple[str, str]:
    """(текст заголовка без разметки, он же без названий карт)."""
    without_cards = _BOLD.sub(" ", _CARD_SHORTCODE.sub(" ", raw))
    plain = _SHORTCODE_TAG.sub("", raw)
    for pattern, repl in _MARKUP:
        plain = pattern.sub(repl, plain)
        without_cards = pattern.sub(repl, without_cards)
    return " ".join(plain.split()), " ".join(without_cards.split())


def _title_case(words: list[str]) -> tuple[list[str], int]:
    """(слова с заглавной без причины, сколько слов после первого проверено).

    Первое слово — первое из букв: номер пункта («5.») не считается. Латиница
    (ники, команды), аббревиатуры и числа не проверяются. Название колоды
    перед классом пишется с заглавной по норме: «Элем Биг Спелл Друид».
    """
    words = [w for w in words if not w[:1].isdigit()]
    tail = [w for w in words[1:] if not w.isupper() and not _LATIN.search(w)]
    archetype: set[int] = set()
    for i, word in enumerate(tail):
        if any(_fold(word).startswith(stem) for stem in _CLASS_STEMS):
            k = i - 1
            while k >= max(0, i - 3) and tail[k][:1].isupper():
                archetype.add(k)
                k -= 1
    proper = _card_proper_words()
    out = []
    for i, word in enumerate(tail):
        low = _fold(word)
        if i in archetype or low.startswith(_PROPER_STEMS) or low[:_PROPER_KEY] in proper:
            continue
        if word[:1].isupper():
            out.append(word)
    return out, len(tail)


def heading_issues(text: str) -> list[dict]:
    """Точка в конце, английский Title Case, длина и мягкие переносы в заголовках.

    Названия карт (шорткоды и жирное) в подсчёт Title Case не входят: «Музыкант
    Южных Морей» пишется так по локализации.
    """
    out: list[dict] = []
    body = _blank(text, _FRONT)
    fenced = False
    for n, line in enumerate(body.split("\n"), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        m = _HEADING_LINE.match(line)
        if fenced or not m:
            continue
        raw = m.group(2)
        plain, prose = _heading_plain(raw)
        visible = plain.replace(SOFT_HYPHEN, "")
        if not visible:
            continue
        if visible.endswith(".") and not visible.endswith(".."):
            out.append(_hit(
                "owner.heading_style", "error", "heading", "точка в конце заголовка",
                n, visible, "убрать точку: заголовок не предложение", issue="trailing_dot",
            ))
        caps, checked = _title_case(_HEADING_WORD.findall(prose.replace(SOFT_HYPHEN, "")))
        if len(caps) >= TITLE_CASE_MIN_WORDS and len(caps) >= TITLE_CASE_MIN_SHARE * checked:
            out.append(_hit(
                "owner.heading_style", "error", "heading",
                f"английский Title Case в русском заголовке: {', '.join(caps[:4])}",
                n, visible, "с заглавной — только первое слово и имена собственные",
                issue="title_case", words=caps,
            ))
        if SOFT_HYPHEN in raw:
            out.append(_hit(
                "owner.heading_style", "review", "heading", "мягкий перенос в заголовке",
                n, visible, "убрать мягкие переносы", issue="soft_hyphen",
            ))
        if len(visible) > HEADING_MAX_CHARS:
            out.append(_hit(
                "owner.heading_style", "review", "heading",
                f"заголовок {len(visible)} знаков: длиннее {HEADING_MAX_CHARS} обрезается на мобильном",
                n, visible, "сократить до главного: предмет и режим",
                issue="too_long", chars=len(visible),
            ))
    return out


# ── «гайд на» вместо «гайд по» ────────────────────────────────────────────

# «гайд на сайте», «гайд на русском», «гайд на неделе» — место, язык, время.
_GUIDE_NA = re.compile(
    rf"(?<![{_CYR}])гайд(?:а|у|ом|е|ы|ов|ам|ами|ах)?\s+на\s+"
    r"(?!(?:сайт|канал|ютуб|youtube|страниц|портал|форум|реддит|reddit|русск|английск|"
    r"язык|манакост|недел|сегодн|завтр|днях|выходн|тем[уеы]?\b|момент|\d))"
    rf"[{_CYR}A-Za-z][{_CYR}A-Za-z'’-]*",
    re.I,
)


def guide_preposition(text: str) -> list[dict]:
    """«Гайд на Мурлока» — калька поисковых запросов; в тексте пишем «гайд по»."""
    masked = _masked_voice(text)
    out = []
    for m in _GUIDE_NA.finditer(masked):
        out.append(_hit(
            "owner.guide_preposition", "error", "word-choice",
            "«гайд на …» вместо «гайд по …»",
            _line_of(text, m.start()), " ".join(text[m.start():m.end()].split()),
            "«гайд по …» (по кому/чему); «гайд на» — только в поисковых ключах SEO",
        ))
    return out


# ── «в вольном» строчными ────────────────────────────────────────────────

# Название режима — с заглавной: «в Вольном», «мета Вольного». «В вольном
# переводе», «в вольном порядке» — не режим.
_WILD = re.compile(
    rf"(?<![{_CYR}])(?:[Вв]о?|[Дд]ля|[Ии]з|[Нн]а|[Пп]о|[Пп]од|[Мм]ет(?:а|е|у|ы|ой))\s+"
    rf"(вольн(?:ом|ого|ому|ый|ым|ые|ых))(?![{_CYR}])"
    r"(?!\s+(?:порядк|перевод|стил|пересказ|дух|интерпретац|изложени|формулиров|обращени))"
)


def wild_mode_case(text: str) -> list[dict]:
    """Режим «Вольный» строчными: «в вольном», «мета вольного», «для вольного»."""
    masked = _masked_voice(text)
    out = []
    for m in _WILD.finditer(masked):
        word = m.group(1)
        out.append(_hit(
            "owner.wild_capitalization", "review", "spelling",
            f"режим строчными: «{word}»",
            _line_of(text, m.start()), " ".join(text[m.start():m.end()].split()),
            f"«{word[:1].upper()}{word[1:]}» — название режима с заглавной",
        ))
    return out


# ── Короткое имя карты раньше полного ────────────────────────────────────

# Официальные имена — из шорткодов (полная форма для ID) и жирных названий
# карт в начале абзаца или пункта. Короткое имя — отдельное слово
# многословного имени (≥ 5 букв), кроме прилагательных и типов существ:
# «Надзиратель» из «Подозрительного надзирателя», «Геомант» из
# «Иглошкур-геоманта». Морфология не нужна: сравнение по основе.
ALIAS_MIN_LETTERS = 5
_ADJ_END = re.compile(r"(?:ый|ий|ой|ая|яя|ое|ее|ые|ие|ых|их|ого|его|ую|юю|ым|им)(?:ся)?$")
_TYPE_STEM = re.compile(
    r"^(?:свинобраз|квилбор|дракон|пират|мурлок|звер(?!инц)|элементал|нежит|механизм|"
    r"демон|наг(?:а|и|ов|ам|ами|ах)?$|аберрац)"
)
_OPENER_BOLD = re.compile(r"^\s*(?:[-*+]\s+|\d{1,3}[.)]\s+)?\*\*([^*\n]{3,120})\*\*")


def _alias_stem(word: str) -> str:
    """Основа для сравнения форм: «надзиратель» → «надзирател», «стрелок» → «стрел»."""
    low = _fold(word)
    if len(low) <= ALIAS_MIN_LETTERS:
        return low
    if re.search(r"(?:ок|ек)$", low):
        return low[:-2]
    return low[: max(ALIAS_MIN_LETTERS, len(low) - 2)]


def _word_stem(word: str) -> str:
    """Основа слова полного имени: окончание падежа отрезается с запасом.

    В полном имени слова идут подряд, поэтому короткая основа не даёт ложных
    совпадений, а «Пузырьковым стрелком» и «Пузырьковый стрелок» сходятся.
    """
    low = _fold(word)
    return low if len(low) <= 3 else low[: max(3, len(low) - 3)]


def _letter_runs(name: str) -> int:
    """Слова имени вместе с частями через дефис: «Иглошкур-геомант» — два."""
    return len(re.findall(f"[{_CYR}]+", name))


def _name_regex(name: str) -> re.Pattern[str]:
    """Полное имя в любом падеже: основа каждого слова плюс окончание."""
    parts = []
    for word in _NAME_WORD.findall(name):
        stems = [
            re.escape(_word_stem(piece)).replace("е", "[её]") + f"[{_CYR}]*"
            for piece in word.split("-")
        ]
        parts.append(r"\s*-\s*".join(stems))
    return re.compile(f"(?<![{_CYR}])" + r"\s+".join(parts) + f"(?![{_CYR}])", re.I)


def _head_words(name: str) -> list[str]:
    """Слова имени, которыми карту зовут коротко (≥ 5 букв).

    Это главное существительное — первое слово после прилагательных
    («Надзиратель», «Музыкант»; у составного — и его части: «Геомант») — и
    имена собственные с заглавной («Кривоклык»). Зависимое слово
    («преобразователя» в «Портрете преобразователя») коротким именем не бывает.
    """
    words = _NAME_WORD.findall(name)
    if _letter_runs(name) < 2:
        return []
    out = []
    head_seen = False
    for i, word in enumerate(words):
        adjective = "-" not in word and bool(_ADJ_END.search(_fold(word)))
        is_head = not head_seen and not adjective
        if is_head:
            head_seen = True
        if not (is_head or (i > 0 and word[:1].isupper())):
            continue
        pieces = word.split("-")
        candidates = [word, *pieces] if len(pieces) > 1 and len(words) > 1 else pieces
        for piece in candidates:
            low = _fold(piece)
            if len(low.replace("-", "")) < ALIAS_MIN_LETTERS or _TYPE_STEM.match(low):
                continue
            out.append(low)
    return out


def _official_names(text: str) -> tuple[dict[str, str], list[tuple[int, int, str]]]:
    """({ключ: официальное имя}, [(начало, конец, ключ) каждого шорткода]).

    Ключ — ID шорткода или само жирное имя. Имя ID — его форма с наибольшим
    числом слов («Выживший красный дракон», а не «Красный дракон»), из таких —
    самая короткая: обычно это именительный падеж.
    """
    names: dict[str, str] = {}
    surfaces: dict[str, list[str]] = {}
    spans: list[tuple[int, int, str]] = []
    for m in _SHORTCODE_ID.finditer(text):
        surface = " ".join(_SHORTCODE_TAG.sub("", m.group(3)).replace("*", "").split())
        if not surface:
            continue
        key = m.group(2)
        surfaces.setdefault(key, []).append(surface)
        spans.append((m.start(), m.end(), key))
    for key, forms in surfaces.items():
        best = min(forms, key=lambda s: (-_letter_runs(s), len(s)))
        if _letter_runs(best) >= 2:
            names[key] = best
    # жирное в начале абзаца или пункта — имя карты, только если оно есть в
    # снимке карт: «**Свинобразы через Свиногонщика**» — подпись сборки
    known = _known_card_names()
    for line in text.split("\n"):
        m = _OPENER_BOLD.match(line)
        if not m or "[" in m.group(1):
            continue
        name = " ".join(m.group(1).split()).strip(" .,:;—–-")
        if _letter_runs(name) >= 2 and " ".join(_fold(name).split()) in known:
            names.setdefault(name, name)
    return names, spans


def premature_card_alias(text: str) -> list[dict]:
    """Короткое имя карты раньше её первого полного названия в статье.

    Ищется двумя путями: шорткод того же ID с короткой формой
    («[hs_bg id=…]Надзирателя[/hs_bg]») и слово с заглавной вне шорткодов,
    совпадающее по основе с ключевым словом ровно одного имени. Одна находка
    на карту — первое раннее упоминание.
    """
    body = _blank(text, _FRONT)
    for pattern in (_CODE, _URL, _BLOCKQUOTE):
        body = _blank(body, pattern)
    # кавычки ищутся без тегов шорткодов: иначе `id="…"` читается как цитата
    plain = _blank(body, _SHORTCODE_TAG)
    quoted = [m.span() for m in _QUOTE.finditer(plain)]
    plain = _blank(plain, _QUOTE).replace("*", " ")
    names, spans = _official_names(body)
    spans = [s for s in spans if not any(a <= s[0] < b for a, b in quoted)]
    if not names:
        return []
    full = {key: [m.span() for m in _name_regex(name).finditer(plain)] for key, name in names.items()}
    short_codes: list[tuple[int, int, str, str]] = []
    for start, end, key in spans:
        if key not in names:
            continue
        surface = " ".join(_SHORTCODE_TAG.sub("", body[start:end]).split())
        # «День самоцветов» и «Дня самоцветов» — обе полные: слов столько же
        if _letter_runs(surface) >= _letter_runs(names[key]):
            full[key].append((start, end))
        elif not any(start <= a < end for a, _ in full[key]):
            short_codes.append((start, end, key, surface))
    first_full = {key: min((a for a, _ in found), default=None) for key, found in full.items()}
    covered = [span for found in full.values() for span in found]
    code_spans = [(a, b) for a, b, _ in spans]

    def inside(pos: int, ranges) -> bool:
        return any(a <= pos < b for a, b in ranges)

    early: dict[str, tuple[int, str]] = {}

    def note(key: str, pos: int, surface: str) -> None:
        first = first_full.get(key)
        if first is not None and pos < first and (key not in early or pos < early[key][0]):
            early[key] = (pos, surface)

    # 1. шорткод того же ID короткой формой
    for start, _, key, surface in short_codes:
        note(key, start, surface)
    # 2. слово с заглавной вне шорткодов и полных названий
    heads: dict[str, set[str]] = {}
    for key, name in names.items():
        for word in _head_words(name):
            heads.setdefault(_alias_stem(word), set()).add(key)
    for m in _NAME_WORD.finditer(plain):
        word = m.group(0)
        if not word[:1].isupper() or inside(m.start(), code_spans) or inside(m.start(), covered):
            continue
        low = _fold(word)
        if _TYPE_STEM.match(low):
            continue
        keys = {
            key
            for stem, owners in heads.items()
            if low.startswith(stem) and len(low) - len(stem) <= 4
            for key in owners
        }
        if len(keys) == 1:
            note(next(iter(keys)), m.start(), word)
    out = []
    for key, (pos, surface) in sorted(early.items(), key=lambda kv: kv[1][0]):
        name, full_line = names[key], _line_of(text, first_full[key])
        out.append(_hit(
            "owner.premature_card_alias", "review", "card-name",
            f"«{surface}» раньше полного названия «{name}» (стр.{full_line})",
            _line_of(text, pos), surface,
            "при первом упоминании — полное официальное название, дальше можно короче",
            card=name, first_full_line=full_line,
        ))
    return out


def voice_checks(text: str) -> list[dict]:
    """Все пять проверок языка автора одним списком, по строкам."""
    hits = (
        pronoun_mix(text)
        + heading_issues(text)
        + guide_preposition(text)
        + wild_mode_case(text)
        + premature_card_alias(text)
    )
    return sorted(hits, key=lambda h: (h["line"] or 0, h["id"]))
