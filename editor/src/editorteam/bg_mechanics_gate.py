"""Детерминированный чекер игровой физики в русских текстах о Полях сражений.

Ловит без модели ошибки, которые владелец возвращал в разборах БГ-статей:

    bg.forbidden_tribe_word  — слово «племя» в любой форме (пишем «тип существ»);
    bg.lobby_tautology       — «в лобби с демонами» про однотипового демона:
                               без своего типа в лобби он вообще не появится;
    bg.battlecry_in_hand     — «собирают удачных Стрелков в руке»: Боевой клич
                               срабатывает при розыгрыше, в руке свойства нет;
    bg.turn2_curve           — существо 2-го уровня или заклинание «на 2-м ходу»
                               и «лишнее золото на 2-м ходу» без источника на 1-м;
    bg.token_zone_mismatch   — щупальце Зоатроида «остаётся на столе» (оно в руке);
    bg.false_free_gold       — «бесплатное золото» от лев-рыбы и нетопыря:
                               активация стоит 2, добытчик продаётся за 1;
    bg.unlinked_pool_spell   — заклинание таверны без шорткода [hs_bg] (warning).

Находки — словари в духе `finding.Finding.to_dict()`; у `unlinked_pool_spell`
severity `warning`, поэтому модель Finding здесь не используется напрямую.

    python -m editorteam.bg_mechanics_gate article.md --dossier dossier.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ANALYZER = "bg_mechanics_gate"
_W = r"[а-яёА-ЯЁ]"

# Встроенный справочник: имя (как в карте) -> (типы существ, уровень таверны).
# Актуальный тир-1 пул и карты, на которых ошибались в разборах.
BUILTIN_MINIONS: dict[str, tuple[tuple[str, ...], int]] = {
    "Иглошкур-геомант": (("QUILBOAR",), 1),
    "Клыкастый походник": (("QUILBOAR",), 1),
    "Порхающий нетопырь": (("BEAST",), 1),
    "Жужжащий вредитель": (("BEAST",), 1),
    "Дюнный силач": (("ELEMENTAL",), 1),
    "Трескучий циклон": (("ELEMENTAL",), 1),
    "Пузырьковый стрелок": (("MURLOC",), 1),
    "Вертлявый разведчик": (("MURLOC",), 1),
    "Заклинатель гнева": (("DEMON",), 1),
    "Баюбот": (("MECHANICAL",), 1),
    "Протягиватель кабелей": (("MECHANICAL",), 1),
    "Бликостраж": (("DRAGON",), 1),
    "Выживший красный дракон": (("DRAGON",), 1),
    "Золотой призер": (("PIRATE",), 1),
    "Музыкант Южных Морей": (("PIRATE",), 1),
    "Безобидная черепушка": (("UNDEAD",), 1),
    "Восставший всадник": (("UNDEAD",), 1),
    "Счастье": (("ABERRATION",), 1),
    "Зоатроид": (("ABERRATION",), 1),
    "Зловещая пророчица": (("DEMON", "NAGA"), 1),
    "Подозрительный надзиратель": ((), 1),
    "Дирижер душ": (("DEMON",), 2),
    "Затаившаяся лев-рыба": (("BEAST",), 2),
    "Пепельный осквернитель": (("DEMON",), 4),
}
# Короткие имена, которыми авторы зовут карты в тексте.
ALIASES = {
    "Геомант": "Иглошкур-геомант",
    "Походник": "Клыкастый походник",
    "Нетопырь": "Порхающий нетопырь",
    "Вредитель": "Жужжащий вредитель",
    "Силач": "Дюнный силач",
    "Циклон": "Трескучий циклон",
    "Стрелок": "Пузырьковый стрелок",
    "Разведчик": "Вертлявый разведчик",
    "Заклинатель": "Заклинатель гнева",
    "Протягиватель": "Протягиватель кабелей",
    "Призер": "Золотой призер",
    "Музыкант": "Музыкант Южных Морей",
    "Черепушка": "Безобидная черепушка",
    "Всадник": "Восставший всадник",
    "Пророчица": "Зловещая пророчица",
    "Дирижер": "Дирижер душ",
    "Осквернитель": "Пепельный осквернитель",
    "Лев-рыба": "Затаившаяся лев-рыба",
}

TYPE_WORDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^свинобраз", re.I), "QUILBOAR"),
    (re.compile(r"^дракон", re.I), "DRAGON"),
    (re.compile(r"^пират", re.I), "PIRATE"),
    (re.compile(r"^мурлок", re.I), "MURLOC"),
    (re.compile(r"^звер", re.I), "BEAST"),
    (re.compile(r"^элементал", re.I), "ELEMENTAL"),
    (re.compile(r"^нежит", re.I), "UNDEAD"),
    (re.compile(r"^(?:механизм|мех(?:и|ов|ами|ам|ах)?$)", re.I), "MECHANICAL"),
    (re.compile(r"^демон", re.I), "DEMON"),
    (re.compile(r"^наг(?:а|и|ой|ам|ами|ах)?$", re.I), "NAGA"),
    (re.compile(r"^аберрац", re.I), "ABERRATION"),
)
TYPE_RU = {
    "QUILBOAR": "Свинобразы", "DRAGON": "Драконы", "PIRATE": "Пираты", "MURLOC": "Мурлоки",
    "BEAST": "Звери", "ELEMENTAL": "Элементали", "UNDEAD": "Нежить", "MECHANICAL": "Механизмы",
    "DEMON": "Демоны", "NAGA": "Наги", "ABERRATION": "Аберрации",
}

POOL_SPELLS = {
    "BG28_810": ("Монетка таверны", r"[Мм]онетк\w*\s+таверны"),
    "BG28_897": ("Банан в меню", r"[Бб]анан\w*\s+в\s+меню"),
    "BG31_880": ("Флаг Альянса", r"[Фф]лаг\w*\s+Альянса"),
    "BG28_503": ("Укрепление", r"Укреплени\w*"),
    "BG28_966": ("Лови яблочко", r"[Лл]ови\s+яблочко"),
    "BG28_512": ("Зачарованное лассо", r"[Зз]ачарованн\w*\s+лассо"),
    "BG28_504": ("Вербовка новобранца", r"[Вв]ербовк\w*\s+новобранц\w*"),
}

TRIBE_WORD = re.compile(
    rf"(?<!{_W})плем(?:енами|енах|енам|енем|ени|ена|ён|ен|я)(?!{_W})", re.I
)
LOBBY = re.compile(
    rf"лобби\s+(?:со?|без)\s+({_W}+(?:(?:\s*,\s*|\s+и\s+|\s+или\s+){_W}+)*)", re.I
)
TURN2 = re.compile(r"(?:на|к|со?)\s+(?:2(?:\s*[-–—]\s*м|-?ом)?|втором|второго)\s+ход\w*", re.I)
TURN2_GOLD = re.compile(
    r"лишн\w*\s+(?:\w+\s+){0,2}?золот\w*\s+(?:\w+\s+){0,1}?на\s+2(?:\s*[-–—]\s*\d)?(?:\s*[-–—]\s*м)?\s+ход",
    re.I,
)
TIER2_WORDS = re.compile(r"(?:2-го|второго)\s+(?:уровня|тира)|тир[а-]?\s*2|уровн\w*\s+2", re.I)
ACQUIRE = re.compile(r"(?<!\w)(?:найд|наход|куп|покуп|возьм|бер[её]|забер|взя)\w*", re.I)
SPELL_WORD = re.compile(r"заклинани\w*", re.I)
ECONOMY = re.compile(
    r"Музыкант|Монетк|Зоатроид|сил\w*\s+геро|аномали|Busker|Tavern Coin|Zoatroid|hero power|anomaly",
    re.I,
)
HAND = re.compile(r"в\s+руке|в\s+руку|в\s+руках", re.I)
LUCKY = re.compile(
    r"удачн\w*|уже\s+получивш\w*|получивш\w*\s+(?:\w+\s+)?свойств\w*|"
    r"с\s+(?:нужн|хорош|удачн|правильн)\w*\s+свойств\w*",
    re.I,
)
HOLD = re.compile(r"(?<!\w)(?:собира|соб[ие]р|копи|накап|накоп|держ|отбира|отбер|придерж|храни|остав)\w*", re.I)
TENTACLE = re.compile(r"щупальц\w*", re.I)
ON_BOARD = re.compile(
    r"(?:оста\w*|призыва\w*|призов\w*|появ\w*|встан\w*|выход\w*|выйд\w*)\s+(?:\w+\s+){0,2}?на\s+стол\w*"
    r"|на\s+стол\w*\s+(?:\w+\s+){0,2}?(?:оста\w*|призыва\w*|появ\w*)",
    re.I,
)
FREE_GOLD = re.compile(
    r"бесплатн\w*\s+(?:\w+\s+){0,2}?золот\w*|золот\w*\s+(?:\w+\s+){0,3}?бесплатн\w*"
    r"|бесплатн\w*\s+(?:\w+\s+){0,3}?продаж\w*",
    re.I,
)
LIONFISH_CONTEXT = re.compile(r"лев-рыб\w*|нетопыр\w*|добытчик\w*", re.I)
REAL_COST = re.compile(
    r"\+5/\+5|(?:за|по|стоит|стоимост\w*|цен\w*)\s+(?:в\s+)?(?:2|два|двух)\s+(?:золот|монет)\w*"
    r"|(?:2|два|двух)\s+(?:золот|монет)\w*",
    re.I,
)
SHORTCODE_TAG = re.compile(r"\[/?(?:hs_bg|hs_card)\b[^\]]*\]", re.I)
SHORTCODE_FULL = re.compile(r"\[(hs_bg|hs_card)\b[^\]]*\].*?\[/\1\]", re.I | re.S)
QUOTED = re.compile(r"«[^«»\n]*»|„[^„“\n]*“|\"[^\"\n]*\"|^\s*>.*$", re.M)
_SENTENCE = re.compile(r"[^.!?…\n]+(?:[.!?…]+|(?=\n)|$)")
_PARA = re.compile(r"(?:[^\n]|\n(?!\s*\n))+")


def _blank(text: str, pattern: re.Pattern[str]) -> str:
    return pattern.sub(lambda m: " " * len(m.group(0)), text)


def _stem(word: str) -> str:
    low = word.lower()
    if len(word) <= 4:
        return word
    if re.search(r"(?:ый|ий|ой|ая|яя|ое|ее|ые|ие|ых|их)$", low):
        return word[:-2]
    if re.search(r"(?:ок|ек)$", low):
        return word[:-2]
    if low[-1] in "аеёиоуыэюяьй":
        return word[:-1]
    return word


def _name_pattern(name: str) -> re.Pattern[str]:
    parts = re.split(r"(\s+|-)", name)
    out = []
    for part in parts:
        if not part:
            continue
        if part.isspace():
            out.append(r"\s+")
        elif part == "-":
            out.append(r"\s*-\s*")
        else:
            stem = re.escape(_stem(part)).replace("е", "[её]")
            out.append(stem + rf"{_W}*")
    return re.compile(rf"(?<!{_W})" + "".join(out) + rf"(?!{_W})")


class Lexicon:
    """Имена существ -> типы и уровень; встроенный словарь + досье."""

    def __init__(self, dossier: dict | list | None = None):
        minions: dict[str, tuple[tuple[str, ...], int | None]] = dict(BUILTIN_MINIONS)
        for card in _dossier_cards(dossier):
            name = card.get("name_ru") or card.get("name")
            if not name or (card.get("type") not in (None, "MINION")):
                continue
            races = tuple(r for r in (card.get("races") or []) if r)
            minions[name] = (races, card.get("techLevel"))
        self.minions = minions
        self.patterns: list[tuple[re.Pattern[str], str]] = []
        for name in sorted(minions, key=len, reverse=True):
            self.patterns.append((_name_pattern(name), name))
        for alias, canonical in ALIASES.items():
            if canonical in minions:
                self.patterns.append((_name_pattern(alias), canonical))

    def mentions(self, text: str) -> list[tuple[int, int, str]]:
        found: list[tuple[int, int, str]] = []
        for pattern, name in self.patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                if any(start < b and end > a for a, b, _ in found):
                    continue
                found.append((start, end, name))
        return sorted(found)

    def races(self, name: str) -> tuple[str, ...]:
        return self.minions.get(name, ((), None))[0]

    def tier(self, name: str) -> int | None:
        return self.minions.get(name, ((), None))[1]


def _dossier_cards(dossier: dict | list | None) -> list[dict]:
    if not dossier:
        return []
    cards = dossier.get("cards", []) if isinstance(dossier, dict) else dossier
    result: list[dict] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        result.append(card)
        result.extend(n for n in card.get("synergy_neighbors", []) if isinstance(n, dict))
    return result


def _spans(pattern: re.Pattern[str], text: str) -> list[tuple[int, int]]:
    return [m.span() for m in pattern.finditer(text) if m.group(0).strip()]


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _finding(text: str, code: str, severity: str, message: str, start: int, end: int,
             suggestion: str = "", **meta) -> dict:
    result = {
        "id": code,
        "analyzer": ANALYZER,
        "category": "bg-mechanics",
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


def _lobby_types(words: str) -> list[str]:
    types: list[str] = []
    for word in re.findall(rf"{_W}+", words):
        for pattern, race in TYPE_WORDS:
            if pattern.search(word) and race not in types:
                types.append(race)
    return types


def check_bg_mechanics(
    text: str,
    *,
    dossier: dict | list | None = None,
    expect_shortcodes: bool | None = None,
) -> list[dict]:
    """Проверить текст о БГ; вернуть находки, отсортированные по позиции."""
    findings: list[dict] = []
    lexicon = Lexicon(dossier)
    # Теги шорткодов заменяем пробелами: смещения сохраняются, имя внутри видно.
    plain = _blank(text, SHORTCODE_TAG)
    paragraphs = _spans(_PARA, plain)

    # 1. «племя» вне прямых цитат.
    unquoted = _blank(plain, QUOTED)
    for match in TRIBE_WORD.finditer(unquoted):
        findings.append(_finding(
            text, "bg.forbidden_tribe_word", "error",
            "В текстах о Полях сражений не пишем «племя»: используйте «тип существ».",
            *match.span(), suggestion="тип существ",
        ))

    for p_index, (p_start, p_end) in enumerate(paragraphs):
        paragraph = plain[p_start:p_end]
        sentences = [(p_start + a, p_start + b) for a, b in _spans(_SENTENCE, paragraph)]
        para_mentions = lexicon.mentions(paragraph)
        has_economy = bool(ECONOMY.search(paragraph))

        for s_start, s_end in sentences:
            sentence = plain[s_start:s_end]
            mentions = lexicon.mentions(sentence)

            # 2. Тавтология лобби.
            for match in LOBBY.finditer(sentence):
                lobby_types = _lobby_types(match.group(1))
                if not lobby_types:
                    continue
                culprit = None
                if mentions:
                    for _, _, name in mentions:
                        races = lexicon.races(name)
                        if len(races) == 1 and races[0] in lobby_types:
                            culprit = name
                            break
                else:
                    context = para_mentions
                    if not context:
                        for prev in range(p_index - 1, -1, -1):
                            prev_text = plain[paragraphs[prev][0]:paragraphs[prev][1]]
                            if prev_text.lstrip().startswith("#"):
                                context = lexicon.mentions(prev_text)
                                break
                    known = [n for _, _, n in context if lexicon.races(n)]
                    if known and all(
                        len(lexicon.races(n)) == 1 and lexicon.races(n)[0] in lobby_types for n in known
                    ):
                        culprit = known[0]
                if culprit:
                    race = lexicon.races(culprit)[0]
                    findings.append(_finding(
                        text, "bg.lobby_tautology", "error",
                        f"«{culprit}» — существо одного типа ({TYPE_RU.get(race, race)}): "
                        "без этого типа в лобби оно вообще не появляется в таверне, "
                        "условие «в лобби с …» ничего не сообщает.",
                        s_start + match.start(), s_start + match.end(),
                        suggestion="убрать условие лобби или назвать реальное ограничение",
                        card=culprit,
                    ))

            # 3. Боевой клич «копится» в руке.
            if HAND.search(sentence) and LUCKY.search(sentence) and HOLD.search(sentence):
                findings.append(_finding(
                    text, "bg.battlecry_in_hand", "error",
                    "Боевой клич срабатывает при розыгрыше: в руке существо ещё не получило "
                    "свойство, отбирать «удачных» до розыгрыша нельзя.",
                    s_start, s_end,
                    suggestion="описать решение после розыгрыша (оставить/продать)",
                ))

            # 4. Кривая 2-го хода.
            turn2 = TURN2.search(sentence)
            if turn2 and ACQUIRE.search(sentence) and not has_economy:
                tier2 = [n for _, _, n in mentions if (lexicon.tier(n) or 0) >= 2]
                reason = None
                if tier2:
                    reason = f"«{tier2[0]}» — существо {lexicon.tier(tier2[0])}-го уровня таверны"
                elif TIER2_WORDS.search(sentence):
                    reason = "существо 2-го уровня таверны"
                elif SPELL_WORD.search(sentence) or any(
                    n == "Зловещая пророчица" for _, _, n in mentions
                ) or any(re.search(p, sentence) for _, p in POOL_SPELLS.values()):
                    reason = "покупка заклинания таверны"
                if reason:
                    findings.append(_finding(
                        text, "bg.turn2_curve", "error",
                        f"{reason} на 2-м ходу без источника золота на 1-м ходу: "
                        "на 2-м ходу 3 золотых и таверна 1-го уровня.",
                        s_start, s_end,
                        suggestion="назвать источник экономики на 1-м ходу или сдвинуть ход",
                    ))
            gold = TURN2_GOLD.search(sentence)
            if gold and not has_economy:
                findings.append(_finding(
                    text, "bg.turn2_curve", "error",
                    "«Лишнее золото на 2-м ходу» без источника на 1-м ходу "
                    "(Музыкант, Монетка, Зоатроид, сила героя, аномалия).",
                    s_start + gold.start(), s_start + gold.end(),
                    suggestion="назвать источник золота",
                ))

            # 5. Щупальце Зоатроида на столе.
            if TENTACLE.search(sentence) and ON_BOARD.search(sentence) and (
                re.search(r"Зоатроид|Zoatroid", paragraph, re.I) or re.search(r"продаж|прода", sentence, re.I)
            ):
                findings.append(_finding(
                    text, "bg.token_zone_mismatch", "error",
                    "При продаже Зоатроида щупальце 0/2 с Провокацией кладётся в руку, "
                    "а не остаётся и не призывается на стол.",
                    s_start, s_end, suggestion="«получаете в руку щупальце 0/2 с Провокацией»",
                ))

            # 6. «Бесплатное золото» от лев-рыбы и нетопыря.
            free = FREE_GOLD.search(sentence)
            if free and LIONFISH_CONTEXT.search(paragraph) and not REAL_COST.search(paragraph):
                findings.append(_finding(
                    text, "bg.false_free_gold", "error",
                    "Связка не даёт бесплатного золота: Активация лев-рыбы стоит 2 золотых, "
                    "нетопырь-добытчик продаётся за 1; выгода — +5/+5 от Наживки.",
                    s_start + free.start(), s_start + free.end(),
                    suggestion="написать про +5/+5 от Наживки и цену 2 золотых",
                ))

    # 7. Заклинания таверны без шорткода.
    if expect_shortcodes is None:
        expect_shortcodes = "[hs_bg" in text
    if expect_shortcodes:
        bare = _blank(text, SHORTCODE_FULL)
        for card_id, (name, pattern) in POOL_SPELLS.items():
            for match in re.finditer(rf"(?<!{_W}){pattern}(?!{_W})", bare):
                findings.append(_finding(
                    text, "bg.unlinked_pool_spell", "warning",
                    f"Заклинание таверны «{name}» без подсветки.",
                    *match.span(), suggestion=f'[hs_bg id="{card_id}"]{match.group(0)}[/hs_bg]',
                    card_id=card_id,
                ))

    findings.sort(key=lambda f: (f["start"], f["id"]))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m editorteam.bg_mechanics_gate",
        description="Проверка игровой физики Полей сражений в русском тексте (без LLM).",
    )
    parser.add_argument("file", help="файл статьи (Markdown/TXT)")
    parser.add_argument("--dossier", help="JSON досье из editorteam.bg_dossier")
    parser.add_argument("--expect-shortcodes", action="store_true",
                        help="требовать шорткоды [hs_bg] у заклинаний таверны")
    args = parser.parse_args(argv)
    text = Path(args.file).read_text(encoding="utf-8")
    dossier = json.loads(Path(args.dossier).read_text(encoding="utf-8")) if args.dossier else None
    findings = check_bg_mechanics(
        text, dossier=dossier, expect_shortcodes=True if args.expect_shortcodes else None
    )
    sys.stdout.write(json.dumps(findings, ensure_ascii=False, indent=2) + "\n")
    return 1 if any(f["severity"] == "error" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
