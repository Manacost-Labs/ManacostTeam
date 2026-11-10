"""Оценка аудита на реальных отклонениях владельца.

Набор — папка с `labels.json`, `versions/` и `gold/` (формат —
editor/docs/OWNER_EVAL.md). Для каждого отклонения берётся версия ДО
исправления, по ней прогоняется детерминированный `audit`, и проверяется,
помечен ли дословный фрагмент находкой подходящего анализатора. Отдельно
считаются срабатывания новых проверок на эталонах и принятой версии:
это ложные тревоги, если владелец к тексту претензий не имел.

Категории, которые без модели не ловятся (слабый совет, нелогичное
сравнение, жанр и длина, непонятный частный случай), получают статус
`needs_reviewer`, даже если какая-то находка случайно задела фрагмент.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

# Какие находки считаются попаданием в категорию отклонения.
DETERMINISTIC = {
    "card_text_retelling": ("card_paraphrase.retelling",),
    "card_text_retelling_and_duplication": (
        "card_paraphrase.retelling",
        "owner.section_repeat",
    ),
    "duplication": ("owner.section_repeat",),
    "overused_word": ("owner.overused_word", "owner.forbidden_literal"),
    "forbidden_word": ("owner.forbidden_literal",),
}

# Почему категория остаётся рецензенту: это записывается в отчёт.
NEEDS_REVIEWER = {
    "card_text_retelling": "пересказ эффекта без нового решения; детерминированный поиск неполон",
    "obvious_or_water": "нужна оценка пользы предложения для выбранного читателя",
    "duplicated_advice": "нужно отличить пустой повтор от полезного нового условия",
    "source_attribution_in_body": "происхождение хранится в рабочих материалах; проверь необходимость имени игрока",
    "genre_fit": "объём и манера сравниваются с выбранными образцами author-context, не с общей нормой слов",
    "ai_tells": "рамки «Подвох:», «И железное правило:» — вопрос интонации; "
    "markers ловит только шаблоны из словаря",
    "source_attribution_overuse": "уместность ссылки на источник зависит от вывода; "
    "частота названий площадок у автора не отделяется от нормы",
    "genre_mismatch_too_long_literary": "жанр и длина относительно эталонов: "
    "длина эталонов 440–1300 слов, но ~2000 у автора тоже встречаются",
    "water_hedging": "плотность оговорок v8 (8,6 на 1000 слов) ниже медианы "
    "corpus-bg (8,7) и эталонов (до 14,6)",
    "obvious_fact": "очевидность зависит от знаний читателя",
    "unclear_edge_case": "нужен смысл фрагмента в контексте",
    "illogical_comparison": "нужна игровая оценка достижимости",
    "weak_or_obvious_tips": "сила совета — игровая оценка",
    "too_short_weak_heroes": "достаточность раздела — оценка содержания",
    "unsupported_or_false_claim": "нужна сверка фактов с игрой",
    "section_rejected_structure": "вкус владельца к блоку целиком",
}

# Keep historic owner labels readable while assigning the same reviewer rubric.
REVIEW_CATEGORY = {
    "source_attribution_overuse": "source_attribution_in_body",
    "genre_mismatch_too_long_literary": "genre_fit",
    "water_hedging": "obvious_or_water", "obvious_fact": "obvious_or_water",
    "too_short_weak_heroes": "genre_fit",
    "section_rejected_structure": "weak_or_obvious_tips",
    "card_text_retelling_and_duplication": "card_text_retelling",
    "duplication": "duplicated_advice",
}

NEW_CHECKS = ("owner.", "card_paraphrase.retelling")

_MARKUP = re.compile(r"\[/?hs_(?:bg|card)\b[^\]]*\]|\*\*|__|`", re.I)


def norm(text: str) -> str:
    text = _MARKUP.sub("", text).replace("ё", "е").replace("Ё", "Е").lower()
    return " ".join(text.replace("\xa0", " ").split())


def _lines_with(text: str, fragment: str) -> list[int]:
    want = norm(fragment)
    return [n for n, line in enumerate(text.split("\n"), 1) if want and want in norm(line)]


def _hits(finding: dict, fragment: str, lines: list[int]) -> bool:
    """Находка задевает фрагмент: та же строка (для фразы) или фрагмент в цитате."""
    if len(fragment.split()) >= 3 and finding.get("line") in lines:
        return True
    want = norm(fragment)
    meta = finding.get("meta") or {}
    haystack = norm(" ".join([finding.get("evidence", ""), str(meta.get("lemma", ""))]))
    return bool(want) and want in haystack


def _matches(finding_id: str, prefixes: tuple[str, ...]) -> bool:
    return any(finding_id == p or (p.endswith(".") and finding_id.startswith(p)) for p in prefixes)


def judge(rejection: dict, text: str, findings: list[dict]) -> dict:
    """Статус одного отклонения и находки, которые задели его фрагменты."""
    category = rejection["category"]
    expected = DETERMINISTIC.get(category, ())
    rows = []
    for fragment in rejection.get("fragments", []):
        lines = _lines_with(text, fragment)
        touched = [f for f in findings if _hits(f, fragment, lines)]
        rows.append(
            {
                "fragment": fragment,
                "lines": lines,
                "expected_hits": sorted({f["id"] for f in touched if _matches(f["id"], expected)}),
                "other_hits": sorted({f["id"] for f in touched if not _matches(f["id"], expected)}),
            }
        )
    if not expected:
        status = "needs_reviewer"
    elif rows and all(r["expected_hits"] for r in rows):
        status = "detected"
    elif any(r["expected_hits"] for r in rows):
        status = "partial"
    else:
        status = "missed"
    touched_lines = {n for r in rows for n in r["lines"]}
    unlabeled = [
        {"id": f["id"], "line": f.get("line")}
        for f in findings
        if _matches(f["id"], expected)
        and f.get("line") not in touched_lines
        and not any(_hits(f, r["fragment"], r["lines"]) for r in rows)
    ]
    return {
        "id": rejection["id"],
        "version": rejection["version"],
        "category": category,
        "reviewer_category": REVIEW_CATEGORY.get(category, category),
        "status": status,
        "reason": NEEDS_REVIEWER.get(category, "") if not expected else "",
        "fragments": rows,
        # находки нужного вида вне размеченных фрагментов: владелец мог
        # назвать проблему без цитаты (повтор Портрета в двух разделах)
        "unlabeled_hits": unlabeled,
    }


def _summary(findings: list[dict]) -> dict:
    new = [f for f in findings if _matches(f["id"], NEW_CHECKS)]
    return {
        "new_checks": {s: sum(1 for f in new if f["severity"] == s) for s in ("error", "review")},
        "new_findings": [
            {"id": f["id"], "severity": f["severity"], "line": f.get("line"),
             "evidence": (f.get("evidence") or "")[:160]}
            for f in new
        ],
        "audit_total": {
            s: sum(1 for f in findings if f["severity"] == s)
            for s in ("error", "likely", "review", "info")
        },
    }


def evaluate(folder: Path, run_audit: Callable[[str, str], list[dict]]) -> dict:
    """Прогнать набор. `run_audit(текст, имя)` возвращает находки audit как dict."""
    labels = json.loads((folder / "labels.json").read_text(encoding="utf-8"))
    versions = folder / "versions"
    cache: dict[str, tuple[str, list[dict]]] = {}

    def audited(path: Path) -> tuple[str, list[dict]]:
        key = str(path)
        if key not in cache:
            text = path.read_text(encoding="utf-8")
            cache[key] = (text, run_audit(text, path.name))
        return cache[key]

    rejections = []
    for rejection in labels["rejections"]:
        text, findings = audited(versions / rejection["version"])
        rejections.append(judge(rejection, text, findings))
    accepted = labels.get("accepted") or sorted(
        p.name for p in versions.glob("*.md") if "accepted" in p.name
    )
    clean = {}
    for name in accepted:
        clean[f"versions/{name}"] = _summary(audited(versions / name)[1])
    for path in sorted((folder / "gold").glob("*")):
        if path.suffix in (".md", ".txt"):
            clean[f"gold/{path.name}"] = _summary(audited(path)[1])
    statuses = [r["status"] for r in rejections]
    return {
        "dataset": str(folder),
        "article": labels.get("article", ""),
        "rejections": rejections,
        "totals": {s: statuses.count(s) for s in ("detected", "partial", "missed", "needs_reviewer")},
        "clean": clean,
        "clean_totals": {
            s: sum(v["new_checks"][s] for v in clean.values()) for s in ("error", "review")
        },
    }


def render(result: dict) -> str:
    out = [f"owner-eval: {result['article']} ({result['dataset']})", ""]
    out.append(f"{'ID':<4} {'версия':<26} {'категория':<36} {'статус':<15} находки")
    for r in result["rejections"]:
        hits = sorted({h for f in r["fragments"] for h in f["expected_hits"]})
        other = sorted({h for f in r["fragments"] for h in f["other_hits"]})
        note = ", ".join(hits) or ("прочие: " + ", ".join(other) if other else "—")
        extra = sorted({f"{u['id']} стр.{u['line']}" for u in r["unlabeled_hits"]})
        if extra:
            note += "; вне фрагментов: " + ", ".join(extra[:3])
        out.append(f"{r['id']:<4} {r['version']:<26} {r['category']:<36} {r['status']:<15} {note}")
    t = result["totals"]
    out.append(
        f"\nитого: detected {t['detected']}, partial {t['partial']}, missed {t['missed']}, "
        f"needs_reviewer {t['needs_reviewer']}"
    )
    out.append("\nновые проверки на эталонах и принятой версии (error / review):")
    for name, v in result["clean"].items():
        out.append(f"  {name:<55} {v['new_checks']['error']} / {v['new_checks']['review']}")
    c = result["clean_totals"]
    out.append(f"  {'всего':<55} {c['error']} / {c['review']}")
    return "\n".join(out)
