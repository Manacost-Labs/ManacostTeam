#!/usr/bin/env python3
"""Audit platform coverage using executed queries linked to inspected sources.

``--write-map`` also writes ``coverage-map.json``: for every source class
(official, statistics, reddit, x, youtube, chinese, podcast, web) whether it
was searched, what was found, or why it was unavailable or not searched. The
bundle validator recomputes the map from the ledgers and requires it for a
schema 1.2 final report.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit, urlunsplit

from source_classes import SOURCE_CLASSES, query_lane, source_class

PLATFORMS = ("x", "reddit", "youtube", "web")
INSPECTED = {
    "full",
    "partial",
    "full_text",
    "partial_text",
    "transcript",
    "timestamped_transcript",
    "structured_data",
}
SUCCESS = {"executed", "completed", "partial", "no_results"}
FAILURE = {"blocked", "failed", "error", "unavailable", "skipped"}
MAP_FILE = "coverage-map.json"
MAP_SCHEMA = "1.0"
MAP_STATUSES = ("found", "searched_not_found", "unavailable", "not_searched")
REASON_REQUIRED = {"unavailable", "not_searched"}
FAILURE_REASON_FIELDS = ("failure_reason", "blocked_reason", "status_reason", "error", "note")


def inspection_targets(values: list[str]) -> dict[str, int]:
    """Parse optional PLATFORM=N breadth goals shared by audit and planner."""
    targets = {}
    for value in values:
        platform, separator, count = value.partition("=")
        if (
            not separator
            or platform not in PLATFORMS
            or not re.fullmatch(r"[1-9][0-9]*", count)
        ):
            raise ValueError(
                "--min-inspected expects x|reddit|youtube|web=N, with N >= 1"
            )
        if platform in targets:
            raise ValueError(f"duplicate --min-inspected target: {platform}")
        targets[platform] = int(count)
    return targets


def platform_for_url(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return "web"
    for platform, domains in {
        "x": ("x.com", "twitter.com"),
        "reddit": ("reddit.com", "redd.it"),
        "youtube": ("youtube.com", "youtu.be"),
    }.items():
        if any(host == domain or host.endswith("." + domain) for domain in domains):
            return platform
    return "web"


def query_platform(record: dict) -> str:
    declared = record.get("target_platform")
    if declared in PLATFORMS:
        return declared
    family, query = (
        str(record.get("family", "")).lower(),
        str(record.get("query", "")).lower(),
    )
    for platform, sites in {
        "x": ("site:x.com", "site:twitter.com"),
        "reddit": ("site:reddit.com",),
        "youtube": ("site:youtube.com",),
    }.items():
        if family == platform or any(site in query for site in sites):
            return platform
    return "web"


def string_list(record: dict, field: str) -> list[str]:
    values = record.get(field, [])
    if not isinstance(values, list) or any(
        not isinstance(value, str) or not value for value in values
    ):
        raise ValueError(f"{field}: expected a list of nonempty strings")
    return values


def index_records(records: list[dict], field: str) -> dict[str, dict]:
    indexed = {}
    for record in records:
        if not isinstance(record, dict):
            raise TypeError("ledger records must be objects")
        identity = record.get(field)
        if not isinstance(identity, str) or not identity:
            raise ValueError(f"missing {field}")
        if identity in indexed:
            raise ValueError(f"duplicate {field}: {identity}")
        indexed[identity] = record
    return indexed


def inspected_url(source: dict) -> str | None:
    if source.get("access_integrity") not in INSPECTED:
        return None
    for field in ("canonical_url", "final_url", "url", "requested_url"):
        url = source.get(field)
        if not isinstance(url, str):
            continue
        try:
            parts = urlsplit(url)
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                continue
            return urlunsplit(
                (
                    parts.scheme.lower(),
                    parts.netloc.lower(),
                    parts.path,
                    parts.query,
                    "",
                )
            )
        except ValueError:
            continue
    return None


def inspection_identity(url: str) -> str:
    """Count a video, X post or Reddit thread once across share URL variants.

    Unknown URL forms retain their full URL, including query parameters. This
    identifies duplicate access; it does not establish independent authorship.
    """
    parts = urlsplit(url)
    platform = platform_for_url(url)
    host = parts.hostname or ""
    if platform == "youtube":
        video = None
        if host == "youtu.be" or host.endswith(".youtu.be"):
            video = parts.path.strip("/")
        elif parts.path.rstrip("/") == "/watch":
            video = parse_qs(parts.query).get("v", [None])[0]
        else:
            match = re.fullmatch(
                r"/(?:shorts|embed|live)/([A-Za-z0-9_-]+)/?", parts.path
            )
            if match:
                video = match.group(1)
        if video and re.fullmatch(r"[A-Za-z0-9_-]+", video):
            return "youtube:video:" + video
    elif platform == "x":
        match = re.search(r"/status/(\d+)(?:/|$)", parts.path)
        if match:
            return "x:post:" + match.group(1)
    elif platform == "reddit":
        match = re.search(r"/comments/([A-Za-z0-9]+)(?:/|$)", parts.path)
        if host == "redd.it" or host.endswith(".redd.it"):
            match = re.fullmatch(r"/([A-Za-z0-9]+)/?", parts.path)
        if match:
            return "reddit:thread:" + match.group(1).lower()
    return url


def analyze_records(
    queries: list[dict],
    sources: list[dict],
    *,
    required: list[str],
    sections: list[str] | None = None,
    languages: list[str] | None = None,
    min_inspected: dict[str, int] | None = None,
) -> dict:
    if set(required) - set(PLATFORMS):
        raise ValueError("unknown required platform")
    targets = dict.fromkeys(PLATFORMS, 1)
    for platform, count in (min_inspected or {}).items():
        if platform not in PLATFORMS or type(count) is not int or count < 1:
            raise ValueError(
                "min_inspected must map known platforms to positive integers"
            )
        targets[platform] = count
    query_index, source_index = (
        index_records(queries, "query_id"),
        index_records(sources, "source_id"),
    )
    links = {
        identity: set(string_list(query, "result_source_ids"))
        for identity, query in query_index.items()
    }
    for identity, query in query_index.items():
        string_list(query, "deliverable_section_ids")
        if query.get("status") not in SUCCESS | FAILURE | {"planned"}:
            raise ValueError(f"{identity}: unknown query status")
        if links[identity] - source_index.keys():
            raise ValueError(
                f"{identity}: result_source_ids references an unknown source"
            )
    for identity, source in source_index.items():
        for query_id in string_list(source, "found_by_query_ids"):
            if query_id not in query_index:
                raise ValueError(
                    f"{identity}: found_by_query_ids references an unknown query"
                )
            links[query_id].add(identity)
    for identity, query in query_index.items():
        if query["status"] == "no_results" and links[identity]:
            raise ValueError(f"{identity}: no_results query cannot link to sources")

    def coverage(section=None, language=None):
        lanes = {
            platform: {
                "executed_queries": 0,
                "failed_queries": 0,
                "inspected_sources": 0,
                "source_ids": [],
                "duplicate_source_ids": [],
            }
            for platform in PLATFORMS
        }
        identities = {platform: set() for platform in PLATFORMS}
        matched_sources = set()
        for identity, query in query_index.items():
            if section and section not in query.get("deliverable_section_ids", []):
                continue
            if language and language != query.get("language"):
                continue
            if not query.get("executed_at") or query.get("status") == "planned":
                continue
            platform = query_platform(query)
            lane = lanes[platform]
            if query["status"] in FAILURE:
                lane["failed_queries"] += 1
                continue
            lane["executed_queries"] += 1
            for source_id in sorted(links[identity]):
                source = source_index[source_id]
                url = inspected_url(source)
                if (
                    url
                    and platform_for_url(url) == platform
                    and source_id not in matched_sources
                ):
                    matched_sources.add(source_id)
                    key = inspection_identity(url)
                    if key in identities[platform]:
                        lane["duplicate_source_ids"].append(source_id)
                        continue
                    identities[platform].add(key)
                    lane["source_ids"].append(source_id)
                    lane["inspected_sources"] += 1
        gaps = []
        for platform in required:
            lane = lanes[platform]
            if (
                not lane["executed_queries"]
                or lane["inspected_sources"] < targets[platform]
            ):
                gaps.append(
                    {
                        "platform": platform,
                        "section_id": section,
                        "language": language,
                        "reason": "no_executed_search"
                        if not lane["executed_queries"]
                        else "no_linked_inspection"
                        if not lane["inspected_sources"]
                        else "insufficient_inspections",
                        "failed_queries": lane["failed_queries"],
                        "inspected_sources": lane["inspected_sources"],
                        "minimum_inspected": targets[platform],
                    }
                )
        return lanes, gaps, matched_sources

    platforms, global_gaps, linked_sources = coverage()
    scopes, scope_gaps = [], []
    if sections or languages:
        for section in sections or [None]:
            for language in languages or [None]:
                lanes, gaps, _ = coverage(section, language)
                scopes.append(
                    {"section_id": section, "language": language, "platforms": lanes}
                )
                scope_gaps.extend(gaps)
    gaps = scope_gaps if scopes else global_gaps
    return {
        "verdict": "partial" if gaps else "covered",
        "required_platforms": required,
        "minimum_inspected": {platform: targets[platform] for platform in required},
        "gaps": sorted({gap["platform"] for gap in gaps}),
        "gap_details": gaps,
        "platforms": platforms,
        "scopes": scopes,
        "unlinked_inspected_source_ids": sorted(
            identity
            for identity, source in source_index.items()
            if inspected_url(source) and identity not in linked_sources
        ),
        "limitation": "Coverage proves logged access and query-to-source linkage, not representativeness, source independence or factual corroboration.",
    }


def read_ledger(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{path.name}:{line_number}: malformed JSON: {exc.msg}"
            ) from exc
        if not isinstance(record, dict):
            raise TypeError(
                f"{path.name}:{line_number}: ledger record must be an object"
            )
        records.append(record)
    return records


def planned_scopes(directory: Path) -> tuple[list[str], list[str]]:
    """Use planned sections/languages, including branches never executed."""
    sections = []
    has_outline = False
    plan = directory / "plan.json"
    if plan.is_file():
        data = json.loads(plan.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("plan.json: expected an object")
        has_outline = "deliverable_outline" in data
        outline = data.get("deliverable_outline", [])
        if not isinstance(outline, list) or any(
            not isinstance(item, dict) for item in outline
        ):
            raise ValueError("plan.json: deliverable_outline must be a list of objects")
        sections = [
            item["section_id"]
            for item in outline
            if item.get("status") != "excluded"
            and isinstance(item.get("section_id"), str)
        ]
    planned = read_ledger(directory / "query-plan.jsonl")
    languages = sorted(
        {
            record["language"]
            for record in planned
            if isinstance(record.get("language"), str) and record["language"]
        }
    )
    if not has_outline:
        sections = sorted(
            {
                section
                for record in planned
                for section in string_list(record, "deliverable_section_ids")
            }
        )
    return list(dict.fromkeys(sections)), languages


def map_lanes(queries: list[dict], sources: list[dict]) -> dict[str, dict]:
    """Per source class: searches, failures and inspected material from the ledgers."""
    lanes = {
        lane: {"queries_executed": 0, "queries_failed": 0, "inspected_sources": 0, "source_ids": [], "failure_reasons": []}
        for lane in SOURCE_CLASSES
    }
    for query in queries:
        if not query.get("executed_at") or query.get("status") in {"planned", "skipped"}:
            continue
        lane = lanes[query_lane(query)]
        if query.get("status") in FAILURE:
            lane["queries_failed"] += 1
            reason = next((str(query[field]) for field in FAILURE_REASON_FIELDS if query.get(field)), None)
            if reason and reason not in lane["failure_reasons"]:
                lane["failure_reasons"].append(reason)
        else:
            lane["queries_executed"] += 1
    seen: dict[str, set[str]] = {lane: set() for lane in SOURCE_CLASSES}
    for source in sources:
        url = inspected_url(source)
        if not url:
            continue
        lane = source_class(url, source.get("source_type"))
        key = inspection_identity(url)
        if key in seen[lane]:
            continue
        seen[lane].add(key)
        lanes[lane]["inspected_sources"] += 1
        lanes[lane]["source_ids"].append(str(source.get("source_id")))
    for lane in lanes.values():
        lane["status"] = (
            "found" if lane["inspected_sources"]
            else "searched_not_found" if lane["queries_executed"]
            else "unavailable" if lane["queries_failed"]
            else "not_searched"
        )
    return lanes


def build_map(queries: list[dict], sources: list[dict], previous: dict | None = None,
              reasons: dict[str, str] | None = None) -> dict:
    """Keep a researcher's reason while the lane status it explains is unchanged."""
    lanes = map_lanes(queries, sources)
    old = (previous or {}).get("lanes", {})
    for name, lane in lanes.items():
        reason = (reasons or {}).get(name)
        if reason is None and old.get(name, {}).get("status") == lane["status"]:
            reason = old[name].get("reason")
        if reason is None and lane["status"] == "unavailable" and lane["failure_reasons"]:
            reason = "; ".join(lane["failure_reasons"])
        lane["reason"] = reason
    return {
        "schema_version": MAP_SCHEMA,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "lanes": lanes,
        "summary": {status: [name for name, lane in lanes.items() if lane["status"] == status] for status in MAP_STATUSES},
        "limitation": "The map records logged search attempts and inspected material per source class; it does not prove the lane was searched well.",
    }


def check_map(document: object, queries: list[dict], sources: list[dict]) -> list[str]:
    """Errors when the map is stale, incomplete, or leaves a gap unexplained."""
    if not isinstance(document, dict) or document.get("schema_version") != MAP_SCHEMA:
        return [f"{MAP_FILE}: schema_version must be {MAP_SCHEMA}"]
    lanes = document.get("lanes")
    if not isinstance(lanes, dict):
        return [f"{MAP_FILE}: lanes must be an object"]
    errors = []
    expected = map_lanes(queries, sources)
    for name, wanted in expected.items():
        lane = lanes.get(name)
        if not isinstance(lane, dict):
            errors.append(f"{MAP_FILE}: missing lane {name}")
            continue
        stale = [field for field in ("status", "queries_executed", "queries_failed", "inspected_sources") if lane.get(field) != wanted[field]]
        if stale:
            errors.append(f"{MAP_FILE}: lane {name} disagrees with the ledgers ({', '.join(stale)}); rerun platform_coverage.py --write-map")
        reason = lane.get("reason")
        if wanted["status"] in REASON_REQUIRED and (not isinstance(reason, str) or not reason.strip()):
            errors.append(f"{MAP_FILE}: lane {name} is {wanted['status']} without a reason; add --reason {name}=TEXT")
    return errors


def parse_reasons(values: list[str]) -> dict[str, str]:
    reasons = {}
    for value in values:
        lane, separator, text = value.partition("=")
        if not separator or lane not in SOURCE_CLASSES or not text.strip():
            raise ValueError(f"--reason expects {'|'.join(SOURCE_CLASSES)}=TEXT")
        reasons[lane] = text.strip()
    return reasons


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--require", action="append", choices=PLATFORMS, default=[])
    parser.add_argument("--section", action="append", default=[])
    parser.add_argument("--language", action="append", default=[])
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--write-map", action="store_true", help=f"Write {MAP_FILE} for the bundle validator")
    parser.add_argument("--reason", action="append", default=[], metavar="CLASS=TEXT",
                        help="Why a source class is unavailable or not searched; repeatable")
    parser.add_argument(
        "--min-inspected",
        action="append",
        default=[],
        metavar="PLATFORM=N",
        help="Unique inspected materials needed per selected section/language; default 1",
    )
    args = parser.parse_args()
    try:
        planned_sections, planned_languages = planned_scopes(args.directory)
        report = analyze_records(
            read_ledger(args.directory / "queries.jsonl"),
            read_ledger(args.directory / "sources.jsonl"),
            required=list(dict.fromkeys(args.require or PLATFORMS)),
            sections=args.section or planned_sections,
            languages=args.language or planned_languages,
            min_inspected=inspection_targets(args.min_inspected),
        )
    except (ValueError, TypeError, OSError) as exc:
        print(json.dumps({"verdict": "invalid", "error": str(exc)}, ensure_ascii=False))
        return 2
    if args.write_map:
        try:
            queries = read_ledger(args.directory / "queries.jsonl")
            sources = read_ledger(args.directory / "sources.jsonl")
            path = args.directory / MAP_FILE
            previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
            document = build_map(queries, sources, previous, parse_reasons(args.reason))
            path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except (ValueError, TypeError, OSError) as exc:
            print(json.dumps({"verdict": "invalid", "error": str(exc)}, ensure_ascii=False))
            return 2
        problems = check_map(document, queries, sources)
        report["coverage_map"] = {"path": str(path), "summary": document["summary"], "problems": problems}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.write_map and report["coverage_map"]["problems"]:
        return 1
    return int(args.strict and report["verdict"] != "covered")


if __name__ == "__main__":
    raise SystemExit(main())
