#!/usr/bin/env python3
"""Suggest shared lineage for near-duplicate source snapshots.

Two pages that carry the same text are not independent corroboration. This
script compares the snapshots in a bundle with word-shingle Jaccard similarity
and reports pairs above a threshold whose sources still have different
``lineage_id`` values. With ``--apply`` the later-accessed source adopts the
earlier source's lineage and records the similarity and the tool that set it.

It measures textual overlap only. A page that paraphrases a press release or
quotes one dataset can still share an origin; record such cases by hand.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from itertools import combinations
from pathlib import Path
from typing import Any

from search_support import normalize_for_match

SHINGLE_WORDS = 5
DEFAULT_THRESHOLD = 0.5
MIN_SHINGLES = 20
HEADER_KEYS = ("Source:", "URL:", "Requested:", "Canonical:", "Accessed:", "Content-Type:", "Published:", "Inspected:")
WORD_RE = re.compile(r"\w+", re.UNICODE)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="Research bundle directory")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--apply", action="store_true", help="Rewrite lineage_id of later duplicates")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def atomic_write(path: Path, text: str) -> None:
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def body_text(snapshot: str) -> str:
    """Drop the snapshot header block written by fetch_source.py or by hand."""

    lines = snapshot.splitlines()
    index = 0
    while index < len(lines) and (not lines[index].strip() or lines[index].startswith(HEADER_KEYS)):
        index += 1
    return "\n".join(lines[index:])


def shingles(text: str, size: int = SHINGLE_WORDS) -> set[int]:
    words = WORD_RE.findall(normalize_for_match(text))
    if len(words) < size:
        return set()
    return {hash(" ".join(words[i : i + size])) for i in range(len(words) - size + 1)}


def jaccard(left: set[int], right: set[int]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def analyze(root: Path, threshold: float) -> dict[str, Any]:
    root = root.resolve()
    sources = load_jsonl(root / "sources.jsonl")
    fingerprints: dict[str, set[int]] = {}
    skipped: list[str] = []
    for record in sources:
        source_id = str(record.get("source_id", "?"))
        snapshot_value = record.get("snapshot_path")
        if not isinstance(snapshot_value, str) or not snapshot_value:
            continue
        try:
            path = (root / snapshot_value).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                continue
            text = body_text(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        grams = shingles(text)
        if len(grams) < MIN_SHINGLES:
            skipped.append(source_id)
            continue
        fingerprints[source_id] = grams
    by_id = {str(record.get("source_id")): record for record in sources}
    pairs: list[dict[str, Any]] = []
    for left, right in combinations(sorted(fingerprints), 2):
        score = jaccard(fingerprints[left], fingerprints[right])
        if score < threshold:
            continue
        left_record, right_record = by_id[left], by_id[right]
        same = left_record.get("lineage_id") == right_record.get("lineage_id")
        earlier, later = sorted(
            (left, right), key=lambda sid: (str(by_id[sid].get("accessed_at", "")), sid)
        )
        pairs.append(
            {
                "source_a": left,
                "source_b": right,
                "similarity": round(score, 3),
                "same_lineage": same,
                "suggested_lineage_id": by_id[earlier].get("lineage_id"),
                "adopting_source_id": later,
            }
        )
    pairs.sort(key=lambda item: -item["similarity"])
    return {
        "compared": len(fingerprints),
        "skipped_short": skipped,
        "threshold": threshold,
        "pairs": pairs,
        "suggestions": [pair for pair in pairs if not pair["same_lineage"]],
    }


def apply_suggestions(root: Path, report: dict[str, Any]) -> int:
    root = root.resolve()
    sources = load_jsonl(root / "sources.jsonl")
    by_id = {str(record.get("source_id")): record for record in sources}
    changed = 0
    for pair in report["suggestions"]:
        target = by_id.get(pair["adopting_source_id"])
        lineage = pair["suggested_lineage_id"]
        if target is None or not lineage or target.get("lineage_id") == lineage:
            continue
        target["previous_lineage_id"] = target.get("lineage_id")
        target["lineage_id"] = lineage
        target["lineage_set_by"] = "lineage_suggest.py"
        target["lineage_similarity"] = pair["similarity"]
        target["lineage_matched_source_id"] = (
            pair["source_a"] if pair["adopting_source_id"] == pair["source_b"] else pair["source_b"]
        )
        changed += 1
    if changed:
        atomic_write(
            root / "sources.jsonl",
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in sources),
        )
    return changed


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.directory).expanduser().resolve()
    if not (root / "manifest.json").is_file():
        print(f"error: not a research bundle: {root}", file=sys.stderr)
        return 2
    if not 0 < args.threshold <= 1:
        print("error: threshold must be in (0, 1]", file=sys.stderr)
        return 2
    try:
        report = analyze(root, args.threshold)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"Lineage suggestions: {len(report['suggestions'])} pairs above {args.threshold} "
            f"with different lineage ({report['compared']} snapshots compared, "
            f"{len(report['skipped_short'])} too short)"
        )
        for pair in report["pairs"]:
            marker = "same lineage" if pair["same_lineage"] else f"suggest {pair['suggested_lineage_id']} for {pair['adopting_source_id']}"
            print(f"- {pair['source_a']} ~ {pair['source_b']}: {pair['similarity']} ({marker})")
    if args.apply:
        changed = apply_suggestions(root, report)
        print(f"Applied lineage to {changed} sources")
    elif report["suggestions"] and not args.json:
        print("Preview only; use --apply to record the suggested lineage")
    return 0


if __name__ == "__main__":
    sys.exit(main())
