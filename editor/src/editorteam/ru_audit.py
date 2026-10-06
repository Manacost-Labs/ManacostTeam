"""Второй, только читающий аудитор: ru-text (ru-score, ru-check) и проверка его отчёта.

ru-text (talkstream/ru-text, MIT) — каталог правил русского текста: оценка 0–10 по
пяти шкалам и признаки машинного текста AD-1…AD-N. Корпус и процедуры лежат в
`references/ru-text/` по закреплённому коммиту (`SOURCE.json`). Основной навык
ru-text сюда не вложен: он молча правит типографику любого русского текста, а
издание защищает авторский голос.

Сам аудит — работа модели: в Claude Code это агент только с Read/Grep/Glob, в другом
клиенте — отдельный сеанс без инструментов записи. Код проверяет то, что проверяется
без модели:

    prepare   хеш текста до аудита, пути корпуса и готовое задание аудитору
    validate  отчёт устроен по scoring.md, арифметика сходится, цитаты есть в тексте,
              правила AD-N существуют, текст не изменился

Отчёт — второе мнение, а не правка: ничего из него не применяется автоматически.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path

from editorteam import rules

ROOT = Path(__file__).resolve().parents[2]
_SKILL = ROOT / ".claude" / "skills" / "hs-edit"
CORPUS = (_SKILL if _SKILL.exists() else ROOT) / "references" / "ru-text"

# Шкалы, веса и ярлыки — из references/scoring.md.
DIMENSIONS = (
    ("Типографика", 0.15),
    ("Чистота языка", 0.25),
    ("Грамотность", 0.20),
    ("Структура", 0.20),
    ("Точность для читателя", 0.20),
)
LABELS = (
    (9.0, "Эталонный"),
    (7.0, "Хороший"),
    (5.0, "Средний"),
    (3.0, "Слабый"),
    (0.0, "Критический"),
)
MODES = ("score", "check")
SHORT_TEXT_WORDS = 50
MAX_QUOTE = 125

_NUMBER = r"(\d+(?:[.,]\d+)?)"
_HEADER = re.compile(rf"^#{{1,6}}\s*Оценка:\s*\**{_NUMBER}\s*/\s*10\**\s*[—–-]\s*(.+?)\s*$", re.M)
_FORMULA = re.compile(rf"Формула.*?=\s*{_NUMBER}", re.I)
_NOT_MEASURED = re.compile(r"^#{2,4}\s*Что оценка не измеряет", re.M | re.I)
_FLOOR = re.compile(r"ярлык\s+ограничен", re.I)
_AD = re.compile(r"\bAD-(\d{1,3})\b")
_QUOTES = (
    re.compile(r"«([^»\n]+)»"),
    re.compile(r'"([^"\n]+)"'),
    re.compile(r"`([^`\n]+)`"),
)
_RULE_ID = re.compile(r"^[A-Za-zА-Яа-я]{1,3}-?\d+[\w.\-]*$")
_ELLIPSIS = re.compile(r"…|\.{3}")
_ARROW = re.compile(r"→|=>|⟶")
_DASHES = str.maketrans({"—": "-", "–": "-", "−": "-"})
_STRIP = str.maketrans("", "", "«»„“”\"'’*_`")


class AuditUnavailable(RuntimeError):
    """Корпус ru-text не найден: аудит без него — это ответ по памяти."""


@dataclass
class AuditCheck:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    total: float | None = None
    expected_total: float | None = None
    label: str | None = None
    quotes_checked: int = 0
    quotes_missing: list[str] = field(default_factory=list)
    quotes_from_catalog: list[str] = field(default_factory=list)
    ad_rules: list[int] = field(default_factory=list)
    text_sha256: str = ""
    readonly: str = "unchecked"

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "schema_version": "1.0",
            "valid": self.valid,
            "total": self.total,
            "expected_total": self.expected_total,
            "label": self.label,
            "scores": self.scores,
            "ad_rules": self.ad_rules,
            "quotes": {
                "checked": self.quotes_checked,
                "missing": self.quotes_missing,
                "from_catalog": self.quotes_from_catalog,
            },
            "text_sha256": self.text_sha256,
            "readonly": self.readonly,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def sha256_of(path: Path) -> str:
    """Хеш текста с переводами строк LF: файл с CRLF и тот же файл с LF — один текст."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def known_rules() -> set[int]:
    """Номера правил AD-N из вложенного addenda.md."""
    addenda = CORPUS / "references" / "addenda.md"
    if not addenda.exists():
        raise AuditUnavailable(f"нет корпуса ru-text: {addenda}")
    text = addenda.read_text(encoding="utf-8")
    return {int(number) for number in re.findall(r"^## AD-(\d+)\.", text, re.M)}


def weighted_total(scores: dict[str, float]) -> float:
    """Взвешенная сумма шкал, округление до десятых «от нуля» (Decimal, без ошибок float)."""
    total = sum(Decimal(str(scores[name])) * Decimal(str(weight)) for name, weight in DIMENSIONS)
    return float(total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def expected_total(scores: dict[str, float]) -> float:
    """Итог по шкалам: взвешенная сумма и непокрываемые пороги из scoring.md."""
    total = weighted_total(scores)
    caps = []
    if any(score < 3.0 for score in scores.values()):
        caps.append(5.0)
    if scores["Типографика"] < 4.0 or scores["Грамотность"] < 4.0:
        caps.append(7.0)
    return min([total, *caps])


def label_for(total: float) -> str:
    return next(label for floor, label in LABELS if total >= floor)


def _number(raw: str) -> float:
    return float(raw.replace(",", "."))


def _fold(text: str) -> str:
    """Текст для сравнения цитат: без регистра, ё, кавычек, разметки и неразрывных пробелов."""
    text = unicodedata.normalize("NFC", text).lower().replace("ё", "е")
    text = text.translate(_DASHES).translate(_STRIP)
    return " ".join(text.split())


def quoted_fragments(remarks: str) -> list[str]:
    """Дословные цитаты из замечаний: куски текста, а не ярлыки правил и не замены.

    Всё после стрелки («→», «=>») — предложение аудитора, в тексте его нет.
    """
    found: list[str] = []
    for line in remarks.splitlines():
        line = _ARROW.split(line, maxsplit=1)[0]
        for pattern in _QUOTES:
            for match in pattern.finditer(line):
                fragment = match.group(1).strip()
                if (
                    len(fragment) < 3
                    or len(fragment) > MAX_QUOTE
                    or _RULE_ID.match(fragment)
                    or not re.search(r"[^\W\d_]", fragment)
                ):
                    continue
                found.append(fragment)
    return found


@lru_cache(maxsize=1)
def _catalog() -> str:
    """Весь корпус правил ru-text одним сложенным текстом: в нём примеры и ключевые слова."""
    files = sorted((CORPUS / "references").glob("*.md"))
    return _fold("\n".join(path.read_text(encoding="utf-8") for path in files))


def classify_quotes(fragments: list[str], text: str) -> tuple[list[str], list[str]]:
    """Цитаты, которых нет в тексте, и те из них, что взяты из каталога правил.

    Аудитор ссылается на правило словом или примером из корпуса («„надёжный“, „весьма
    существенно“»): это не цитата текста, и выдумкой оно не является. Выдумка — то, чего
    нет ни в тексте, ни в корпусе.
    """
    folded = _fold(text)
    missing: list[str] = []
    from_catalog: list[str] = []
    for fragment in fragments:
        parts = [_fold(part) for part in _ELLIPSIS.split(fragment)]
        absent = [part for part in parts if len(part) >= 4 and part not in folded]
        if not absent:
            continue
        if all(part in _catalog() for part in absent):
            from_catalog.append(fragment)
        else:
            missing.append(fragment)
    return missing, from_catalog


def validate_report(
    report: str,
    text: str,
    *,
    mode: str = "score",
    expected_sha256: str | None = None,
    text_sha256: str = "",
) -> AuditCheck:
    """Проверить отчёт аудитора. Ошибка — отчёту нельзя доверять и аудит надо повторить."""
    check = AuditCheck(text_sha256=text_sha256)
    remarks_all: list[str] = []

    if mode == "score":
        _check_score(report, text, check, remarks_all)
    else:
        remarks_all.append(report)

    fragments = quoted_fragments("\n".join(remarks_all))
    check.quotes_checked = len(fragments)
    check.quotes_missing, check.quotes_from_catalog = classify_quotes(fragments, text)
    for fragment in check.quotes_missing:
        check.errors.append(f"цитаты нет в тексте, возможна выдумка: «{fragment}»")

    known = known_rules()
    check.ad_rules = sorted({int(number) for number in _AD.findall(report)})
    for number in check.ad_rules:
        if number not in known:
            check.warnings.append(f"правила AD-{number} нет в корпусе ru-text {max(known)} правил")

    if expected_sha256 is not None and text_sha256:
        if expected_sha256.lower() == text_sha256:
            check.readonly = "verified"
        else:
            check.readonly = "violated"
            check.errors.append("текст изменился после prepare: аудитор обязан только читать")
    return check


def _check_score(report: str, text: str, check: AuditCheck, remarks_all: list[str]) -> None:
    header = _HEADER.search(report)
    if header is None:
        check.errors.append("нет заголовка «## Оценка: X.X / 10 — Ярлык» из scoring.md")
    else:
        check.total = _number(header.group(1))
        check.label = header.group(2).strip(" []*«»")

    for name, _ in DIMENSIONS:
        row = re.search(
            rf"^\|\s*\**{re.escape(name)}\**\s*\|\s*\**{_NUMBER}\**\s*(?:/\s*10)?\s*\|(.*)$",
            report,
            re.M | re.I,
        )
        if row is None:
            check.errors.append(f"нет строки шкалы «{name}» с баллом")
            continue
        score = _number(row.group(1))
        if not 0.0 <= score <= 10.0:
            check.errors.append(f"балл «{name}» вне 0–10: {score}")
        check.scores[name] = score
        remarks_all.append(row.group(2))

    if not _NOT_MEASURED.search(report):
        check.errors.append("нет раздела «Что оценка не измеряет»")
    if len(text.split()) < SHORT_TEXT_WORDS and "короткий" not in report.lower():
        check.warnings.append("текст короче 50 слов, а оговорки о ненадёжной оценке нет")

    if len(check.scores) == len(DIMENSIONS) and check.total is not None:
        check.expected_total = expected_total(check.scores)
        if abs(check.total - check.expected_total) > 0.05:
            check.errors.append(
                f"итог {check.total} не сходится с формулой: по шкалам выходит "
                f"{check.expected_total}"
            )
        formula = _FORMULA.search(report)
        if formula is not None:
            shown = _number(formula.group(1))
            raw = weighted_total(check.scores)
            if abs(shown - raw) > 0.05 and abs(shown - check.expected_total) > 0.05:
                check.errors.append(f"строка «Формула» даёт {shown}, по шкалам выходит {raw}")
        _check_label(report, check)


def _check_label(report: str, check: AuditCheck) -> None:
    """Ярлык соответствует баллу; при AD-14/AD-15 он может быть ограничен до «Средний»."""
    order = [label for _, label in LABELS]
    band = label_for(check.total)
    shown = (check.label or "").casefold()
    reported = next((label for label in order if shown.startswith(label.casefold())), None)
    if reported is None:
        check.errors.append(f"неизвестный ярлык «{check.label}»")
        return
    middle = order.index("Средний")
    capped = (
        _FLOOR.search(report) is not None
        and order.index(reported) >= middle
        and order.index(band) < middle
    )
    if reported != band and not capped:
        check.errors.append(f"ярлык «{reported}» не соответствует баллу {check.total}: «{band}»")


def house_overrides(decisions: dict | None = None) -> list[str]:
    """Решения издания, которые важнее типографики и стиля ru-text."""
    typography = rules.typography() if decisions is None else decisions
    notes: list[str] = []
    if (typography.get("quotes") or {}).get("decision") == "straight":
        notes.append('прямые кавычки " — решение издания; «ёлочки» не предлагать')
    if ((typography.get("numbers") or {}).get("range") or {}).get("decision") == "hyphen":
        notes.append("диапазоны через дефис, «2-3 маны»; среднее тире в диапазонах не предлагать")
    if (typography.get("yo") or {}).get("decision") == "remove":
        notes.append("буква ё не ставится («ее», «еще»); исключение — официальные названия карт")
    if (typography.get("archetype_hyphen") or {}).get("decision") == "space":
        notes.append("архетипы пишутся без дефиса и с заглавными: «Квест Маг», «агро колода»")
    dashes = typography.get("dashes") or {}
    if dashes.get("primary") == "—":
        em = (dashes.get("corpus") or {}).get("em")
        notes.append(
            "длинное тире — основной знак издания"
            + (f" ({em} на корпусе автора)" if em else "")
            + "; AD-1 засчитывать только за частоту выше нормы автора"
        )
    notes.append("многоточие из трёх точек и короткие фразы — авторский голос, не AD-2 и не ошибка")
    notes.append("неразрывные пробелы ставит отдельная стадия после аудита; их нет — не замечание")
    notes.append(
        "названия карт, классов, режимов и числа не обсуждаются: «как в игре» и «как у автора»"
    )
    return notes


def prepare(path: Path, mode: str = "score") -> dict:
    """Всё, что нужно перед аудитом: хеш текста, корпус и задание аудитору."""
    if mode not in MODES:
        raise ValueError(f"mode должен быть из {MODES}")
    text_path = path.resolve()
    known = known_rules()
    procedure = CORPUS / f"ru-{mode}.procedure.md"
    if not procedure.exists():
        raise AuditUnavailable(f"нет процедуры ru-text: {procedure}")
    digest = sha256_of(text_path)
    overrides = house_overrides()
    references = CORPUS / "references"
    if mode == "score":
        report_format = f"раздел «Output format» в {references / 'scoring.md'}, дословно"
    else:
        report_format = "раздел «Output format» процедуры: находки с правилом и серьёзностью"
    prompt = "\n".join(
        [
            "Ты — независимый аудитор русского текста. Работаешь только на чтение.",
            "",
            "1. Не записывай, не правь и не перемещай файлы и не запускай команды: доступны "
            "только Read, Grep, Glob. Исправленный текст не нужен, нужен отчёт.",
            f"2. Следуй процедуре {procedure}. Правила читай из {references}, не по памяти; "
            "если папку не нашёл, так и скажи и остановись.",
            f"3. Аудируемый текст: {text_path} (SHA-256 {digest}). Прочитай его целиком.",
            f"4. Формат отчёта — {report_format}.",
            "5. Цитируй только то, что в тексте есть, дословно, до 125 знаков. Не выдумывай "
            f"цитаты и номера правил: у каждого замечания цитата и правило из корпуса "
            f"(AD-1…AD-{max(known)}).",
            "6. Решения издания важнее типографики и стиля ru-text. Это не ошибки:",
            *[f"   - {note}" for note in overrides],
            "7. Ты сверяешь текст с нормами ru-text. Факты, смысл, авторский голос и названия "
            "карт не твоя забота; своё мнение о том, как переписать абзац, не навязывай.",
        ]
    )
    return {
        "schema_version": "1.0",
        "mode": mode,
        "text": str(text_path),
        "text_sha256": digest,
        "words": len(text_path.read_text(encoding="utf-8").split()),
        "corpus": str(CORPUS),
        "procedure": str(procedure),
        "house_overrides": overrides,
        "prompt": prompt,
    }
