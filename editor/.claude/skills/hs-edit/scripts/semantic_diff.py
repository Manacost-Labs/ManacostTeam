#!/usr/bin/env python3
"""Semantic post-edit guard for facts, negation, numbers, and claim contracts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

NEGATION = re.compile(r"\b(?:не|нельзя|никогда|not|never|don't|do\s+not)\b", re.IGNORECASE)
TOKENS = re.compile(r"[a-zа-яёа-я0-9]+", re.IGNORECASE)
NUMBERS = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?%?(?!\w)")
CONTRACT_FIELDS = (
    "subject",
    "action",
    "target",
    "card",
    "context",
    "condition",
    "negation",
    "certainty",
    "numbers",
)


# Оговорки автора исходника про сам исходник, его доказательства и подготовку
# материала: «не претендует», «получить не удалось», «не забыть», «нельзя
# подтвержденно объявить», «для статьи». Читателю статьи они ничего не дают.
_META_NEGATION = re.compile(
    r"""
    \bне\s+(?:претендует|удалось|забыть|забывайте|забудьте|заявля\w+|
             включен\w*|подтвержден\w*|измерен\w*)\b
  | \bнельзя\s+(?:\w+\s+){0,2}?(?:подтвержд\w+|объявл\w+|считать|утверждать|
                            выдавать|приписывать|приводить)\b
  | \b(?:для|в)\s+(?:статьи|статью|мета-?отч[её]та|отч[её]та|абзаца|материала)\b
  | \bпроверить,\s+не\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
# «не просто X, а Y» и «X, а не Y»: отрицание только в противопоставлении
_CONTRAST = re.compile(r",\s*а\s+не\s|\bне\s+(?:просто|только)\s[^.!?;]{0,80}?,\s*а\s", re.IGNORECASE)


def negation_type(sentence: str) -> str:
    """Что за отрицание в предложении исходника: fact, contrast или rhetorical.

    fact — отрицание несёт факт игры или совет («Бранн не удваивает Беглеца»,
    «не оставляйте Мастера брони»). Его потеря — потеря смысла.
    contrast — отрицание стоит только в противопоставлении «X, а не Y». Смысл
    держит положительная половина, её покрывают проверки карт и чисел.
    rhetorical — оговорка автора исходника о самом исходнике и доказательствах.

    Требовать сохранить два последних вида нельзя: тогда переплавка тащит в
    текст риторику источника, а именно её и надо вычищать.
    """
    if _META_NEGATION.search(sentence):
        return "rhetorical"
    leftover = _CONTRAST.sub(" ", sentence)
    if NEGATION.search(sentence) and not NEGATION.search(leftover):
        return "contrast"
    return "fact"


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[.!?…])\s+|\n+", text) if item.strip()]


def _semantic_tokens(text: str) -> set[str]:
    without_negation = NEGATION.sub(" ", text.casefold())
    return set(TOKENS.findall(without_negation))


def _similarity(left: str, right: str) -> float:
    a, b = _semantic_tokens(left), _semantic_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def negation_flips(before: str, after: str) -> list[dict]:
    issues = []
    after_sentences = _sentences(after)
    for source in _sentences(before):
        if not NEGATION.search(source) or negation_type(source) != "fact":
            continue
        best = max(after_sentences, key=lambda item: _similarity(source, item), default="")
        similarity = _similarity(source, best)
        if similarity >= 0.6 and best and not NEGATION.search(best):
            issues.append(
                {
                    "kind": "FACTUAL_SEMANTIC_DRIFT",
                    "field": "negation",
                    "message": "после редактуры исчезло отрицание",
                    "before": source,
                    "after": best,
                    "similarity": round(similarity, 3),
                    "severity": "error",
                }
            )
    return issues


def number_drift(
    before: str, after: str, allowed_removed_numbers: list[str] | None = None
) -> list[dict]:
    left, right = Counter(NUMBERS.findall(before)), Counter(NUMBERS.findall(after))
    removed = left - right
    added = right - left
    allowed = Counter(allowed_removed_numbers or [])
    if not added and not (removed - allowed):
        return []
    if left == right:
        return []
    return [
        {
            "kind": "FACTUAL_SEMANTIC_DRIFT",
            "field": "numbers",
            "message": "изменился набор чисел или процентов",
            "before": dict(left),
            "after": dict(right),
            "severity": "error",
        }
    ]


def _claim_map(claims: list[dict] | None) -> dict[str, dict]:
    return {
        str(claim["claim_id"]): claim
        for claim in claims or []
        if isinstance(claim, dict) and claim.get("claim_id")
    }


def claim_contract_drift(before: list[dict] | None, after: list[dict] | None) -> list[dict]:
    if before is None and after is None:
        return []
    old, new = _claim_map(before), _claim_map(after)
    issues: list[dict] = []
    for claim_id, source in old.items():
        target = new.get(claim_id)
        if target is None:
            issues.append(
                {
                    "kind": "FACTUAL_SEMANTIC_DRIFT",
                    "claim_id": claim_id,
                    "field": "claim",
                    "message": "claim исчез из post-edit snapshot",
                    "severity": "error",
                }
            )
            continue
        old_meaning = source.get("meaning") if isinstance(source.get("meaning"), dict) else {}
        new_meaning = target.get("meaning") if isinstance(target.get("meaning"), dict) else {}
        for field in CONTRACT_FIELDS:
            if old_meaning.get(field) != new_meaning.get(field):
                issues.append(
                    {
                        "kind": "FACTUAL_SEMANTIC_DRIFT",
                        "claim_id": claim_id,
                        "field": field,
                        "message": f"claim contract changed: {field}",
                        "before": old_meaning.get(field),
                        "after": new_meaning.get(field),
                        "severity": "error",
                    }
                )
        for field in ("confidence", "patch", "meta_epoch"):
            if source.get(field) != target.get(field):
                issues.append(
                    {
                        "kind": "FACTUAL_SEMANTIC_DRIFT",
                        "claim_id": claim_id,
                        "field": field,
                        "message": f"claim contract changed: {field}",
                        "before": source.get(field),
                        "after": target.get(field),
                        "severity": "error",
                    }
                )
    for claim_id in sorted(set(new) - set(old)):
        issues.append(
            {
                "kind": "FACTUAL_SEMANTIC_DRIFT",
                "claim_id": claim_id,
                "field": "claim",
                "message": "post-edit snapshot contains a new unsupported claim",
                "severity": "error",
            }
        )
    return issues


def freshness_issues(
    claims: list[dict] | None,
    current_meta_epoch: str | None = None,
    current_patch: str | None = None,
) -> list[dict]:
    issues = []
    for claim in claims or []:
        claim_id = claim.get("claim_id")
        if current_meta_epoch and claim.get("meta_epoch") != current_meta_epoch:
            issues.append(
                {
                    "kind": "STALE_EVIDENCE",
                    "claim_id": claim_id,
                    "field": "meta_epoch",
                    "message": "evidence meta_epoch does not match current meta epoch",
                    "expected": current_meta_epoch,
                    "actual": claim.get("meta_epoch"),
                    "severity": "error",
                }
            )
        if current_patch and claim.get("patch") != current_patch:
            issues.append(
                {
                    "kind": "STALE_EVIDENCE",
                    "claim_id": claim_id,
                    "field": "patch",
                    "message": "evidence patch does not match current patch",
                    "expected": current_patch,
                    "actual": claim.get("patch"),
                    "severity": "error",
                }
            )
    return issues


def compare(
    before_text: str,
    after_text: str,
    claims_before: list[dict] | None = None,
    claims_after: list[dict] | None = None,
    current_meta_epoch: str | None = None,
    current_patch: str | None = None,
    allowed_removed_numbers: list[str] | None = None,
) -> list[dict]:
    return [
        *negation_flips(before_text, after_text),
        *number_drift(before_text, after_text, allowed_removed_numbers),
        *claim_contract_drift(claims_before, claims_after),
        *freshness_issues(claims_before, current_meta_epoch, current_patch),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare meaning before and after editing")
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--claims-before", type=Path)
    parser.add_argument("--claims-after", type=Path)
    parser.add_argument("--current-meta-epoch")
    parser.add_argument("--current-patch")
    args = parser.parse_args()
    try:
        before_text = args.before.read_text(encoding="utf-8")
        after_text = args.after.read_text(encoding="utf-8")
        before_claims = (
            json.loads(args.claims_before.read_text(encoding="utf-8"))
            if args.claims_before
            else None
        )
        after_claims = (
            json.loads(args.claims_after.read_text(encoding="utf-8")) if args.claims_after else None
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    issues = compare(
        before_text,
        after_text,
        before_claims,
        after_claims,
        args.current_meta_epoch,
        args.current_patch,
    )
    print(json.dumps({"accepted": not issues, "violations": issues}, ensure_ascii=False, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
