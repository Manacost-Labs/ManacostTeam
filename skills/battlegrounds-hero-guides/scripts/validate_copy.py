"""Mechanical checks for a link-free, copy-ready Battlegrounds hero guide."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


FIELDS = ("Сила", "Сложность", "Бан типов существ", "Стартовая кривая")
RATING_FIELDS = ("Сила", "Сложность")
RATING_VALUE = re.compile(r"[1-5] из 5(?:, оценка редакции)?")
LINK_OR_CITATION = re.compile(
    r"https?://|www\.|\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b|"
    r"\]\([^)]*\)|\[\^\d+\]|\[cite[:\]]|cite|【\d+†",
    re.IGNORECASE,
)
NON_PREFERRED_TERMS = {
    "доска вместо стола": re.compile(r"\bдоск\w*\b", re.IGNORECASE),
    "магазин вместо таверны": re.compile(r"\bмагазин\w*\b", re.IGNORECASE),
}
GIFT_NOUN = re.compile(r"\bподар(?:ок|к[а-яё]*)\b", re.IGNORECASE)
DARK_GIFT_CONTEXT = re.compile(
    r"\bт[её]мн\w*[ \t]+(?:дар\w*|подар\w*)\b|\bDark Gifts?\b|\bКсавий\b",
    re.IGNORECASE,
)


def validate(source: str) -> list[str]:
    issues: list[str] = []
    if LINK_OR_CITATION.search(source):
        issues.append("В тексте есть ссылка или маркер цитирования.")
    for label, pattern in NON_PREFERRED_TERMS.items():
        if pattern.search(source):
            issues.append(f"Нежелательный термин: {label}.")

    sections = re.split(r"(?=^###[ \t]+\S[^\r\n]*$)", source, flags=re.MULTILINE)
    if sections[0].strip():
        issues.append("Перед первым заголовком героя есть лишний текст.")
    heroes = [section for section in sections[1:] if section.strip()]
    if not heroes:
        return issues + ["Не найдено ни одного заголовка героя уровня ###."]

    names: set[str] = set()
    for section in heroes:
        lines = section.splitlines()
        name = lines[0].removeprefix("###").strip()
        if DARK_GIFT_CONTEXT.search(section) and GIFT_NOUN.search(section):
            issues.append(f"{name}: нежелательный термин — подарок вместо тёмного дара.")
        if name in names:
            issues.append(f"Повторяется герой: {name}.")
        names.add(name)
        for field in FIELDS:
            matches = re.findall(rf"^\*\*{re.escape(field)}:\*\*[ \t]*[^\s\r\n].*$", section, re.MULTILINE)
            if len(matches) != 1:
                issues.append(f"{name}: поле «{field}» должно встретиться ровно один раз.")
            elif field in RATING_FIELDS:
                value = matches[0].split("**", 2)[-1].strip()
                if not RATING_VALUE.fullmatch(value):
                    issues.append(f"{name}: «{field}» должна быть целым числом от 1 до 5 в формате «N из 5».")
        nonblank = [(index, line.strip()) for index, line in enumerate(lines[1:], 1) if line.strip()]
        for position, field in enumerate(FIELDS):
            if position >= len(nonblank) or not re.fullmatch(
                rf"\*\*{re.escape(field)}:\*\*[ \t]*\S.*", nonblank[position][1]
            ):
                issues.append(f"{name}: поле «{field}» должно стоять в начале на позиции {position + 1}.")
        body = "\n".join(lines[nonblank[3][0] + 1 :]) if len(nonblank) >= 4 else ""
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", body)
            if paragraph.strip()
            and not re.match(r"^(?:#{1,6}|[-*])[ \t]", paragraph.strip())
            and len(re.findall(r"\w+", paragraph)) >= 5
        ]
        if len(paragraphs) < 2:
            issues.append(f"{name}: нужно хотя бы два игровых абзаца.")
    return issues


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("copy_ready", type=Path)
    args = parser.parse_args()
    issues = validate(args.copy_ready.read_text(encoding="utf-8"))
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        return 1
    print("OK: структура, диапазон оценок, терминология и отсутствие ссылок проверены; игровые факты требуют ручной проверки.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
