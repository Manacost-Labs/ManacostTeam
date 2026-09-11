#!/usr/bin/env python3
"""Record seen search results in a bundle's ``candidates.jsonl`` ledger.

Recall cannot be measured while rejected results are invisible. Every result a
researcher looks at gets one record: opened (with the resulting source ID),
rejected (with a canonical reason), or deferred. ``fetch_source.py`` writes the
``opened`` record itself; use this script for rejections, deferrals, and bulk
imports of a result list.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from search_support import (
    CANDIDATE_DECISIONS,
    CANDIDATE_REJECT_REASONS,
    canonical_url,
    next_id,
)

LEDGER = "candidates.jsonl"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        encoding="utf-8",
    )


def record_candidate(
    root: Path,
    *,
    query_id: str,
    url: str,
    decision: str,
    reason: str | None = None,
    source_id: str | None = None,
    title: str | None = None,
    rank: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Append or update one candidate record and return it.

    A record is keyed by ``(query_id, canonical URL)``. Recording the same
    pair again updates the decision instead of duplicating the row, so a
    deferred result that is later opened keeps one identity.
    """

    if decision not in CANDIDATE_DECISIONS:
        raise ValueError(f"invalid decision {decision!r}")
    if decision == "rejected" and reason not in CANDIDATE_REJECT_REASONS:
        raise ValueError("rejected candidates need a canonical reason")
    if decision == "opened" and not source_id:
        raise ValueError("opened candidates need the resulting source_id")
    path = root / LEDGER
    records = load_jsonl(path)
    key = canonical_url(url)
    existing = next(
        (
            item
            for item in records
            if item.get("query_id") == query_id and canonical_url(str(item.get("url", ""))) == key
        ),
        None,
    )
    now = utc_now()
    if existing is None:
        ids = {str(item.get("candidate_id")) for item in records if item.get("candidate_id")}
        existing = {
            "candidate_id": next_id("CAN", ids),
            "query_id": query_id,
            "url": url,
            "seen_at": now,
        }
        records.append(existing)
    existing["decision"] = decision
    existing["decided_at"] = now
    if title:
        existing["title"] = title
    if rank is not None:
        existing["rank"] = rank
    if reason:
        existing["reason"] = reason
    elif decision != "rejected":
        existing.pop("reason", None)
    if source_id:
        existing["source_id"] = source_id
    if note:
        existing["note"] = note
    write_jsonl(path, records)
    return existing


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record", help="Record one seen result")
    record.add_argument("directory")
    record.add_argument("--query-id", required=True)
    record.add_argument("--url", required=True)
    record.add_argument("--decision", required=True, choices=sorted(CANDIDATE_DECISIONS))
    record.add_argument("--reason", choices=sorted(CANDIDATE_REJECT_REASONS))
    record.add_argument("--source-id")
    record.add_argument("--title")
    record.add_argument("--rank", type=int)
    record.add_argument("--note")

    bulk = sub.add_parser("bulk", help="Record many results from a JSON list or JSONL file")
    bulk.add_argument("directory")
    bulk.add_argument("file", help="JSON array or JSON lines of {query_id, url, decision, ...}")

    summary = sub.add_parser("summary", help="Print decision counts")
    summary.add_argument("directory")
    return parser.parse_args(argv)


def known_query_ids(root: Path) -> set[str]:
    ids: set[str] = set()
    for name in ("queries.jsonl", "query-plan.jsonl"):
        for item in load_jsonl(root / name):
            if isinstance(item.get("query_id"), str):
                ids.add(item["query_id"])
    return ids


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.directory).expanduser().resolve()
    if not (root / "manifest.json").is_file():
        print(f"error: not a research bundle: {root}", file=sys.stderr)
        return 2
    try:
        if args.command == "summary":
            records = load_jsonl(root / LEDGER)
            counts: dict[str, int] = {}
            reasons: dict[str, int] = {}
            for item in records:
                counts[str(item.get("decision"))] = counts.get(str(item.get("decision")), 0) + 1
                if item.get("decision") == "rejected":
                    reasons[str(item.get("reason"))] = reasons.get(str(item.get("reason")), 0) + 1
            print(f"Candidates: {len(records)} seen; " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
            for reason, count in sorted(reasons.items(), key=lambda pair: -pair[1]):
                print(f"- rejected {reason}: {count}")
            return 0
        queries = known_query_ids(root)
        if args.command == "record":
            if args.query_id not in queries:
                print(f"error: unknown query {args.query_id}", file=sys.stderr)
                return 2
            record = record_candidate(
                root,
                query_id=args.query_id,
                url=args.url,
                decision=args.decision,
                reason=args.reason,
                source_id=args.source_id,
                title=args.title,
                rank=args.rank,
                note=args.note,
            )
            print(f"Recorded {record['candidate_id']}: {record['decision']} {record['url']}")
            return 0
        text = Path(args.file).read_text(encoding="utf-8")
        stripped = text.strip()
        items: list[Any]
        if stripped.startswith("["):
            items = json.loads(stripped)
        else:
            items = [json.loads(line) for line in stripped.splitlines() if line.strip()]
        written = 0
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("bulk items must be objects")
            if item.get("query_id") not in queries:
                raise ValueError(f"unknown query {item.get('query_id')}")
            record_candidate(
                root,
                query_id=str(item["query_id"]),
                url=str(item["url"]),
                decision=str(item.get("decision", "deferred")),
                reason=item.get("reason"),
                source_id=item.get("source_id"),
                title=item.get("title"),
                rank=item.get("rank"),
                note=item.get("note"),
            )
            written += 1
        print(f"Recorded {written} candidates")
        return 0
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
