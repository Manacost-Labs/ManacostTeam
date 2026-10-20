"""Mechanical checks for a copy-ready guide and its decision review."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
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
REVIEW_PHASES = {"early", "mid", "fallback"}


def hero_sections(source: str) -> dict[str, str]:
    sections = re.split(r"(?=^###[ \t]+\S[^\r\n]*$)", source, flags=re.MULTILINE)
    return {
        section.splitlines()[0].removeprefix("###").strip(): section
        for section in sections[1:]
        if section.strip()
    }


def field_value(section: str, field: str) -> str | None:
    match = re.search(rf"^\*\*{re.escape(field)}:\*\*[ \t]*(.+)$", section, re.MULTILINE)
    return match.group(1).strip() if match else None


def normalized(value: str) -> str:
    return " ".join(value.split())


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


def validate_review(source: str, review: object) -> list[str]:
    """Check that a human decision review covers and quotes the actual guide."""
    issues: list[str] = []
    if not isinstance(review, dict):
        return ["Журнал игровых развилок должен быть объектом JSON."]
    if type(review.get("schema_version")) is not int or review["schema_version"] != 1:
        issues.append("Журнал игровых развилок: schema_version должен быть 1.")
    if review.get("mode") not in ("solo", "duos"):
        issues.append("Журнал игровых развилок: mode должен быть solo или duos.")
    if not isinstance(review.get("patch"), str) or not review["patch"].strip():
        issues.append("Журнал игровых развилок: укажи проверенный patch.")
    try:
        date.fromisoformat(review.get("checked_on", ""))
    except (TypeError, ValueError):
        issues.append("Журнал игровых развилок: checked_on должен быть датой YYYY-MM-DD.")

    entries = review.get("heroes")
    if not isinstance(entries, list):
        return issues + ["Журнал игровых развилок: heroes должен быть списком."]
    sections = hero_sections(source)
    reviewed_names: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            issues.append("Журнал игровых развилок: у каждого героя должно быть имя.")
            continue
        name = entry["name"].strip()
        reviewed_names.append(name)
        section = sections.get(name)
        if section is None:
            issues.append(f"{name}: героя нет в тексте гайда.")
            continue
        for field, key in (("Сила", "strength"), ("Сложность", "difficulty")):
            score = entry.get(key)
            value = field_value(section, field)
            if type(score) is not int or score not in range(1, 6):
                issues.append(f"{name}: {key} должен быть целым числом от 1 до 5.")
            elif value is None or not value.startswith(f"{score} из 5"):
                issues.append(f"{name}: {key} не совпадает с полем «{field}» в гайде.")
        if entry.get("confidence") not in ("high", "medium", "low"):
            issues.append(f"{name}: confidence должен быть high, medium или low.")
        if "оценка редакции" not in (field_value(section, "Сила") or ""):
            issues.append(f"{name}: редакционная оценка силы должна быть помечена в готовом тексте.")

        body_start = re.search(r"^\*\*Стартовая кривая:\*\*.*$", section, re.MULTILINE)
        body = section[body_start.end() :] if body_start else ""
        probes = entry.get("probes")
        if not isinstance(probes, list):
            issues.append(f"{name}: probes должен быть списком из трёх игровых развилок.")
            continue
        phases: list[str] = []
        anchors: list[str] = []
        for probe in probes:
            if not isinstance(probe, dict):
                issues.append(f"{name}: игровая развилка должна быть объектом.")
                continue
            phase = probe.get("phase")
            phases.append(phase if isinstance(phase, str) else "")
            label = f"{name}/{phase}"
            for key in ("state", "decision", "reason", "source_note"):
                value = probe.get(key)
                if not isinstance(value, str) or len(value.strip()) < 15:
                    issues.append(f"{label}: поле {key} должно содержать конкретное объяснение.")
            options = probe.get("options")
            if not isinstance(options, list) or len(options) != 2 or any(
                not isinstance(option, str) or len(option.strip()) < 10 for option in options
            ) or options[0].strip() == options[1].strip():
                issues.append(f"{label}: нужны два разных возможных действия.")
            elif probe.get("decision") not in options:
                issues.append(f"{label}: decision должен совпадать с одним из двух действий.")
            anchor = probe.get("guide_quote")
            if not isinstance(anchor, str) or len(anchor.strip()) < 25:
                issues.append(f"{label}: нужна содержательная цитата из гайда.")
            elif normalized(anchor) not in normalized(body):
                issues.append(f"{label}: цитата не найдена в тексте этого героя.")
            else:
                anchors.append(normalized(anchor))
        if set(phases) != REVIEW_PHASES or len(phases) != len(REVIEW_PHASES):
            issues.append(f"{name}: нужны разные развилки early, mid и fallback.")
        if len(anchors) != len(set(anchors)):
            issues.append(f"{name}: разные развилки не могут опираться на одну цитату.")
    if len(reviewed_names) != len(set(reviewed_names)):
        issues.append("В журнале игровых развилок повторяется герой.")
    if set(reviewed_names) != set(sections):
        issues.append("Журнал игровых развилок должен охватывать ровно героев гайда.")
    return issues


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("copy_ready", type=Path)
    parser.add_argument("--review", type=Path, help="JSON с проверенными игровыми развилками")
    args = parser.parse_args()
    source = args.copy_ready.read_text(encoding="utf-8")
    issues = validate(source)
    if args.review:
        try:
            review = json.loads(args.review.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            issues.append(f"Не удалось прочитать журнал игровых развилок: {error}.")
        else:
            issues.extend(validate_review(source, review))
    if issues:
        for issue in issues:
            print(f"ERROR: {issue}", file=sys.stderr)
        return 1
    checked = " и привязка игровых развилок" if args.review else ""
    print(f"OK: структура, оценки, терминология{checked} проверены; факты и качество решений требуют ручной проверки.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
