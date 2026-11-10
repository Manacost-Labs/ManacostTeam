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

Пересказ текста карты по предложению — в `card_paraphrase.retellings`.
Пороги сняты с корпусов автора; числа калибровки — в docs/OWNER_EVAL.md.
Плотность страховочных оговорок (R04) не отделяется от нормы автора и
оставлена рецензенту: там же объяснено почему.
"""

from __future__ import annotations

import json
import re
from collections import Counter
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
