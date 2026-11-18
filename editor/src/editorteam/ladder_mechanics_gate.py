"""Детерминированный гейт игровой физики для гайдов Стандарта и Вольного (без LLM).

Симметричен `bg_mechanics_gate`, но для ладдера: сверяет с данными
HearthstoneJSON то, что в тексте записано как факт о карте, и разбирает
дек-коды статьи. Ловит только узкие однозначные формы, чтобы не шуметь:

* стоимость рядом с названием: «Рагнарос (8)», «8-мановый Рагнарос»;
  «Рагнарос стоит 8 маны» — предупреждение (часто это цена после эффекта),
  «за 8 маны» не проверяется (розыгрыш со скидкой);
* атака и здоровье рядом с названием: «Рагнарос 8/8», «Рагнарос (8/8)»;
* «Боевой клич <карты>» и «Предсмертный хрип <карты>» (название в косвенном
  падеже) у карты без такого свойства;
* «<легендарная карта> x2» — ошибка, «две копии <легендарной>» — предупреждение
  (копии бывают созданными в игре);
* дек-коды: декодируются, 30 карт, формат совпадает с текстом, у легендарок
  одна копия; карты из раздела «Мулиган» есть в списке колоды.

Если в предложении есть слова скидки или усиления («дешевле», «получает»),
расхождение по стоимости или статам не считается ошибкой.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from functools import lru_cache

from editorteam.bg_mechanics_gate import SHORTCODE_TAG, _blank, _line

ANALYZER = "ladder_mechanics_gate"
CARD_TYPES = frozenset({"MINION", "SPELL", "WEAPON", "LOCATION", "HERO"})
# Скины героев делят имена с картами («Рагнарос Повелитель Огня», редкость FREE),
# а Классика (VANILLA) хранит старые стоимости: по имени их не сверяем.
EXCLUDED_SETS = frozenset({"HERO_SKINS", "VANILLA", "BATTLEGROUNDS", "LETTUCE"})
DECK_FORMATS = {1: "wild", 2: "standard", 3: "classic", 4: "twist"}
FORMAT_WORDS = {
    "standard": re.compile(r"\bСтандарт\w*", re.I),
    "wild": re.compile(r"\bВольн\w*", re.I),
}
DECK_CODE = re.compile(r"(?<![A-Za-z0-9+/])AAE[A-Za-z0-9+/]{12,}={0,2}")
DISCOUNT = re.compile(r"скидк|дешев|уменьш|сниж|меньше|бесплатн|подешев", re.I)
BUFF = re.compile(r"получа|получит|усил|бафф|прибав|увелич|\+\d", re.I)
KEYWORDS = {
    "BATTLECRY": (re.compile(r"Боев\w*\s+клич\w*\s+$", re.I), "Боев"),
    "DEATHRATTLE": (re.compile(r"Предсмертн\w*\s+хрип\w*\s+$", re.I), "Предсмертн"),
}
COST_PAREN = re.compile(r"^\s*\((\d{1,2})\)")
STATS_AFTER = re.compile(r"^\s*\(?(\d{1,2})\s*/\s*(\d{1,2})\)?(?![\d/])")
# «Стоит N маны» часто описывает карту после эффекта («возвращённый Шагом сквозь
# тень Фонарщик стоит 1»), а «за N маны» — розыгрыш со скидкой: только предупреждение
# и только для «стоит»; «за N маны» не проверяем вовсе.
COST_STATED = re.compile(r"^\s+(?:стоит|стоимостью)\s+(\d{1,2})\s+ман", re.I)
COST_BEFORE = re.compile(r"(\d{1,2})\s*-?\s*манов\w*\s+$", re.I)
# Закрытый список падежных окончаний: «Охота» не должна совпасть с «Охотником».
_ENDINGS = (
    "ами|ями|ого|его|ому|ему|ыми|ими|ой|ей|ою|ею|ом|ем|ам|ям|ах|ях|ым|им|ых|их|"
    "ую|юю|ая|яя|ое|ее|ые|ие|ью|а|я|о|е|и|ы|у|ю|ь|й"
)
_ADJ_END = re.compile(r"(?:ый|ий|ой|ая|яя|ое|ее|ые|ие|ых|их)$", re.I)
_WORD_PART = re.compile(r"(\s+|-)")
TWO_COPIES_BEFORE = re.compile(r"(?:две|2|обе|двух)\s+копи\w*\s+$", re.I)
TWO_COPIES_AFTER = re.compile(r"^\s*[xх×]\s*2\b", re.I)
MULLIGAN_HEADING = re.compile(r"^(#{1,6})\s+.*(?:мулиган|mulligan)", re.I | re.M)
HEADING = re.compile(r"^(#{1,6})\s+", re.M)
LIST_LINE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s")
_SENTENCE_END = re.compile(r"[.!?…\n]")


@dataclass
class CardIndex:
    by_name: dict[str, list[dict]] = field(default_factory=dict)
    by_dbf: dict[int, dict] = field(default_factory=dict)


def _ru(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("ruRU", "")
    return value if isinstance(value, str) else ""


def load_cards(path: str | Path) -> list[dict]:
    """`cards.json` или `cards.collectible.json` HearthstoneJSON: ruRU или all."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("ожидался список карт HearthstoneJSON")
    return data


def build_index(cards: list[dict]) -> CardIndex:
    index = CardIndex()
    for card in cards:
        if isinstance(card.get("dbfId"), int):
            index.by_dbf[card["dbfId"]] = card
        if not card.get("collectible") or card.get("type") not in CARD_TYPES:
            continue
        if card.get("set") in EXCLUDED_SETS:
            continue
        name = _ru(card.get("name")).strip()
        if len(name) >= 3:
            index.by_name.setdefault(name, []).append(card)
    return index


# ---------------------------------------------------------------- deck codes


def decode_deckstring(code: str) -> dict:
    """Разбор дек-кода Hearthstone: формат, герои и {dbfId: копии}."""
    try:
        raw = base64.b64decode(code + "=" * (-len(code) % 4), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"не base64: {exc}") from exc
    pos = 0

    def varint() -> int:
        nonlocal pos
        result = shift = 0
        while True:
            if pos >= len(raw):
                raise ValueError("дек-код обрывается")
            byte = raw[pos]
            pos += 1
            result |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return result
            shift += 7

    if not raw or raw[0] != 0:
        raise ValueError("нет нулевого байта заголовка")
    pos = 1
    varint()  # версия
    fmt = varint()
    heroes = [varint() for _ in range(varint())]
    cards: dict[int, int] = {}
    for copies in (1, 2):
        for _ in range(varint()):
            dbf = varint()
            cards[dbf] = cards.get(dbf, 0) + copies
    for _ in range(varint()):
        dbf = varint()
        cards[dbf] = cards.get(dbf, 0) + varint()
    return {"format": DECK_FORMATS.get(fmt, str(fmt)), "heroes": heroes, "cards": cards}


# ---------------------------------------------------------------- helpers


def _finding(text: str, code: str, severity: str, message: str, start: int, end: int,
             suggestion: str = "", **meta) -> dict:
    result = {
        "id": code,
        "analyzer": ANALYZER,
        "category": "ladder-mechanics",
        "severity": severity,
        "message": message,
        "evidence": text[start:end].strip(),
        "line": _line(text, start),
        "start": start,
        "end": end,
    }
    if suggestion:
        result["suggestion"] = suggestion
    if meta:
        result["meta"] = meta
    return result


def _word_pattern(word: str) -> str:
    low = word.lower()
    if len(word) <= 3 or not word[-1].isalpha():
        stem = word
    elif _ADJ_END.search(low):
        stem = word[:-2]
    elif len(word) > 4 and low.endswith(("ок", "ек")):
        stem = word[:-2] + word[-1]  # беглая гласная: Щенок → Щенка
    elif low[-1] in "аеёиоуыэюяьй":
        stem = word[:-1]
    else:
        stem = word

    def soft(value: str) -> str:
        return "".join("[её]" if ch in "её" else ch for ch in re.escape(value))

    return rf"(?:{soft(word)}|{soft(stem)}(?:{_ENDINGS})?)"


@lru_cache(maxsize=None)
def _name_pattern(name: str) -> re.Pattern[str]:
    out = []
    for part in _WORD_PART.split(name):
        if not part:
            continue
        if part.isspace():
            out.append(r"\s+")
        elif part == "-":
            out.append(r"\s*-\s*")
        else:
            out.append(_word_pattern(part))
    return re.compile(r"(?<![\w-])" + "".join(out) + r"(?![\w-])")


def _sentence(text: str, start: int, end: int) -> str:
    left = max((m.end() for m in _SENTENCE_END.finditer(text, 0, start)), default=0)
    right = _SENTENCE_END.search(text, end)
    return text[left: right.start() if right else len(text)]


def _mentions(text: str, index: CardIndex) -> list[tuple[int, int, str]]:
    folded = text.casefold().replace("ё", "е")
    found: list[tuple[int, int, str]] = []
    for name in index.by_name:
        head = name.casefold().replace("ё", "е")[:4]
        if head not in folded:
            continue
        for match in _name_pattern(name).finditer(text):
            found.append((match.start(), match.end(), name))
    # Длинное название важнее короткого внутри него: «Рагнарос, Повелитель Огня».
    found.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    kept: list[tuple[int, int, str]] = []
    for item in found:
        if kept and item[0] < kept[-1][1]:
            continue
        kept.append(item)
    return kept


def _sections(text: str, heading: re.Pattern[str]) -> list[tuple[int, int]]:
    spans = []
    for match in heading.finditer(text):
        level = len(match.group(1))
        end = len(text)
        for nxt in HEADING.finditer(text, match.end()):
            if len(nxt.group(1)) <= level:
                end = nxt.start()
                break
        spans.append((match.start(), end))
    return spans


# ---------------------------------------------------------------- checks


def _check_mention(text: str, start: int, end: int, name: str, cards: list[dict]) -> list[dict]:
    findings: list[dict] = []
    after, before = text[end:end + 40], text[max(0, start - 40):start]
    sentence = _sentence(text, start, end)
    costs = {c.get("cost") for c in cards if isinstance(c.get("cost"), int)}
    ids = sorted({str(c.get("id")) for c in cards})

    stats = STATS_AFTER.match(after)
    if stats:
        claimed = (int(stats.group(1)), int(stats.group(2)))
        real = {
            (c.get("attack"), c.get("health", c.get("durability")))
            for c in cards
            if isinstance(c.get("attack"), int)
        }
        if real and claimed not in real and not BUFF.search(sentence):
            shown = ", ".join(f"{a}/{h}" for a, h in sorted(real, key=str))
            findings.append(_finding(
                text, "ladder.stats_mismatch", "error",
                f"У «{name}» по данным карты {shown}, а в тексте {claimed[0]}/{claimed[1]}.",
                start, end + stats.end(), f"Исправьте на {shown} или поясните усиление.",
                card_ids=ids,
            ))
        return findings

    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line = text[line_start: line_end if line_end >= 0 else len(text)]
    # В списке колоды «Карта (2)» может значить число копий, а не ману.
    paren_severity = "warning" if LIST_LINE.match(line) or "|" in line else "error"
    for pattern, severity in ((COST_PAREN, paren_severity), (COST_STATED, "warning")):
        match = pattern.match(after)
        if match:
            claimed = int(match.group(1))
            if costs and claimed not in costs and not DISCOUNT.search(sentence):
                shown = ", ".join(str(c) for c in sorted(costs))
                findings.append(_finding(
                    text, "ladder.cost_mismatch", severity,
                    f"«{name}» стоит {shown} маны, а в тексте {claimed}.",
                    start, end + match.end(),
                    "Исправьте стоимость или назовите скидку, из-за которой карта дешевле.",
                    card_ids=ids,
                ))
            break
    before_cost = COST_BEFORE.search(before)
    if before_cost:
        claimed = int(before_cost.group(1))
        if costs and claimed not in costs and not DISCOUNT.search(sentence):
            shown = ", ".join(str(c) for c in sorted(costs))
            findings.append(_finding(
                text, "ladder.cost_mismatch", "error",
                f"«{name}» стоит {shown} маны, а в тексте {claimed}-мановая карта.",
                start - (len(before) - before_cost.start()), end,
                "Исправьте стоимость или назовите скидку.", card_ids=ids,
            ))

    # «Боевой клич Неофитки культа» — свойство карты; «активирует боевой клич
    # Древнее знание» — название в начальной форме стоит как дополнение.
    inflected = text[start:end] != name
    for mechanic, (pattern, stem) in KEYWORDS.items():
        match = pattern.search(before)
        if not match or not inflected:
            continue
        has = any(
            mechanic in (c.get("mechanics") or [])
            or stem.casefold() in _ru(c.get("text")).casefold()
            for c in cards
        )
        if not has:
            findings.append(_finding(
                text, "ladder.keyword_mismatch", "error",
                f"У «{name}» нет свойства «{match.group(0).strip()}» в тексте карты.",
                start - (len(before) - match.start()), end,
                "Сверьте свойство с текстом карты.", card_ids=ids, mechanic=mechanic,
            ))

    copies = TWO_COPIES_BEFORE.search(before)
    copies_after = TWO_COPIES_AFTER.match(after)
    if (copies or copies_after) and cards and all(c.get("rarity") == "LEGENDARY" for c in cards):
        span_start = start - (len(before) - copies.start()) if copies else start
        span_end = end + copies_after.end() if copies_after else end
        # «x2» — запись списка колоды; «две копии» бывают созданными в игре.
        findings.append(_finding(
            text, "ladder.legendary_copies", "error" if copies_after else "warning",
            f"«{name}» — легендарная карта, в колоде может быть только одна копия.",
            span_start, span_end, "Уберите вторую копию из текста.", card_ids=ids,
        ))
    return findings


def _check_decks(text: str, codes: list[tuple[int, int, str]], index: CardIndex) -> tuple[list[dict], set[int], set[str]]:
    findings: list[dict] = []
    deck_dbfs: set[int] = set()
    deck_classes: set[str] = set()
    mentions = {fmt: len(pattern.findall(text)) for fmt, pattern in FORMAT_WORDS.items()}
    for start, end, code in codes:
        try:
            deck = decode_deckstring(code)
        except ValueError as exc:
            findings.append(_finding(
                text, "ladder.deckcode_invalid", "error",
                f"Дек-код не читается: {exc}.", start, end,
                "Скопируйте код колоды из клиента заново.",
            ))
            continue
        cards = deck["cards"]
        deck_dbfs.update(cards)
        for hero in deck["heroes"]:
            hero_class = index.by_dbf.get(hero, {}).get("cardClass")
            if isinstance(hero_class, str):
                deck_classes.add(hero_class)
        total = sum(cards.values())
        if total not in (30, 40):
            findings.append(_finding(
                text, "ladder.deck_size", "warning",
                f"В дек-коде {total} карт вместо 30.", start, end,
                "Проверьте, что код скопирован целиком.", total=total,
            ))
        unknown = sorted(dbf for dbf in cards if dbf not in index.by_dbf)
        if unknown:
            findings.append(_finding(
                text, "ladder.deck_unknown_cards", "warning",
                f"В дек-коде {len(unknown)} карт, которых нет в данных HearthstoneJSON: "
                "обновите cards.json.", start, end, dbf_ids=unknown,
            ))
        for dbf, count in cards.items():
            card = index.by_dbf.get(dbf)
            if card and card.get("rarity") == "LEGENDARY" and count > 1:
                findings.append(_finding(
                    text, "ladder.legendary_copies", "error",
                    f"В дек-коде {count} копии легендарной «{_ru(card.get('name'))}».",
                    start, end, card_ids=[str(card.get("id"))],
                ))
        fmt = deck["format"]
        other = "wild" if fmt == "standard" else "standard" if fmt == "wild" else None
        if other and mentions.get(other, 0) and not mentions.get(fmt, 0):
            word = {"standard": "Стандарт", "wild": "Вольный"}
            findings.append(_finding(
                text, "ladder.deck_format_mismatch", "warning",
                f"Дек-код собран для формата «{word[fmt]}», а текст говорит только о формате «{word[other]}».",
                start, end, deck_format=fmt,
            ))
    return findings, deck_dbfs, deck_classes


def check_ladder_mechanics(text: str, cards: list[dict], deck_codes: list[str] | None = None) -> list[dict]:
    """Найти механические ошибки ладдерного гайда; карты — список HearthstoneJSON."""
    index = build_index(cards)
    plain = _blank(text, SHORTCODE_TAG)
    codes = [(m.start(), m.end(), m.group(0)) for m in DECK_CODE.finditer(plain)]
    for extra in deck_codes or []:
        if extra not in {code for _, _, code in codes}:
            codes.append((0, 0, extra))
    findings, deck_dbfs, deck_classes = _check_decks(plain, codes, index)

    code_spans = [(start, end) for start, end, _ in codes]
    mentions = [
        item for item in _mentions(plain, index)
        if not any(s <= item[0] < e for s, e in code_spans)
    ]
    for start, end, name in mentions:
        findings.extend(_check_mention(plain, start, end, name, index.by_name[name]))

    if deck_dbfs:
        allowed_classes = deck_classes | {"NEUTRAL"}
        for section_start, section_end in _sections(plain, MULLIGAN_HEADING):
            for start, end, name in mentions:
                if not section_start <= start < section_end:
                    continue
                variants = index.by_name[name]
                if deck_classes and not any(c.get("cardClass") in allowed_classes for c in variants):
                    continue  # карта соперника
                if not any(c.get("dbfId") in deck_dbfs for c in variants):
                    findings.append(_finding(
                        plain, "ladder.mulligan_not_in_deck", "warning",
                        f"«{name}» упомянута в мулигане, но её нет в дек-коде статьи.",
                        start, end, "Проверьте список колоды или уберите карту из мулигана.",
                        card_ids=sorted({str(c.get("id")) for c in variants}),
                    ))
    findings.sort(key=lambda item: (item["start"], item["id"]))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m editorteam.ladder_mechanics_gate",
        description="Проверка игровой физики гайдов Стандарта и Вольного (без LLM).",
    )
    parser.add_argument("file", help="файл статьи (Markdown/TXT)")
    parser.add_argument("--cards", required=True,
                        help="cards.json или cards.collectible.json HearthstoneJSON (ruRU или all)")
    parser.add_argument("--deckcode", action="append", default=[],
                        help="дек-код, если его нет в тексте (можно несколько)")
    args = parser.parse_args(argv)
    text = Path(args.file).read_text(encoding="utf-8")
    findings = check_ladder_mechanics(text, load_cards(args.cards), args.deckcode)
    sys.stdout.write(json.dumps(findings, ensure_ascii=False, indent=2) + "\n")
    return 1 if any(f["severity"] == "error" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
