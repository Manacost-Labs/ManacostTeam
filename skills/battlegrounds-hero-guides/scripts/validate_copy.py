"""Mechanical checks for a link-free, copy-ready Battlegrounds hero guide."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


FIELDS = ("Сила", "Сложность", "Бан типов существ", "Стартовая кривая")
LINK_OR_CITATION = re.compile(
    r"https?://|www\.|\]\([^)]*\)|\[\^\d+\]|\[cite[:\]]|cite",
    re.IGNORECASE,
)
NON_PREFERRED_TERMS = {
    "подарок вместо тёмного дара": re.compile(r"\bподар(?:ок|к[а-яё]*)\b", re.IGNORECASE),
    "доска вместо стола": re.compile(r"\bдоск\w*\b", re.IGNORECASE),
    "магазин вместо таверны": re.compile(r"\bмагазин\w*\b", re.IGNORECASE),
}


def validate(source: str) -> list[str]:
    issues: list[str] = []
    if LINK_OR_CITATION.search(source):
        issues.append("В тексте есть ссылка или маркер цитирования.")
    for label, pattern in NON_PREFERRED_TERMS.items():
        if pattern.search(source):
            issues.append(f"Нежелательный термин: {label}.")

    sections = re.split(r"(?=^###\s+\S)", source, flags=re.MULTILINE)
    if sections[0].strip():
        issues.append("Перед первым заголовком героя есть лишний текст.")
    heroes = [section for section in sections[1:] if section.strip()]
    if not heroes:
        return issues + ["Не найдено ни одного заголовка героя уровня ###."]

    names: set[str] = set()
    for section in heroes:
        lines = section.splitlines()
        name = lines[0].removeprefix("###").strip()
        if name in names:
            issues.append(f"Повторяется герой: {name}.")
        names.add(name)
        for field in FIELDS:
            matches = re.findall(rf"^\*\*{re.escape(field)}:\*\*[ \t]*[^\s\r\n].*$", section, re.MULTILINE)
            if len(matches) != 1:
                issues.append(f"{name}: поле «{field}» должно встретиться ровно один раз.")
        body = re.sub(r"^\*\*[^\n]*\n?", "", "\n".join(lines[1:]), flags=re.MULTILINE)
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
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
    print("OK: структура, терминология и отсутствие ссылок проверены; игровые факты требуют ручной проверки.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
