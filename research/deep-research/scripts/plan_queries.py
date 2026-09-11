#!/usr/bin/env python3
"""Generate a deterministic query matrix for a research bundle.

The matrix expands every research branch (a ``plan.json`` section or the main
question) across canonical query families, languages, entities, and version
markers. It writes ``query-plan.jsonl`` so the executed ``queries.jsonl`` ledger
can be compared against what was planned by ``search_coverage.py``.

Planned records are not executed queries. Copy a record into ``queries.jsonl``
with ``executed_at``, ``status``, and ``result_source_ids`` when it has been run.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from search_support import QUERY_FAMILIES, QUERY_PASSES, next_id, normalize_query

PLAN_FILE = "query-plan.jsonl"
MAX_TOPIC_WORDS = 12

DEFAULT_FAMILIES_BY_DEPTH: dict[str, tuple[str, ...]] = {
    "quick": ("primary", "statistics", "experts", "counterargument", "freshness"),
    "deep": (
        "general",
        "primary",
        "statistics",
        "experts",
        "reddit",
        "x",
        "youtube",
        "mistakes",
        "counterargument",
        "freshness",
    ),
    "exhaustive": (
        "general",
        "primary",
        "statistics",
        "experts",
        "reddit",
        "x",
        "youtube",
        "mistakes",
        "synergies",
        "counterargument",
        "freshness",
    ),
}

FAMILY_PASS: dict[str, str] = {
    "counterargument": "contradiction",
    "freshness": "freshness",
    "localized": "collection",
}

# Placeholders: {topic}, {version}, {year}, {entity}. A template that needs
# {version} or {entity} is skipped when no value is available.
TEMPLATES: dict[str, dict[str, tuple[str, ...]]] = {
    "en": {
        "general": ("{topic}", "{topic} explained", "{topic} guide"),
        "primary": (
            "{topic} official",
            "{topic} official documentation",
            "{topic} patch notes {version}",
            "{entity} official change {version}",
        ),
        "statistics": (
            "{topic} statistics",
            "{topic} data {version}",
            "{topic} methodology sample size",
            "{entity} win rate {version}",
        ),
        "experts": (
            "{topic} expert analysis",
            "{topic} high rank guide {version}",
            "{topic} coaching",
        ),
        "reddit": ("site:reddit.com {topic}", "site:reddit.com {topic} {version}"),
        "x": ("site:x.com {topic}", "{topic} {version} discussion"),
        "youtube": (
            "{topic} {version} guide video",
            "{topic} mistakes video",
            "{topic} tournament VOD",
        ),
        "mistakes": ("{topic} mistakes", "{topic} common errors avoid"),
        "synergies": ("{topic} synergy", "{entity} interaction {topic}"),
        "counterargument": (
            "{topic} overrated",
            "why not {topic}",
            "{topic} wrong",
            "{entity} overrated",
        ),
        "freshness": ("{topic} {year}", "{topic} {version}", "{topic} latest change"),
        "localized": (),
    },
    "ru": {
        "general": ("{topic}", "{topic} объяснение", "{topic} гайд"),
        "primary": (
            "{topic} официально",
            "{topic} описание обновления {version}",
            "{entity} изменение {version}",
        ),
        "statistics": (
            "{topic} статистика",
            "{topic} доля побед {version}",
            "{entity} статистика {version}",
        ),
        "experts": ("{topic} разбор", "{topic} гайд легенда {version}"),
        "reddit": ("{topic} обсуждение форум",),
        "x": ("{topic} {version} мнение",),
        "youtube": ("{topic} {version} видео гайд", "{topic} ошибки видео"),
        "mistakes": ("{topic} ошибки", "{topic} чего избегать"),
        "synergies": ("{topic} синергия", "{entity} взаимодействие"),
        "counterargument": ("{topic} переоценен", "почему не {topic}", "{topic} слабый"),
        "freshness": ("{topic} {year}", "{topic} {version}"),
        "localized": ("{topic} на русском", "{topic} русское сообщество"),
    },
}

CONTEXT_VERSION_KEYS = (
    "patch",
    "client_patch",
    "balance_patch",
    "latest_battlegrounds_balance_patch",
    "latest_substantive_balance",
    "version",
    "season",
    "expansion",
    "release",
)
RUSSIAN_DEFAULT_DOMAINS = frozenset({"hearthstone"})


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="Research bundle directory")
    parser.add_argument(
        "--section",
        action="append",
        default=[],
        help="Restrict to a plan.json section ID; repeatable",
    )
    parser.add_argument(
        "--topic",
        action="append",
        default=[],
        help="Extra branch topic when plan.json has no sections; repeatable",
    )
    parser.add_argument(
        "--entity", action="append", default=[], help="Named entity to expand; repeatable"
    )
    parser.add_argument(
        "--version-marker",
        action="append",
        default=[],
        help="Version, patch, or season marker; defaults to manifest current_context",
    )
    parser.add_argument(
        "--language",
        action="append",
        default=[],
        help="Template language (en, ru); repeatable; default en",
    )
    parser.add_argument(
        "--family",
        action="append",
        default=[],
        help="Restrict to a canonical family; repeatable; default depends on depth",
    )
    parser.add_argument(
        "--apply", action="store_true", help=f"Append new records to {PLAN_FILE}"
    )
    parser.add_argument("--json", action="store_true", help="Print records as JSON lines")
    return parser.parse_args(argv)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: expected an object")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"{path.name}:{number}: record must be an object")
        records.append(item)
    return records


def branch_list(
    manifest: dict[str, Any], plan: dict[str, Any] | None, sections: list[str], topics: list[str]
) -> list[tuple[str | None, str]]:
    """Return ``(section_id, topic)`` pairs to expand."""

    branches: list[tuple[str | None, str]] = []
    outline = plan.get("deliverable_outline", []) if plan else []
    for item in outline:
        if not isinstance(item, dict):
            continue
        section_id = item.get("section_id")
        if sections and section_id not in sections:
            continue
        if item.get("status") == "excluded":
            continue
        topic = item.get("working_title") or item.get("reader_question")
        if isinstance(section_id, str) and isinstance(topic, str) and topic.strip():
            branches.append((section_id, topic.strip()))
    if sections and not branches:
        raise ValueError("no matching plan.json sections for --section")
    for topic in topics:
        if topic.strip():
            branches.append((None, topic.strip()))
    if not branches:
        question = str(manifest.get("main_question", "")).strip()
        if not question:
            raise ValueError("manifest.json has no main_question and no sections were given")
        branches.append((None, question))
    for _section_id, topic in branches:
        if len(topic.split()) > MAX_TOPIC_WORDS:
            raise ValueError(
                f"branch topic exceeds {MAX_TOPIC_WORDS} words and would produce unusable "
                f"queries; pass a short --topic label instead: {topic[:60]}..."
            )
    return branches


def version_markers(manifest: dict[str, Any], explicit: list[str]) -> list[str]:
    if explicit:
        return list(dict.fromkeys(marker.strip() for marker in explicit if marker.strip()))
    context = manifest.get("current_context")
    markers: list[str] = []
    if isinstance(context, dict):
        for key in CONTEXT_VERSION_KEYS:
            value = context.get(key)
            if isinstance(value, (str, int, float)) and str(value).strip():
                markers.append(str(value).strip())
    return list(dict.fromkeys(markers))


def render(template: str, *, topic: str, year: str, version: str | None, entity: str | None) -> str | None:
    if "{version}" in template and not version:
        return None
    if "{entity}" in template and not entity:
        return None
    text = template.replace("{topic}", topic).replace("{year}", year)
    text = text.replace("{version}", version or "").replace("{entity}", entity or "")
    return " ".join(text.split())


def build_plan(
    *,
    branches: list[tuple[str | None, str]],
    families: list[str],
    languages: list[str],
    entities: list[str],
    markers: list[str],
    year: str,
    existing_queries: list[str],
    existing_ids: set[str],
    coverage_enabled: bool,
) -> list[dict[str, Any]]:
    seen = {normalize_query(query) for query in existing_queries}
    ids = set(existing_ids)
    records: list[dict[str, Any]] = []
    planned_at = utc_now()
    for section_id, topic in branches:
        for language in languages:
            table = TEMPLATES[language]
            for family in families:
                for template in table.get(family, ()):
                    version_values: list[str | None] = list(markers) if "{version}" in template else [None]
                    entity_values: list[str | None] = list(entities) if "{entity}" in template else [None]
                    for version in version_values:
                        for entity in entity_values:
                            query = render(
                                template, topic=topic, year=year, version=version, entity=entity
                            )
                            if not query:
                                continue
                            key = normalize_query(query)
                            if key in seen:
                                continue
                            seen.add(key)
                            query_id = next_id("QRY", ids)
                            ids.add(query_id)
                            record: dict[str, Any] = {
                                "query_id": query_id,
                                "pass": FAMILY_PASS.get(family, "discovery"),
                                "family": family,
                                "language": language,
                                "query": query,
                                "topic": topic,
                                "status": "planned",
                                "planned_at": planned_at,
                            }
                            if entity:
                                record["entity"] = entity
                            if version:
                                record["version_marker"] = version
                            if coverage_enabled and section_id:
                                record["deliverable_section_ids"] = [section_id]
                            records.append(record)
    return records


def summarize(records: list[dict[str, Any]]) -> str:
    by_branch: dict[str, dict[str, int]] = {}
    for record in records:
        branch = ",".join(record.get("deliverable_section_ids", [])) or record["topic"]
        by_branch.setdefault(branch, {})
        by_branch[branch][record["family"]] = by_branch[branch].get(record["family"], 0) + 1
    lines = [f"Query plan: {len(records)} new planned queries"]
    for branch, families in by_branch.items():
        parts = ", ".join(f"{family}={count}" for family, count in sorted(families.items()))
        lines.append(f"- {branch}: {parts}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.directory).expanduser().resolve()
    try:
        manifest = load_json(root / "manifest.json")
        plan_path = root / "plan.json"
        plan = load_json(plan_path) if plan_path.is_file() else None
        executed = load_jsonl(root / "queries.jsonl")
        planned = load_jsonl(root / PLAN_FILE)
        branches = branch_list(manifest, plan, args.section, args.topic)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    depth = str(manifest.get("depth", "deep"))
    if depth not in DEFAULT_FAMILIES_BY_DEPTH:
        print(f"error: manifest depth is invalid: {depth}", file=sys.stderr)
        return 2
    families = list(dict.fromkeys(args.family)) or list(DEFAULT_FAMILIES_BY_DEPTH[depth])
    unknown = [family for family in families if family not in QUERY_FAMILIES]
    if unknown:
        print(f"error: unknown query family: {', '.join(unknown)}", file=sys.stderr)
        return 2
    domains = manifest.get("domain_adapters")
    domain_values = {str(item) for item in domains} if isinstance(domains, list) else set()
    default_languages = ["en", "ru"] if domain_values & RUSSIAN_DEFAULT_DOMAINS else ["en"]
    languages = list(dict.fromkeys(args.language)) or default_languages
    unsupported = [language for language in languages if language not in TEMPLATES]
    if unsupported:
        print(f"error: unsupported template language: {', '.join(unsupported)}", file=sys.stderr)
        return 2
    if "localized" not in families and any(language != "en" for language in languages):
        families.append("localized")

    as_of = str(manifest.get("as_of", ""))
    year = as_of[:4] if len(as_of) >= 4 and as_of[:4].isdigit() else utc_now()[:4]
    markers = version_markers(manifest, args.version_marker)
    existing_ids = {
        str(record.get("query_id"))
        for record in executed + planned
        if isinstance(record.get("query_id"), str)
    }
    existing_queries = [
        str(record.get("query", "")) for record in executed + planned if record.get("query")
    ]
    records = build_plan(
        branches=branches,
        families=families,
        languages=languages,
        entities=list(dict.fromkeys(entity.strip() for entity in args.entity if entity.strip())),
        markers=markers,
        year=year,
        existing_queries=existing_queries,
        existing_ids=existing_ids,
        coverage_enabled="coverage_contract_version" in manifest,
    )
    for pass_name in {record["pass"] for record in records}:
        assert pass_name in QUERY_PASSES

    if args.json:
        for record in records:
            print(json.dumps(record, ensure_ascii=False))
    else:
        print(summarize(records))
        if not markers:
            print("- note: no version markers; version-bound templates were skipped")
    if args.apply and records:
        with (root / PLAN_FILE).open("a", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"Appended {len(records)} records to {PLAN_FILE}")
    elif not args.apply and not args.json:
        print("Preview only; use --apply to write the plan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
