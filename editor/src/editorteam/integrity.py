"""Narrow, inspectable consistency checks; no automatic factual corrections."""
from __future__ import annotations

import re

# The score cue and explicit win percentage must share a short clause. Ranges,
# deck stats, dates and percentages in the next sentence are not win records.
_RECORD = re.compile(
    r"\b(?:со\s+)?сч[её]т(?:ом)?\s+(?P<wins>\d{1,6})\s*[-–—:]\s*(?P<losses>\d{1,6})"
    r"\s*\(\s*(?P<approx>около\s+|примерно\s+)?(?P<pct>\d{1,3}(?:[.,]\d{1,2})?)"
    r"\s*%\s*(?:винрейта|побед)\s*\)", re.I,
)


def arithmetic_issues(text: str) -> list[dict]:
    """Detect only incompatible explicit record/percentage pairs.

    This establishes an internal inconsistency, not which input is true.
    Exact percentages allow displayed rounding; explicitly approximate integer
    percentages allow one percentage point. Draws/other denominators need review.
    """
    issues = []
    for match in _RECORD.finditer(text):
        wins, losses = int(match["wins"]), int(match["losses"])
        if wins + losses == 0:
            continue  # Undefined denominator is not evidence of a false record.
        displayed = match["pct"].replace(",", ".")
        expected = 100 * wins / (wins + losses)
        digits = len(displayed.partition(".")[2])
        tolerance = 1.0 if match["approx"] else 0.5 * 10 ** -digits
        if abs(expected - float(displayed)) <= tolerance + 1e-9:
            continue
        issues.append({
            "kind": "ARITHMETIC_INCONSISTENCY", "severity": "error",
            "evidence": match[0], "line": text.count("\n", 0, match.start()) + 1,
            "message": f"Счёт {wins}-{losses} даёт {expected:.2f}% побед, а в тексте {displayed}%; числа несовместимы при одном наборе игр.",
            "suggestion": "Сверить исходный результат и процент с источником; уточнить выборку и ничьи. Не выбирать автоматически, какое число исправлять.",
        })
    return issues


def diagnostic_scope() -> dict:
    """Legacy accepted remains a deterministic diagnostic result only."""
    return {"review_scope": "diagnostics_only", "independent_review_required": True,
            "publication_ready": False, "source_verification": "not_performed"}
