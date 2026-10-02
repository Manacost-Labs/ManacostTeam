#!/usr/bin/env python3
"""Audit platform coverage using executed queries linked to inspected sources."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

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
SUCCESS = {"completed", "partial", "no_results"}
FAILURE = {"blocked", "failed", "error", "unavailable"}


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
) -> dict:
    if set(required) - set(PLATFORMS):
        raise ValueError("unknown required platform")
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
            if not lane["executed_queries"] or not lane["inspected_sources"]:
                gaps.append(
                    {
                        "platform": platform,
                        "section_id": section,
                        "language": language,
                        "reason": "no_executed_search"
                        if not lane["executed_queries"]
                        else "no_linked_inspection",
                        "failed_queries": lane["failed_queries"],
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--require", action="append", choices=PLATFORMS, default=[])
    parser.add_argument("--section", action="append", default=[])
    parser.add_argument("--language", action="append", default=[])
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    try:
        planned_sections, planned_languages = planned_scopes(args.directory)
        report = analyze_records(
            read_ledger(args.directory / "queries.jsonl"),
            read_ledger(args.directory / "sources.jsonl"),
            required=list(dict.fromkeys(args.require or PLATFORMS)),
            sections=args.section or planned_sections,
            languages=args.language or planned_languages,
        )
    except (ValueError, TypeError, OSError) as exc:
        print(json.dumps({"verdict": "invalid", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(args.strict and report["verdict"] != "covered")


if __name__ == "__main__":
    raise SystemExit(main())
