#!/usr/bin/env python3
"""Score semantic-audit predictions against the Deep Research gold set."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


DIMENSIONS = (
    "semantic_support",
    "scope_match",
    "authority_match",
    "freshness_match",
    "evidence_type_match",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", help="Gold semantic-cases.jsonl")
    parser.add_argument("predictions", help="Evaluator predictions.jsonl")
    parser.add_argument("--threshold", type=float, default=0.95)
    return parser.parse_args()


def load(path: Path, prefix: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        identifier = item.get("gold_id")
        if not isinstance(identifier, str) or not identifier.startswith(prefix):
            raise ValueError(f"{path.name}:{line_number}: invalid gold_id")
        if identifier in result:
            raise ValueError(f"{path.name}:{line_number}: duplicate {identifier}")
        result[identifier] = item
    return result


def main() -> int:
    args = parse_args()
    try:
        cases = load(Path(args.cases).expanduser().resolve(), "GOLD-")
        predictions = load(Path(args.predictions).expanduser().resolve(), "GOLD-")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Semantic gold: FAIL\n- {exc}")
        return 1
    if len(cases) < 20:
        print("Semantic gold: FAIL\n- at least 20 cases are required")
        return 1
    missing = sorted(set(cases) - set(predictions))
    extra = sorted(set(predictions) - set(cases))
    if missing or extra:
        print("Semantic gold: FAIL")
        if missing:
            print(f"- missing predictions: {', '.join(missing)}")
        if extra:
            print(f"- unknown predictions: {', '.join(extra)}")
        return 1

    correct = 0
    total = 0
    p0_failures: list[str] = []
    verdict_correct = 0
    for identifier, case in cases.items():
        prediction = predictions[identifier]
        case_exact = True
        for dimension in DIMENSIONS:
            expected = case.get(f"expected_{dimension}")
            actual = prediction.get(dimension)
            total += 1
            if expected == actual:
                correct += 1
                if dimension == "semantic_support":
                    verdict_correct += 1
            else:
                case_exact = False
        if case.get("p0") is True and not case_exact:
            p0_failures.append(identifier)

    field_accuracy = correct / total
    verdict_accuracy = verdict_correct / len(cases)
    if field_accuracy < args.threshold or verdict_accuracy < args.threshold or p0_failures:
        print("Semantic gold: FAIL")
        print(f"- field accuracy: {field_accuracy:.3f}")
        print(f"- verdict accuracy: {verdict_accuracy:.3f}")
        if p0_failures:
            print(f"- P0 failures: {', '.join(p0_failures)}")
        return 1
    print(
        "Semantic gold: PASS "
        f"({len(cases)} cases, field_accuracy={field_accuracy:.3f}, "
        f"verdict_accuracy={verdict_accuracy:.3f}, p0_failures=0)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

