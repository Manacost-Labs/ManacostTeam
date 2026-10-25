"""Механический текст про карты: пересказ эффекта, пустое упоминание, плотность инсайта.

Правило против пересказа записано в `docs/PLAYER_EDITORIAL_STANDARD.md`; здесь
оно измеряется тремя числами:

1. ``paraphrase_rate`` — доля предложений с картой, которые повторяют её
   официальный текст и ничего не добавляют сверху;
2. ``bare_mention_rate`` — доля упоминаний, рядом с которыми нет ни когда
   играть, ни против кого, ни что ради неё отложить, ни чем заменить, ни
   типичной ошибки;
3. ``insight_density`` — доля предложений прозы со связкой
   «условие → решение → причина».

Названия с падежами распознаёт `cards.Index` скилла (его передаёт CLI, как
spell_hints получает morph); тексты карт — снимок HearthstoneJSON рядом с
модулем. Сравнение смысла лексическое, по леммам: эмбеддинг-модели в
обязательных зависимостях нет.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

TEXTS = Path(__file__).with_name("card_texts_ru.json")
SOURCE = "https://api.hearthstonejson.com/v1/latest/ruRU/cards.json"

# Пороги документа сняты `card-paraphrase --calibrate` с корпусов автора
# (corpus-archive 297 + corpus-bg 45 гайдов, 2026-10-25). Распределение:
#   paraphrase_rate    p50 0, p90 0, p95 0.006, p99 0.012, max 0.045
#   bare_mention_rate  p10 0.113, p50 0.207, p90 0.364, max 0.875
#   insight_density    p10 0.003, p50 0.016, p90 0.031 (у Полей сражений p50 0.006)
# Пересказ у автора почти не встречается, p90 равен нулю, поэтому порог —
# чуть выше худшего гайда автора. Остальные два — p90 и p10: хуже 90 %
# гайдов автора — сигнал редактору, а не приговор. Вне нормы на корпусе:
# пересказ 0, упоминания 32, инсайт 32 из 342.
PARAPHRASE_MAX = 0.05
BARE_MENTION_MAX = 0.37
INSIGHT_MIN = 0.003

# Предложение-пересказ: не меньше половины смысловых слов текста карты и не
# больше 40 % собственных слов автора. По корпусу: при доле своих слов до 0,34
# почти все находки — пересказ («Громоголов призывает две Искры 1/1 по обе
# стороны от себя»), в полосе 0,34–0,45 — примерно половина («в вашей колоде
# есть одно существо с 2 атаки» уже про колоду, а не про карту).
COVER_MIN = 0.5
NOVELTY_MAX = 0.4
MIN_OVERLAP = 2

# Глаголы-связки пересказа: «позволяет нанести», «даёт броню» — это обёртка
# эффекта, а не мысль автора.
WRAPPER = frozenset(
    "позволять давать мочь являться иметь обладать эффект свойство способность "
    "механика текст карта который тот также ещё просто весь это свой ваш наш "
    "ед единица".split()
)
# Слова архетипов с заглавной («Нечетный Паладин», «Квест Маг») — не карты.
ARCHETYPE_WORDS = frozenset(
    "чётный нечётный четный нечетный квест темпо мидрейндж big биг хайлендер рено токен".split()
)
_DROP_POS = frozenset({"PREP", "CONJ", "PRCL", "INTJ", "NPRO"})
_NUMBERS = {
    "один": "1",
    "два": "2",
    "три": "3",
    "четыре": "4",
    "пять": "5",
    "шесть": "6",
    "семь": "7",
    "восемь": "8",
    "девять": "9",
    "десять": "10",
}

# Маркеры теста упоминания: что делает строку советом, а не справкой.
# "when" — когда и как играть: сюда же решение читателю (императив, «стоит»).
CONTEXT = {
    "when": frozenset(
        "когда если пока рано ранний поздно поздний сразу потом затем после ход "
        "момент дождаться дожидаться ждать выждать муллиган стартовый лейт эндгейм "
        "стадия этап".split()
    ),
    "against": frozenset("против матчап матч-ап зеркало зеркальный противостоять".split()),
    "hold": frozenset(
        "отложить откладывать придержать придерживать держать удерживать сохранить "
        "сохранять приберечь беречь поберечь копить оставить оставлять ради "
        "экономить".split()
    ),
    "replace": frozenset(
        "заменить заменять замена вместо альтернатива альтернативный взамен аналог "
        "бюджетный заменитель".split()
    ),
    "mistake": frozenset(
        "ошибка ошибаться ошибочно зря нельзя опасно ловушка новичок спешить "
        "торопиться переоценивать недооценивать рисковать рискованно".split()
    ),
}
# Слова, которых нет в словаре pymorphy («матч-апах» остаётся «матч-апах»),
# и обороты: «Инженер-новичок, а не Маг крови Талнос» — выбор замены.
_SURFACE = {
    "when": re.compile(r"мул+игн?ан|лейтгейм|мидгейм|эндгейм", re.I),
    "against": re.compile(r"матч-?ап", re.I),
    "replace": re.compile(r"\bа\s+не\b", re.I),
}
_NEGATIVE_ADVICE = re.compile(
    r"\bне\s+(?:стоит|нужно|надо|следует|спеши|тороп|трат|разыгрыва|выставля|забыва)",
    re.I,
)

CONDITION = frozenset("если когда пока против матчап матч-ап случай зеркало".split())
DECISION = frozenset(
    "стоить нужно надо следовать смысл выгодно выгодный важно важный разумно "
    "предпочтительно рекомендовать приоритет нельзя можно должный лучше".split()
)
REASON = frozenset(
    "потому поскольку ведь иначе чтобы ради благодаря поэтому значит ибо "
    "следовательно зато из-за".split()
)
# Причина в начале следующего предложения: «…держите её. Иначе …»
REASON_LEADS = frozenset("иначе потому ведь поскольку зато поэтому".split())

_WORD = re.compile(r"[А-Яа-яЁёA-Za-z0-9]+(?:['’-][А-Яа-яЁёA-Za-z0-9]+)*")
_SENT = re.compile(r"(?<=[.!?…])\s+(?=[«\"(]?[А-ЯЁA-Z0-9])")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+·•]|\d+[.)])\s+")
_INLINE = [
    (re.compile(r"\[(hs_card|hs_bg)\b[^\]]*\](.*?)\[/\1\]", re.I), r"\2"),
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
    (re.compile(r"<[^>]+>"), ""),
    (re.compile(r"\*\*|__|(?<!\w)[*_](?=\S)|(?<=\S)[*_](?!\w)"), ""),
]


# ── Снимок текстов карт ────────────────────────────────────────────────────


def clean_text(raw: str) -> str:
    """Текст карты без разметки, переменных и динамического хвоста после «@»."""
    text = raw.split("@", 1)[0]
    text = re.sub(r"<[^>]+>|\[x\]|\{\d+\}|[$#&]", "", text)
    return " ".join(text.replace("_", " ").replace("\xa0", " ").split())


_BG_TYPES = {
    "MINION",
    "SPELL",
    "BATTLEGROUND_SPELL",
    "BATTLEGROUND_TRINKET",
    "HERO_POWER",
    "BATTLEGROUND_QUEST_REWARD",
    "BATTLEGROUND_ANOMALY",
}


def build_texts(cards: Iterable[dict]) -> dict[str, list[str]]:
    """{название: [тексты]} — коллекционные карты и карты Полей сражений.

    У одного названия бывает несколько текстов (переиздания, версия Полей
    сражений), поэтому список. Ванильные существа остаются с пустым списком:
    упоминание распознаётся, пересказывать нечего.
    """
    out: dict[str, set[str]] = {}
    for card in cards:
        name = card.get("name")
        bg = card.get("set") == "BATTLEGROUNDS" or card.get("techLevel")
        if not name or not (card.get("collectible") or (bg and card.get("type") in _BG_TYPES)):
            continue
        texts = out.setdefault(name, set())
        if card.get("text"):
            texts.add(clean_text(card["text"]))
    return {name: sorted(t for t in texts if t) for name, texts in sorted(out.items())}


def load_texts(path: Path = TEXTS) -> dict[str, list[str]]:
    if not path.exists():
        raise FileNotFoundError(
            f"нет снимка текстов карт {path}; обновить: editor-team card-paraphrase --update-texts"
        )
    return json.loads(path.read_text(encoding="utf-8"))["cards"]


def update_texts(fetch: Callable[[str], list[dict]], path: Path = TEXTS, taken: str = "") -> int:
    cards = build_texts(fetch(SOURCE))
    payload = {"_источник": SOURCE, "_снято": taken, "cards": cards}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return len(cards)


# ── Разбор текста ─────────────────────────────────────────────────────────


@dataclass
class Mention:
    card: str
    surface: str
    first: int  # индексы токенов предложения [first, last)
    last: int


@dataclass
class Sentence:
    text: str
    line: int
    tokens: list[str]
    lemmas: list[str]
    impr: list[bool]
    mentions: list[Mention] = field(default_factory=list)


class Lexicon:
    """Леммы и распознавание названий поверх `cards.Index`."""

    def __init__(
        self,
        idx,
        texts: dict[str, list[str]],
        common: Counter | None = None,
        skip_single: Iterable[str] = (),
    ):
        self.idx = idx
        self.texts = texts
        self.common = common or Counter()
        self.skip_single = {s.lower() for s in skip_single} | ARCHETYPE_WORDS
        self._parse: dict[str, tuple[str, str | None, bool]] = {}
        self._name_tokens: dict[str, list[str]] = {}
        self._text_lemmas: dict[str, list[list[frozenset]]] = {}

    def parse(self, word: str) -> tuple[str, str | None, bool]:
        """(лемма, часть речи, повелительное) по вероятнейшему разбору.

        Повелительное — по любому разбору у формы на «-те»: «держите»
        вероятнее изъявительное, но в гайде это обращение к читателю. Без
        «-те» — только по вероятнейшему: «боли» не приказ «болеть».
        """
        if word not in self._parse:
            low = word.lower()
            if low.isdigit():
                self._parse[word] = (low, "NUMB", False)
            else:
                parses = self.idx.morph.parse(low)
                p = parses[0]
                lemma = _NUMBERS.get(p.normal_form, p.normal_form)
                impr = "impr" in p.tag or (
                    low.endswith("те") and any("impr" in q.tag for q in parses)
                )
                self._parse[word] = (lemma, p.tag.POS, impr)
        return self._parse[word]

    def content(self, tokens: Iterable[str]) -> list[frozenset]:
        """Смысловые слова как множества всех разборов.

        Вероятнейший разбор ненадёжен на текстах карт без «ё»: «берете»
        он читает как «берет», а «берёте» автора — как «брать». Слова
        совпадают, если пересекаются их разборы.
        """
        out = []
        for t in tokens:
            lemma, pos, _ = self.parse(t)
            if pos in _DROP_POS or lemma in WRAPPER or (len(lemma) < 3 and not lemma.isdigit()):
                continue
            out.append(frozenset(_NUMBERS.get(x, x) for x in self.idx.lemmas(t.lower())))
        return out

    def card_texts(self, card: str) -> list[list[frozenset]]:
        """Смысловые слова каждого текста карты без слов самого названия."""
        if card not in self._text_lemmas:
            name = set().union(*(self.idx.lemmas(t.lower()) for t in _WORD.findall(card)))
            self._text_lemmas[card] = [
                [w for w in self.content(_WORD.findall(t)) if not w & name]
                for t in self.texts.get(card, [])
            ]
        return self._text_lemmas[card]

    def all_lemmas(self, text: str) -> Counter:
        return Counter(self.parse(t)[0] for t in _WORD.findall(text))

    def _tokens_of(self, name: str) -> list[str]:
        if name not in self._name_tokens:
            self._name_tokens[name] = _WORD.findall(name)
        return self._name_tokens[name]

    def _same(self, word: str, name_word: str) -> bool:
        return bool(self.idx.lemmas(word) & self.idx.lemmas(name_word)) or (
            word.lower() == name_word.lower()
        )

    def _short_name(self, word: str, lemmas: set, initial: bool, known) -> tuple[str, int] | None:
        """«Самуро» вместо «Мастер клинка Самуро», «Балинду» вместо «Балинда Каменный Очаг».

        Только имя собственное внутри имени карты: у карты не меньше двух слов
        с заглавной, и совпало одно из них. Иначе «Нечетный Паладин» становится
        картой «Нечетные не в почете», а «Hearthstone» — «Аватарой Hearthstone».
        """
        if not re.fullmatch(r"[А-ЯЁ][а-яё'’-]+", word):
            return None
        hits = {n for lemma in lemmas for n in self.idx.by_lemma.get(lemma, ())}
        if len(hits) != 1:
            return None
        name = next(iter(hits))
        # слово имени стоит в начальной форме: «Тетис» в «Адмирал флота Тетис»;
        # «Запределья» и «Наксрамаса» в родительном — это место, а не персонаж
        caps = [t.lower() for t in self._tokens_of(name) if t[:1].isupper()]
        normal = {q.normal_form for q in self.idx.morph.parse(word)}
        if len(caps) < 2 or not normal & set(caps):
            return None
        if initial and name not in known:
            return None
        return name, 1

    def mentions(self, tokens: list[str], known: Iterable[str] = ()) -> list[Mention]:
        """Упоминания карт: полное имя в любом падеже или однозначное короткое.

        Карта в тексте автора пишется с заглавной; однословное имя-обычное
        слово корпуса в начале предложения («Подготовка к матчу») считается
        картой, только если этот же текст называет её картой посреди фразы
        (`known`).
        """
        found: list[Mention] = []
        i = 0
        while i < len(tokens):
            word = tokens[i]
            if not word[:1].isupper() or len(word) < 3:
                i += 1
                continue
            lemmas = self.idx.lemmas(word)
            candidates = set()
            for lemma in lemmas:
                candidates |= self.idx.by_lemma.get(lemma, set())
            best = None
            for name in sorted(candidates, key=lambda n: -len(self._tokens_of(n))):
                parts = self._tokens_of(name)
                if i + len(parts) > len(tokens):
                    continue
                if all(self._same(tokens[i + k], parts[k]) for k in range(len(parts))):
                    best = (name, len(parts))
                    break
            commonish = any(self.common.get(lemma, 0) >= 5 for lemma in lemmas)
            skipped = bool(lemmas & self.skip_single)
            if (
                best
                and best[1] == 1
                and (skipped or (i == 0 and commonish and best[0] not in known))
            ):
                best = None
            if best is None and not (commonish or skipped):
                best = self._short_name(word, lemmas, i == 0, known)
            if best:
                found.append(Mention(best[0], " ".join(tokens[i : i + best[1]]), i, i + best[1]))
                i += best[1]
            else:
                i += 1
        return found


def _clean_inline(line: str) -> str:
    for pattern, repl in _INLINE:
        line = pattern.sub(repl, line)
    return line


def _blocks(body: str) -> list[tuple[int, str]]:
    """Абзацы и пункты списков с номером первой строки."""
    out: list[tuple[int, str]] = []
    buf: list[str] = []
    start = 0
    for n, raw in enumerate(body.split("\n"), 1):
        if not raw.strip() or _LIST_ITEM.match(raw):
            if buf:
                out.append((start, " ".join(buf)))
            buf = []
            if not raw.strip():
                continue
            raw = _LIST_ITEM.sub("", raw)
        if not buf:
            start = n
        buf.append(raw.strip())
    if buf:
        out.append((start, " ".join(buf)))
    return out


def split_sentences(text: str, lex: Lexicon, prose: Callable[[str], str]) -> list[list[Sentence]]:
    """Предложения по абзацам. `prose` убирает код, таблицы, цитаты и заголовки
    с сохранением строк (common.mask_protected + prose_only скилла)."""
    paragraphs = []
    for line, block in _blocks(prose(text)):
        sents = []
        for chunk in _SENT.split(_clean_inline(block)):
            tokens = _WORD.findall(chunk)
            if not tokens:
                continue
            parsed = [lex.parse(t) for t in tokens]
            sents.append(
                Sentence(
                    chunk.strip(), line, tokens, [p[0] for p in parsed], [p[2] for p in parsed]
                )
            )
        if sents:
            paragraphs.append(sents)
    sentences = [s for sents in paragraphs for s in sents]
    for s in sentences:
        s.mentions = lex.mentions(s.tokens)
    known = {m.card for s in sentences for m in s.mentions if m.first > 0}
    for s in sentences:
        if s.tokens and s.tokens[0][:1].isupper():
            s.mentions = lex.mentions(s.tokens, known)
    return paragraphs


# ── Три замера ────────────────────────────────────────────────────────────


def _own(sentence: Sentence) -> list[str]:
    """Токены предложения без слов названий карт."""
    inside = {k for m in sentence.mentions for k in range(m.first, m.last)}
    return [t for k, t in enumerate(sentence.tokens) if k not in inside]


def context_kinds(tokens: list[str], lex: Lexicon, card_lemmas: Counter) -> set[str]:
    """Какие из пяти опор совета есть в токенах сверх текста самой карты.

    Леммы вычитаются мультимножеством: «если» из текста карты не делает
    пересказ советом, а второе, авторское «если» — делает.
    """
    words = Counter(lex.parse(t)[0] for t in tokens) - card_lemmas
    joined = " ".join(tokens)
    kinds = {kind for kind, marks in CONTEXT.items() if marks & words.keys()}
    kinds |= {kind for kind, pattern in _SURFACE.items() if pattern.search(joined)}
    # «Возвращайте Бандитку Шагом сквозь тень», «стоит разыграть» — как играть
    if words.keys() & DECISION or any(lex.parse(t)[2] for t in tokens):
        kinds.add("when")
    if _NEGATIVE_ADVICE.search(joined):
        kinds.add("mistake")
    return kinds


def _card_all_lemmas(card: str, lex: Lexicon) -> Counter:
    out = Counter()
    for t in lex.texts.get(card, []):
        out |= lex.all_lemmas(t)
    return out


def _cards_lemmas(sentence: Sentence, lex: Lexicon) -> Counter:
    out = Counter()
    for m in sentence.mentions:
        out |= _card_all_lemmas(m.card, lex)
    return out


def paraphrase_score(sentence: Sentence, card: str, lex: Lexicon) -> tuple[float, float, int]:
    """(доля текста карты, доля своих слов, общих лемм) для лучшего текста карты."""
    own = lex.content(_own(sentence))
    best = (0.0, 1.0, 0)
    for text in lex.card_texts(card):
        if not text:
            continue
        used = [False] * len(own)
        overlap = 0
        for word in text:
            for k, mine in enumerate(own):
                if not used[k] and mine & word:
                    used[k] = True
                    overlap += 1
                    break
        cover = overlap / len(text)
        novelty = used.count(False) / max(len(own), 1)
        if (cover, -novelty) > (best[0], -best[1]):
            best = (cover, novelty, overlap)
    return best


def signals(sentence: Sentence, minus: Counter | None = None) -> tuple[bool, bool, bool]:
    """(условие, решение, причина) в предложении сверх лемм `minus` (текста карты)."""
    low = sentence.text.lower()
    words = Counter(sentence.lemmas) - (minus or Counter())
    cond = (
        bool(words.keys() & CONDITION)
        or "как только" in low
        or bool(_SURFACE["against"].search(low))
    )
    decision = (
        bool(words.keys() & DECISION)
        or re.search(r"\bлучше\b", low) is not None  # pymorphy: «лучше» → «хороший»
        or any(sentence.impr)
        or bool(_NEGATIVE_ADVICE.search(low))
    )
    reason = bool(words.keys() & REASON) or "так как" in low
    return cond, decision, reason


def is_insight(sentence: Sentence, following: Sentence | None) -> bool:
    cond, decision, reason = signals(sentence)
    if not reason and following and following.lemmas and following.lemmas[0] in REASON_LEADS:
        reason = True
    return cond and decision and reason


def analyze(text: str, lex: Lexicon, prose: Callable[[str], str], document: str = "") -> dict:
    paragraphs = split_sentences(text, lex, prose)
    prose_sentences = mention_sentences = mentions = insights = 0
    paraphrases: list[dict] = []
    bare: list[dict] = []
    for sents in paragraphs:
        for k, s in enumerate(sents):
            own = _own(s)
            if len(own) < 3:
                continue  # строка списка карт или подпись, а не фраза
            prose_sentences += 1
            following = sents[k + 1] if k + 1 < len(sents) else None
            if is_insight(s, following):
                insights += 1
            if not s.mentions:
                continue
            mention_sentences += 1
            near = set()
            for w in sents[max(k - 1, 0) : k + 2]:
                near |= context_kinds(_own(w), lex, _cards_lemmas(w, lex))
            flagged = False
            for m in s.mentions:
                mentions += 1
                card_lemmas = _card_all_lemmas(m.card, lex)
                if not near:
                    bare.append(
                        {"line": s.line, "card": m.card, "form": m.surface, "quote": s.text}
                    )
                if flagged:
                    continue
                cover, novelty, overlap = paraphrase_score(s, m.card, lex)
                if (
                    overlap >= MIN_OVERLAP
                    and cover >= COVER_MIN
                    and novelty <= NOVELTY_MAX
                    and not context_kinds(own, lex, card_lemmas)
                    and not any(signals(s, card_lemmas))
                ):
                    flagged = True
                    paraphrases.append(
                        {
                            "line": s.line,
                            "card": m.card,
                            "quote": s.text,
                            "card_text": " | ".join(lex.texts.get(m.card, [])),
                            "cover": round(cover, 2),
                            "novelty": round(novelty, 2),
                        }
                    )
    metrics = {
        "prose_sentences": prose_sentences,
        "mention_sentences": mention_sentences,
        "mentions": mentions,
        "paraphrase_rate": _rate(len(paraphrases), mention_sentences),
        "bare_mention_rate": _rate(len(bare), mentions),
        "insight_density": _rate(insights, prose_sentences),
    }
    return {
        "document": document,
        "metrics": metrics,
        "thresholds": thresholds(),
        "verdicts": verdicts(metrics),
        "paraphrases": paraphrases,
        "bare_mentions": bare,
    }


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def thresholds() -> dict:
    return {
        "paraphrase_rate_max": PARAPHRASE_MAX,
        "bare_mention_rate_max": BARE_MENTION_MAX,
        "insight_density_min": INSIGHT_MIN,
    }


def verdicts(metrics: dict) -> dict:
    """True — в норме автора, False — хуже порога, None — нечего мерить."""

    def check(value, ok):
        return None if value is None else ok(value)

    return {
        "paraphrase_rate": check(metrics["paraphrase_rate"], lambda v: v <= PARAPHRASE_MAX),
        "bare_mention_rate": check(metrics["bare_mention_rate"], lambda v: v <= BARE_MENTION_MAX),
        "insight_density": check(metrics["insight_density"], lambda v: v >= INSIGHT_MIN),
    }


def percentiles(values: list[float], points=(10, 25, 50, 75, 90, 95, 99, 100)) -> dict:
    """Ближайший ранг: порог — значение, которое действительно встретилось у автора."""
    vals = sorted(values)
    if not vals:
        return {}
    return {f"p{p}": vals[max(0, math.ceil(p / 100 * len(vals)) - 1)] for p in points}


def calibrate(reports: list[dict]) -> dict:
    out = {"documents": len(reports)}
    for key in ("paraphrase_rate", "bare_mention_rate", "insight_density"):
        vals = [r["metrics"][key] for r in reports if r["metrics"][key] is not None]
        out[key] = {"measured": len(vals), **percentiles(vals)}
    return out


def render(report: dict, limit: int = 20) -> str:
    m, v = report["metrics"], report["verdicts"]
    mark = {True: "норма", False: "ВНЕ НОРМЫ", None: "—"}
    t = report["thresholds"]
    lines = [
        f"\n{report['document']}",
        "  Механический текст про карты (диагностика, решает редактор)",
    ]
    if report["paraphrases"]:
        lines.append(f"\n  ПЕРЕСКАЗ ЭФФЕКТА ({len(report['paraphrases'])})")
        for p in report["paraphrases"][:limit]:
            lines.append(f"    стр.{p['line']} {p['card']}: «{p['quote']}»")
            lines.append(f"        текст карты: {p['card_text']}")
    if report["bare_mentions"]:
        lines.append(f"\n  УПОМИНАНИЕ БЕЗ СОВЕТА ({len(report['bare_mentions'])})")
        for b in report["bare_mentions"][:limit]:
            lines.append(f"    стр.{b['line']} {b['card']}: «{b['quote']}»")
        if len(report["bare_mentions"]) > limit:
            lines.append(
                f"    … ещё {len(report['bare_mentions']) - limit}, полный список в --format json"
            )
    lines += [
        "\n  ИЗМЕРЕНО",
        f"    предложений прозы      {m['prose_sentences']}",
        f"    упоминаний карт        {m['mentions']} в {m['mention_sentences']} предложениях",
        f"    доля пересказа         {m['paraphrase_rate']}  (≤ {t['paraphrase_rate_max']}: {mark[v['paraphrase_rate']]})",
        f"    упоминаний без совета  {m['bare_mention_rate']}  (≤ {t['bare_mention_rate_max']}: {mark[v['bare_mention_rate']]})",
        f"    плотность инсайта      {m['insight_density']}  (≥ {t['insight_density_min']}: {mark[v['insight_density']]})",
    ]
    return "\n".join(lines)
