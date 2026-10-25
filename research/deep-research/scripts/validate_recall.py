#!/usr/bin/env python3
"""Validate the search-recall benchmark and score linked bundles.

Each case names the sources a competent researcher must find for a question:
exact pages by canonical URL, or venues by host plus path prefix. A linked
bundle is scored on recall against that gold set, on how many queries it took
to reach the first official or statistics source, and on snippet-only sources.
The structural benchmark proves traceability; this one proves the search
looked where it had to.

Recall is reported at two levels: ``recall`` counts gold found among recorded
sources, ``discovery_recall`` also counts gold that only surfaced as a search
candidate. Both are broken down by source class (official, statistics, reddit,
x, youtube, chinese, podcast, web).

``--stage plan`` validates case definitions only. ``--stage score`` also opens
every bundle listed in ``results.jsonl``; cases without a bundle are reported
as ``not_run`` and do not fail the gate. ``run_recall.py`` wraps scoring with
history and live search runs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from search_support import canonical_url, url_host
from source_classes import SOURCE_CLASSES, source_class

ORACLE_VERSION = "1.1"
ORACLE_VERSIONS = frozenset({"1.0", ORACLE_VERSION})
MIN_RECALL = 0.9
MIN_CASES = 30
CASE_TYPES = frozenset({"meta_report", "deck_guide", "battlegrounds", "patch", "news", "arena", "esports"})
VERIFY_ROUTES = frozenset({"direct", "tinyfish", "browser"})
SNIPPET_INTEGRITY_VALUES = frozenset({"snippet", "search_snippet", "snippet_only"})
AUTHORITATIVE_TYPES = frozenset(
    {"official", "official_law", "official_social", "statistics", "dataset", "structured_data"}
)
# Blizzard serves one article under several hosts and slugs; the numeric
# article id is the identity (registry note: news.blizzard.com mirrors it).
BLIZZARD_ARTICLE_HOSTS = frozenset(
    {"hearthstone.blizzard.com", "playhearthstone.com", "news.blizzard.com", "hs.blizzard.cn"}
)
BLIZZARD_ARTICLE_RE = re.compile(r"/(?:[a-z]{2}-[a-z]{2}/)?(?:news|blog|article)/(?:[a-z]+/)?(\d{7,9})(?:/|$)")


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


def _check_date(value: Any) -> bool:
    try:
        date.fromisoformat(str(value))
    except ValueError:
        return False
    return True


def validate_search_setup(setup: Any, label: str) -> list[str]:
    """Inputs a live run needs; the planner never translates on its own."""
    errors: list[str] = []
    if not isinstance(setup, dict):
        return [f"{label}: search_setup must be an object"]
    topic = setup.get("topic")
    if not isinstance(topic, dict) or not all(
        isinstance(topic.get(language), str) and topic[language].strip() for language in ("en", "ru", "zh")
    ):
        errors.append(f"{label}: search_setup.topic needs en, ru and zh phrases")
    for position, entity in enumerate(setup.get("entities", []), 1):
        if not isinstance(entity, dict) or not entity.get("entity_id") or not (
            isinstance(entity.get("dbf"), int) or isinstance(entity.get("names"), dict)
        ):
            errors.append(f"{label}: search_setup.entities[{position}] needs entity_id and dbf or names")
    markers = setup.get("version_markers", [])
    if not isinstance(markers, list) or any(not isinstance(item, str) or not item for item in markers):
        errors.append(f"{label}: search_setup.version_markers must be a list of strings")
    return errors


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
        version = case.get("oracle_version")
        if version not in ORACLE_VERSIONS:
            errors.append(f"{label}: oracle_version must be one of {', '.join(sorted(ORACLE_VERSIONS))}")
        current = version == ORACLE_VERSION
        for field in ("prompt", "domain", "mode", "as_of"):
            if not isinstance(case.get(field), str) or not case[field].strip():
                errors.append(f"{label}: missing {field}")
        if current and case.get("case_type") not in CASE_TYPES:
            errors.append(f"{label}: case_type must be one of {', '.join(sorted(CASE_TYPES))}")
        if "search_setup" in case:
            errors.extend(validate_search_setup(case["search_setup"], label))
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
            elif current and item["source_class"] not in SOURCE_CLASSES:
                errors.append(f"{entry}: source_class must be one of {', '.join(SOURCE_CLASSES)}")
            probe = item.get("probe_url")
            venue = kind == "host_prefix" and item.get("host") and isinstance(item.get("path_prefix"), str)
            if probe is not None and (not venue or not gold_matches(item, str(probe))):
                errors.append(f"{entry}: probe_url must be a page inside the host_prefix venue")
            aliases = item.get("aliases", [])
            if not isinstance(aliases, list) or any(not str(alias).startswith("https://") for alias in aliases):
                errors.append(f"{entry}: aliases must be https URLs")
            if current:
                # Oracle 1.1: every gold target was opened before it was added.
                if not _check_date(item.get("verified_at")):
                    errors.append(f"{entry}: verified_at must be YYYY-MM-DD")
                if item.get("verified_via") not in VERIFY_ROUTES:
                    errors.append(f"{entry}: verified_via must be one of {', '.join(sorted(VERIFY_ROUTES))}")
    return errors


def gold_target(item: dict[str, Any]) -> str:
    return item.get("url") or f"https://{item.get('host')}{item.get('path_prefix')}"


def gold_class(item: dict[str, Any]) -> str:
    """Oracle 1.0 used community/expert; infer the lane from the target."""
    value = item.get("source_class")
    return value if value in SOURCE_CLASSES else source_class(gold_target(item))


def page_identity(url: str) -> str:
    canonical = canonical_url(url)
    host = url_host(url)
    if host in BLIZZARD_ARTICLE_HOSTS:
        match = BLIZZARD_ARTICLE_RE.search(urlsplit(canonical).path)
        if match:
            region = "cn" if host == "hs.blizzard.cn" else "global"
            return f"blizzard-article:{region}:{match.group(1)}"
    return canonical


def gold_matches(item: dict[str, Any], url: str) -> bool:
    if not url:
        return False
    if item["match"] == "url":
        identity = page_identity(url)
        return any(identity == page_identity(target) for target in [item["url"], *item.get("aliases", [])])
    host = url_host(url)
    wanted = url_host(f"https://{item['host']}")
    path = urlsplit(canonical_url(url)).path
    return host == wanted and path.lower().startswith(item["path_prefix"].lower())


def record_url(record: dict[str, Any]) -> str:
    return str(record.get("final_url") or record.get("requested_url") or record.get("url") or "")


def gold_hit(item: dict[str, Any], sources: list[dict[str, Any]]) -> str | None:
    for record in sources:
        if gold_matches(item, record_url(record)):
            return str(record.get("source_id"))
    return None


def candidate_hit(item: dict[str, Any], candidates: list[dict[str, Any]]) -> str | None:
    for record in candidates:
        if gold_matches(item, str(record.get("url") or "")):
            return str(record.get("candidate_id") or record.get("url"))
    return None


def class_breakdown(rows: list[tuple[str, bool, bool]]) -> dict[str, dict[str, Any]]:
    """rows: (class, found among sources, found at discovery level)."""
    table: dict[str, dict[str, Any]] = {}
    for lane, found, discovered in rows:
        bucket = table.setdefault(lane, {"gold": 0, "found": 0, "discovered": 0})
        bucket["gold"] += 1
        bucket["found"] += int(found)
        bucket["discovered"] += int(discovered)
    for bucket in table.values():
        bucket["recall"] = round(bucket["found"] / bucket["gold"], 3)
        bucket["discovery_recall"] = round(bucket["discovered"] / bucket["gold"], 3)
    return {lane: table[lane] for lane in SOURCE_CLASSES if lane in table}


def score_bundle(case: dict[str, Any], bundle: Path) -> dict[str, Any]:
    sources = load_jsonl(bundle / "sources.jsonl")
    queries = load_jsonl(bundle / "queries.jsonl")
    candidates = load_jsonl(bundle / "candidates.jsonl")
    hits: list[dict[str, Any]] = []
    misses: list[dict[str, Any]] = []
    rows: list[tuple[str, bool, bool]] = []
    discovered_total = 0
    for item in case["gold_sources"]:
        source_id = gold_hit(item, sources)
        candidate_id = None if source_id else candidate_hit(item, candidates)
        target = item.get("url") or f"{item.get('host')}{item.get('path_prefix')}"
        lane = gold_class(item)
        entry = {"gold": target, "source_class": lane, "source_id": source_id, "why": item["why"]}
        if candidate_id:
            entry["candidate"] = candidate_id
        (hits if source_id else misses).append(entry)
        discovered = bool(source_id or candidate_id)
        discovered_total += int(discovered)
        rows.append((lane, bool(source_id), discovered))
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
        "discovery_recall": round(discovered_total / len(case["gold_sources"]), 3),
        "gold_total": len(case["gold_sources"]),
        "gold_found": len(hits),
        "gold_discovered": discovered_total,
        "by_class": class_breakdown(rows),
        "hits": hits,
        "misses": misses,
        "snippet_only": snippet_only,
        "queries_total": len(queries),
        "queries_to_first_authoritative": first_authoritative,
    }


def aggregate_by_class(reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rows: list[tuple[str, bool, bool]] = []
    for report in reports:
        for lane, bucket in report.get("by_class", {}).items():
            for position in range(bucket["gold"]):
                rows.append((lane, position < bucket["found"], position < bucket["discovered"]))
    return class_breakdown(rows)


def score_all(root: Path, cases: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
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
    reports = [item for item in scored.values() if item.get("status") in {"pass", "fail"}]
    gold_total = sum(item["gold_total"] for item in reports)
    return {
        "cases": len(cases),
        "scored": len(reports),
        "not_run": not_run,
        "passed": sum(1 for item in reports if item["status"] == "pass"),
        "recall": round(sum(item["gold_found"] for item in reports) / gold_total, 3) if gold_total else None,
        "discovery_recall": round(sum(item["gold_discovered"] for item in reports) / gold_total, 3) if gold_total else None,
        "by_class": aggregate_by_class(reports),
        "results": scored,
        "failures": failures,
    }


def format_classes(by_class: dict[str, dict[str, Any]]) -> str:
    return ", ".join(
        f"{lane} {bucket['found']}/{bucket['gold']}"
        + (f" (+{bucket['discovered'] - bucket['found']} candidate)" if bucket["discovered"] > bucket["found"] else "")
        for lane, bucket in by_class.items()
    )


def load_benchmark(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    cases = load_jsonl(root / "cases.jsonl")
    results = load_jsonl(root / "results.jsonl")
    errors = validate_cases(cases)
    if len(cases) < MIN_CASES:
        errors.append(f"recall benchmark needs at least {MIN_CASES} cases, found {len(cases)}")
    return cases, results, errors


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.directory).expanduser().resolve()
    try:
        cases, results, errors = load_benchmark(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("Recall benchmark: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    if args.stage == "plan":
        print(f"Recall benchmark: PASS ({len(cases)} cases defined, stage=plan)")
        return 0

    summary = score_all(root, cases, results)
    failures, not_run, scored = summary["failures"], summary["not_run"], summary["results"]
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
                print(f"  by class: {format_classes(report['by_class'])}")
        if summary["by_class"]:
            print(f"- overall recall {summary['recall']}, discovery {summary['discovery_recall']}; by class: {format_classes(summary['by_class'])}")
        for failure in failures:
            print(f"- fail: {failure}")
        for case_id in not_run:
            print(f"- not_run: {case_id}")
    if failures or (args.require_all and not_run):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
