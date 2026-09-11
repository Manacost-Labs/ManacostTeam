#!/usr/bin/env python3
"""Validate the search-recall benchmark and score linked bundles.

Each case names the sources a competent researcher must find for a question:
exact pages by canonical URL, or venues by host plus path prefix. A linked
bundle is scored on recall against that gold set, on how many queries it took
to reach the first official or statistics source, and on snippet-only sources.
The structural benchmark proves traceability; this one proves the search
looked where it had to.

``--stage plan`` validates case definitions only. ``--stage score`` also opens
every bundle listed in ``results.jsonl``; cases without a bundle are reported
as ``not_run`` and do not fail the gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from search_support import canonical_url, url_host

ORACLE_VERSION = "1.0"
MIN_RECALL = 0.9
MIN_CASES = 10
SNIPPET_INTEGRITY_VALUES = frozenset({"snippet", "search_snippet", "snippet_only"})
AUTHORITATIVE_TYPES = frozenset(
    {"official", "official_law", "official_social", "statistics", "dataset", "structured_data"}
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="Recall benchmark directory with cases.jsonl")
    parser.add_argument("--stage", choices=("plan", "score"), default="score")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--require-all", action="store_true", help="Fail when any case is not_run"
    )
    return parser.parse_args(argv)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError(f"{path.name}:{number}: record must be an object")
            records.append(item)
    return records


def validate_cases(cases: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, case in enumerate(cases, 1):
        label = f"cases.jsonl:{index}"
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.startswith("RECALL-"):
            errors.append(f"{label}: case_id must start with RECALL-")
            continue
        if case_id in seen:
            errors.append(f"{label}: duplicate case {case_id}")
        seen.add(case_id)
        if case.get("oracle_version") != ORACLE_VERSION:
            errors.append(f"{label}: oracle_version must be {ORACLE_VERSION}")
        for field in ("prompt", "domain", "mode", "as_of"):
            if not isinstance(case.get(field), str) or not case[field].strip():
                errors.append(f"{label}: missing {field}")
        gold = case.get("gold_sources")
        if not isinstance(gold, list) or len(gold) < 3:
            errors.append(f"{label}: gold_sources needs at least three entries")
            continue
        for position, item in enumerate(gold, 1):
            entry = f"{label}:gold[{position}]"
            if not isinstance(item, dict):
                errors.append(f"{entry}: must be an object")
                continue
            kind = item.get("match")
            if kind == "url":
                if not str(item.get("url", "")).startswith("https://"):
                    errors.append(f"{entry}: url match needs an https URL")
            elif kind == "host_prefix":
                if not item.get("host") or not isinstance(item.get("path_prefix"), str):
                    errors.append(f"{entry}: host_prefix match needs host and path_prefix")
            else:
                errors.append(f"{entry}: match must be url or host_prefix")
            if not isinstance(item.get("why"), str) or not item["why"].strip():
                errors.append(f"{entry}: needs a why")
            if not isinstance(item.get("source_class"), str):
                errors.append(f"{entry}: needs a source_class")
    return errors


def gold_hit(item: dict[str, Any], sources: list[dict[str, Any]]) -> str | None:
    for record in sources:
        url = str(record.get("final_url") or record.get("requested_url") or record.get("url") or "")
        if not url:
            continue
        if item["match"] == "url" and canonical_url(url) == canonical_url(item["url"]):
            return str(record.get("source_id"))
        if item["match"] == "host_prefix":
            host = url_host(url)
            wanted = url_host(f"https://{item['host']}")
            path = canonical_url(url).split(wanted, 1)[-1] if wanted in canonical_url(url) else ""
            if host == wanted and path.startswith(item["path_prefix"]):
                return str(record.get("source_id"))
    return None


def score_bundle(case: dict[str, Any], bundle: Path) -> dict[str, Any]:
    sources = load_jsonl(bundle / "sources.jsonl")
    queries = load_jsonl(bundle / "queries.jsonl")
    hits: list[dict[str, Any]] = []
    misses: list[dict[str, Any]] = []
    for item in case["gold_sources"]:
        source_id = gold_hit(item, sources)
        target = item.get("url") or f"{item.get('host')}{item.get('path_prefix')}"
        (hits if source_id else misses).append({"gold": target, "source_id": source_id, "why": item["why"]})
    recall = len(hits) / len(case["gold_sources"])
    snippet_only = [
        str(record.get("source_id")) for record in sources
        if str(record.get("access_integrity", "")) in SNIPPET_INTEGRITY_VALUES
    ]
    by_id = {str(record.get("source_id")): record for record in sources}
    ordered = sorted(queries, key=lambda record: (str(record.get("executed_at", "")), str(record.get("query_id", ""))))
    first_authoritative: int | None = None
    for position, record in enumerate(ordered, 1):
        result_ids = record.get("result_source_ids") if isinstance(record.get("result_source_ids"), list) else []
        if any(str(by_id.get(str(sid), {}).get("source_type", "")) in AUTHORITATIVE_TYPES for sid in result_ids):
            first_authoritative = position
            break
    status = "pass" if recall >= MIN_RECALL and not snippet_only else "fail"
    return {
        "status": status,
        "recall": round(recall, 3),
        "gold_total": len(case["gold_sources"]),
        "gold_found": len(hits),
        "hits": hits,
        "misses": misses,
        "snippet_only": snippet_only,
        "queries_total": len(queries),
        "queries_to_first_authoritative": first_authoritative,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.directory).expanduser().resolve()
    try:
        cases = load_jsonl(root / "cases.jsonl")
        results = load_jsonl(root / "results.jsonl")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    errors = validate_cases(cases)
    if len(cases) < MIN_CASES:
        errors.append(f"recall benchmark needs at least {MIN_CASES} cases, found {len(cases)}")
    if errors:
        print("Recall benchmark: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    if args.stage == "plan":
        print(f"Recall benchmark: PASS ({len(cases)} cases defined, stage=plan)")
        return 0

    bundle_by_case = {str(item.get("case_id")): item for item in results}
    scored: dict[str, Any] = {}
    failures: list[str] = []
    not_run: list[str] = []
    for case in cases:
        case_id = case["case_id"]
        link = bundle_by_case.get(case_id)
        bundle_path = None
        if link and isinstance(link.get("bundle_path"), str):
            bundle_path = (root / link["bundle_path"]).resolve()
        if bundle_path is None or not (bundle_path / "sources.jsonl").is_file():
            scored[case_id] = {"status": "not_run"}
            not_run.append(case_id)
            continue
        try:
            report = score_bundle(case, bundle_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            scored[case_id] = {"status": "error", "error": str(exc)}
            failures.append(f"{case_id}: {exc}")
            continue
        scored[case_id] = report
        if report["status"] == "fail":
            missed = "; ".join(item["gold"] for item in report["misses"])
            failures.append(
                f"{case_id}: recall {report['recall']} ({report['gold_found']}/{report['gold_total']})"
                + (f", missed: {missed}" if missed else "")
                + (f", snippet-only: {', '.join(report['snippet_only'])}" if report["snippet_only"] else "")
            )
    summary = {
        "cases": len(cases),
        "scored": len(cases) - len(not_run),
        "not_run": not_run,
        "passed": sum(1 for item in scored.values() if item.get("status") == "pass"),
        "results": scored,
        "failures": failures,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        verdict = "FAIL" if failures or (args.require_all and not_run) else "PASS"
        print(
            f"Recall benchmark: {verdict} ({summary['passed']}/{summary['scored']} scored cases pass, "
            f"{len(not_run)} not run, stage=score)"
        )
        for case_id, report in scored.items():
            if report.get("status") in {"pass", "fail"}:
                print(
                    f"- {case_id}: {report['status']} recall {report['recall']} "
                    f"({report['gold_found']}/{report['gold_total']}), "
                    f"first authoritative at query {report['queries_to_first_authoritative']}"
                )
        for failure in failures:
            print(f"- fail: {failure}")
        for case_id in not_run:
            print(f"- not_run: {case_id}")
    if failures or (args.require_all and not_run):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
