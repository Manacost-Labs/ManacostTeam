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
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from platform_coverage import (
    analyze_records,
    inspection_targets,
    planned_scopes,
    query_platform,
)
from search_support import QUERY_FAMILIES, QUERY_PASSES, next_id, normalize_query
from search_coverage import reader_questions, source_followups

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
        "general": (
            "{topic}",
            "{topic} explained",
            "{topic} guide",
            "{topic} forum discussion {version}",
            "{topic} tournament report {version}",
            "{topic} developer interview {year}",
            "{topic} specialist wiki mechanics",
        ),
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
        "reddit": (
            "site:reddit.com {topic}",
            "site:reddit.com {topic} {version}",
            "site:reddit.com {topic} mistakes",
            "site:reddit.com {topic} discussion {year}",
            "site:reddit.com {entity} {topic}",
        ),
        "x": (
            "site:x.com {topic}",
            "site:x.com {topic} {version}",
            "site:twitter.com {topic} {version}",
            "site:x.com {entity} {topic}",
            "site:x.com {topic} nerf",
            "site:x.com {topic} tournament {year}",
        ),
        "youtube": (
            "site:youtube.com {topic} {version} guide",
            "site:youtube.com {topic} mistakes",
            "site:youtube.com {topic} tournament VOD",
            "site:youtube.com {entity} {topic}",
            "site:youtube.com {topic} analysis {year}",
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
        "reddit": (
            "site:reddit.com {topic} обсуждение",
            "site:reddit.com {topic} {version}",
            "site:reddit.com {topic} ошибки",
            "site:reddit.com {entity} {topic}",
            "site:reddit.com {topic} советы {version}",
        ),
        "x": (
            "site:x.com {topic} {version}",
            "site:twitter.com {topic} {version}",
            "site:x.com {topic} мнение",
            "site:x.com {entity} {topic}",
            "site:x.com {topic} ошибки {version}",
            "site:x.com {topic} разбор {year}",
        ),
        "youtube": (
            "site:youtube.com {topic} {version} гайд",
            "site:youtube.com {topic} ошибки",
            "site:youtube.com {topic} разбор",
            "site:youtube.com {entity} {topic}",
        ),
        "mistakes": ("{topic} ошибки", "{topic} чего избегать"),
        "synergies": ("{topic} синергия", "{entity} взаимодействие"),
        "counterargument": (
            "{topic} переоценен",
            "почему не {topic}",
            "{topic} слабый",
            "{entity} ограничения",
        ),
        "freshness": ("{topic} {year}", "{topic} {version}"),
        "localized": ("{topic} на русском", "{topic} русское сообщество"),
    },
    # Simplified Chinese: Chinese venues have no Reddit/X/YouTube lane; their
    # forums and video site are reached through the localized family.
    "zh": {
        "general": ("{topic}", "{topic} 攻略", "{topic} 解析"),
        "primary": ("{topic} 官方", "{topic} 更新说明 {version}", "{entity} 改动 {version}"),
        "statistics": ("{topic} 数据", "{topic} 胜率 {version}", "{entity} 胜率"),
        "experts": ("{topic} 高分 思路", "{topic} 大神 解析 {version}"),
        "reddit": (),
        "x": (),
        "youtube": (),
        "mistakes": ("{topic} 常见错误",),
        "synergies": ("{topic} 配合", "{entity} 联动"),
        "counterargument": ("{topic} 被高估", "为什么不 {topic}", "{entity} 弱点"),
        "freshness": ("{topic} {year}", "{topic} {version}", "{topic} 最新改动"),
        "localized": (
            "{topic} 国服",
            "site:nga.cn {topic}",
            "site:bilibili.com {topic}",
            "site:iyingdi.com {topic}",
        ),
    },
}
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

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
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


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
        "--entity",
        action="append",
        default=[],
        help="Named entity to expand; repeatable",
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
        help="Template language (en, ru, zh); repeatable; default en, plus ru for Hearthstone",
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
    parser.add_argument(
        "--json", action="store_true", help="Print records as JSON lines"
    )
    parser.add_argument(
        "--coverage-gaps",
        action="store_true",
        help="Queue pending/new queries only for incomplete platform/section/language lanes",
    )
    parser.add_argument(
        "--min-inspected",
        action="append",
        default=[],
        metavar="PLATFORM=N",
        help="Breadth goal for --coverage-gaps; default 1 unique inspected material",
    )
    parser.add_argument("--question-gaps", action="store_true", help="Queue unanswered reader questions and source-grounded followups")
    parser.add_argument("--max-queries", type=int, help="Total query-attempt budget; also counts outstanding planned queries")
    parser.add_argument("--search-phrase", action="append", default=[], metavar="LANGUAGE=PHRASE", help="Localized main-topic phrase (use plan.query_localization.topics for sections)")
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
    manifest: dict[str, Any],
    plan: dict[str, Any] | None,
    sections: list[str],
    topics: list[str],
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
            raise ValueError(
                "manifest.json has no main_question and no sections were given"
            )
        branches.append((None, question))
    localized_topics = (plan or {}).get("query_localization", {}).get("topics", {})
    for section_id, topic in branches:
        if len(topic.split()) > MAX_TOPIC_WORDS and not localized_topics.get(section_id or "__all__"):
            raise ValueError(
                f"branch topic exceeds {MAX_TOPIC_WORDS} words and would produce unusable "
                f"queries; pass a short --topic label instead: {topic[:60]}..."
            )
    return branches


def version_markers(manifest: dict[str, Any], explicit: list[str]) -> list[str]:
    if explicit:
        return list(
            dict.fromkeys(marker.strip() for marker in explicit if marker.strip())
        )
    context = manifest.get("current_context")
    markers: list[str] = []
    if isinstance(context, dict):
        for key in CONTEXT_VERSION_KEYS:
            value = context.get(key)
            if isinstance(value, (str, int, float)) and str(value).strip():
                markers.append(str(value).strip())
    return list(dict.fromkeys(markers))


def render(
    template: str, *, topic: str, year: str, version: str | None, entity: str | None
) -> str | None:
    if "{version}" in template and not version:
        return None
    if "{entity}" in template and not entity:
        return None
    text = template.replace("{topic}", topic).replace("{year}", year)
    text = text.replace("{version}", version or "").replace("{entity}", entity or "")
    return " ".join(text.split())


def localized_phrase(phrases: dict[str, Any], language: str, fallback: str = "") -> str:
    """No translation model is hidden in the template expander."""
    if not isinstance(phrases, dict):
        raise ValueError("search_phrases must map languages to phrases")
    value = phrases.get(language)
    if not value and fallback:
        # Explicit legacy adapter: retain a topic only in its source language.
        detected = "ru" if re.search(r"[А-Яа-яЁё]", fallback) else "en"
        if detected == language:
            value = fallback
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing {language} search_phrases: supply a real localized phrase in query_localization.topics or --search-phrase")
    if language == "en" and re.search(r"[А-Яа-яЁё]", value):
        raise ValueError("English search_phrases must use English names and phrasing, not a Russian title plus a suffix")
    if language == "zh" and not CJK_RE.search(value):
        raise ValueError("zh search_phrases must use Chinese names and phrasing")
    return " ".join(value.split())


def localized_entities(entries: list[dict[str, Any]], language: str) -> list[tuple[str, str]]:
    result = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("entity_id") or not isinstance(entry.get("names"), dict):
            raise ValueError("query_localization.entities require entity_id and names by language")
        names = entry["names"].get(language)
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, list) or not names or any(not isinstance(name, str) or not name.strip() for name in names):
            raise ValueError(f"missing {language} entity names for {entry['entity_id']}")
        for name in names:
            if language == "en" and re.search(r"[А-Яа-яЁё]", name):
                raise ValueError(f"English entity name required for {entry['entity_id']}")
            result.append((entry["entity_id"], name.strip()))
    return result


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
    localization: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    seen = {normalize_query(query) for query in existing_queries}
    ids = set(existing_ids)
    records: list[dict[str, Any]] = []
    planned_at = utc_now()
    localization = localization or {}
    if not isinstance(localization.get("topics", {}), dict) or not isinstance(localization.get("entities", []), list):
        raise ValueError("query_localization requires topics object and entities list")
    for section_id, topic in branches:
        for language in languages:
            phrases = localization.get("topics", {}).get(section_id or "__all__", {})
            localized_topic = localized_phrase(phrases, language, topic)
            if len(localized_topic.split()) > MAX_TOPIC_WORDS:
                raise ValueError(f"search_phrases exceeds {MAX_TOPIC_WORDS} words; supply a concise search phrase")
            named_entities = localized_entities(localization.get("entities", []), language)
            if language == "en" and any(re.search(r"[А-Яа-яЁё]", entity) for entity in entities):
                raise ValueError("English entity name required: use query_localization.entities for localized aliases instead of Cyrillic --entity")
            named_entities += [("", entity) for entity in entities]
            entity_ids = {name: entity_id for entity_id, name in named_entities}
            table = TEMPLATES[language]
            for family in families:
                for template in table.get(family, ()):
                    version_values: list[str | None] = (
                        list(markers) if "{version}" in template else [None]
                    )
                    entity_values: list[str | None] = (
                        [name for _, name in named_entities] if "{entity}" in template else [None]
                    )
                    for version in version_values:
                        for entity in entity_values:
                            query = render(
                                template,
                                topic=localized_topic,
                                year=year,
                                version=version,
                                entity=entity,
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
                                "target_platform": family
                                if family in {"x", "reddit", "youtube"}
                                else "web",
                            }
                            if entity:
                                record["entity"] = entity
                                if entity_ids[entity]:
                                    record["entity_id"] = entity_ids[entity]
                            if version:
                                record["version_marker"] = version
                            if coverage_enabled and section_id:
                                record["deliverable_section_ids"] = [section_id]
                            records.append(record)
    return records


def question_queue(plan: dict[str, Any], executed: list[dict[str, Any]], sources: list[dict[str, Any]],
                   planned: list[dict[str, Any]], languages: list[str], sections: list[str]) -> list[dict[str, Any]]:
    """Turn read-source questions into bounded work, never into new evidence."""
    questions = reader_questions(plan)
    candidates = []
    for question in questions + source_followups(executed, sources, questions):
        if question.get("status", "open") in {"answered", "excluded"}:
            continue
        candidates.append({**question, "reader_question_id": question.get("reader_question_id", question["question_id"]),
                           "queue_reason": question.get("queue_reason") or question.get("gap") or question["question"]})
    priority = {"critical": 0, "material": 1, "contextual": 2}
    candidates.sort(key=lambda item: priority.get(item.get("priority", "material"), 1))
    done = {normalize_query(str(record.get("query", ""))) for record in executed if record.get("status") != "planned"}
    pending = {normalize_query(str(record.get("query", ""))): record for record in planned if record.get("status") == "planned"}
    ids = {str(record.get("query_id")) for record in planned + executed}
    seen_questions = set()
    seen_queries = set(done)
    selected = []
    by_query = {}
    for candidate in candidates:
        if sections and candidate.get("section_id") not in sections:
            continue
        question_key = (candidate["reader_question_id"], normalize_query(candidate["question"]))
        if question_key in seen_questions:
            continue
        seen_questions.add(question_key)
        for language in languages:
            query = localized_phrase(candidate.get("search_phrases", {}), language)
            key = normalize_query(query)
            if key in seen_queries:
                # One search may answer several reader questions. Deduplicate
                # the request, never its question/section/source provenance.
                previous = by_query.get(key)
                if previous is not None:
                    for field, values in (
                        ("reader_question_ids", [candidate["reader_question_id"]]),
                        ("deliverable_section_ids", [candidate["section_id"]] if candidate.get("section_id") else []),
                        ("origin_source_ids", candidate.get("origin_source_ids", [])),
                        ("origin_query_ids", [candidate["origin_query_id"]] if candidate.get("origin_query_id") else []),
                    ):
                        if values:
                            previous[field] = list(dict.fromkeys(previous.get(field, []) + values))
                continue
            seen_queries.add(key)
            previous = pending.get(key)
            query_id = previous["query_id"] if previous else next_id("QRY", ids)
            ids.add(query_id)
            record = {"query_id": query_id, "status": "planned", "pass": "gap", "family": "general", "target_platform": "web",
                      "language": language, "query": query, "topic": candidate["question"], "planned_at": previous.get("planned_at") if previous else utc_now(),
                      "reader_question_id": candidate["reader_question_id"], "queue_reason": candidate["queue_reason"]}
            record["reader_question_ids"] = [candidate["reader_question_id"]]
            record["priority"] = candidate.get("priority", "material")
            if candidate.get("origin_query_id"):
                record["origin_query_ids"] = [candidate["origin_query_id"]]
            for field in ("origin_query_id", "origin_source_ids"):
                if field in candidate:
                    record[field] = candidate[field]
            if candidate.get("section_id"):
                record["deliverable_section_ids"] = [candidate["section_id"]]
            if previous:
                current = record
                record = {**previous, **current}
                record["priority"] = min(
                    (previous.get("priority", "material"), current["priority"]),
                    key=lambda value: priority.get(value, 1),
                )
                for plural, singular in (("reader_question_ids", "reader_question_id"),
                                         ("origin_query_ids", "origin_query_id"),
                                         ("origin_source_ids", None),
                                         ("deliverable_section_ids", None)):
                    old_values = list(previous.get(plural, []))
                    if singular and previous.get(singular):
                        old_values = list(dict.fromkeys([previous[singular]] + old_values))
                        record[singular] = previous[singular]
                    values = list(dict.fromkeys(old_values + current.get(plural, [])))
                    if values:
                        record[plural] = values
            selected.append(record)
            by_query[key] = record
    return sorted(selected, key=lambda item: priority.get(item.get("priority", "material"), 1))


def apply_budget(records: list[dict[str, Any]], executed: list[dict[str, Any]], planned: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None:
        return records
    if type(limit) is not int or limit < 1:
        raise ValueError("research_budget.max_queries / --max-queries must be a positive integer")
    attempted = [record for record in executed if record.get("status") not in {"planned", "skipped"}]
    done_keys = {normalize_query(str(record.get("query", ""))) for record in attempted}
    pending_ids = {record.get("query_id") for record in planned if record.get("status") == "planned" and normalize_query(str(record.get("query", ""))) not in done_keys}
    available = max(0, limit - len(attempted) - len(pending_ids))
    remaining_attempts = max(0, limit - len(attempted))
    chosen = []
    for record in records:
        if len(chosen) >= remaining_attempts:
            break
        if record["query_id"] in pending_ids:
            chosen.append(record)
        elif available:
            chosen.append(record)
            available -= 1
    return chosen


def summarize(records: list[dict[str, Any]]) -> str:
    by_branch: dict[str, dict[str, int]] = {}
    for record in records:
        branch = ",".join(record.get("deliverable_section_ids", [])) or record["topic"]
        by_branch.setdefault(branch, {})
        by_branch[branch][record["family"]] = (
            by_branch[branch].get(record["family"], 0) + 1
        )
    lines = [f"Query plan: {len(records)} new planned queries"]
    for branch, families in by_branch.items():
        parts = ", ".join(
            f"{family}={count}" for family, count in sorted(families.items())
        )
        lines.append(f"- {branch}: {parts}")
    return "\n".join(lines)


def gap_queue(
    fresh: list[dict[str, Any]],
    pending: list[dict[str, Any]],
    executed: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reuse unexecuted planned records; never present them as logged access."""
    done_ids = {record.get("query_id") for record in executed}
    done_queries = {
        normalize_query(record["query"]) for record in executed if record.get("query")
    }
    selected = []
    seen = set()
    for record in pending + fresh:
        if (
            record.get("status") != "planned"
            or record.get("query_id") in done_ids
            or normalize_query(record.get("query", "")) in done_queries
        ):
            continue
        for gap in gaps:
            if (
                query_platform(record) == gap["platform"]
                and (not gap["language"] or record.get("language") == gap["language"])
                and (
                    not gap["section_id"]
                    or gap["section_id"] in record.get("deliverable_section_ids", [])
                )
            ):
                if record["query_id"] not in seen:
                    seen.add(record["query_id"])
                    selected.append({**record, "coverage_gap_reason": gap["reason"]})
                break
    return selected


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.directory).expanduser().resolve()
    try:
        manifest = load_json(root / "manifest.json")
        plan_path = root / "plan.json"
        plan = load_json(plan_path) if plan_path.is_file() else None
        executed = load_jsonl(root / "queries.jsonl")
        planned = load_jsonl(root / PLAN_FILE)
        branches = [] if args.question_gaps else branch_list(manifest, plan, args.section, args.topic)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    depth = str(manifest.get("depth", "deep"))
    if depth not in DEFAULT_FAMILIES_BY_DEPTH:
        print(f"error: manifest depth is invalid: {depth}", file=sys.stderr)
        return 2
    families = list(dict.fromkeys(args.family)) or list(
        DEFAULT_FAMILIES_BY_DEPTH[depth]
    )
    unknown = [family for family in families if family not in QUERY_FAMILIES]
    if unknown:
        print(f"error: unknown query family: {', '.join(unknown)}", file=sys.stderr)
        return 2
    domains = manifest.get("domain_adapters")
    domain_values = (
        {str(item) for item in domains} if isinstance(domains, list) else set()
    )
    default_languages = (
        ["en", "ru"] if domain_values & RUSSIAN_DEFAULT_DOMAINS else ["en"]
    )
    languages = list(dict.fromkeys(args.language)) or default_languages
    unsupported = [language for language in languages if language not in TEMPLATES]
    if unsupported:
        print(
            f"error: unsupported template language: {', '.join(unsupported)}",
            file=sys.stderr,
        )
        return 2
    if (
        "localized" not in families
        and any(language != "en" for language in languages)
        and not (args.coverage_gaps and args.family)
    ):
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
        str(record.get("query", ""))
        for record in executed + planned
        if record.get("query")
    ]
    try:
        if args.question_gaps and args.coverage_gaps:
            raise ValueError("choose --question-gaps or --coverage-gaps, not both")
        localization = (plan or {}).get("query_localization", {})
        if not isinstance(localization, dict):
            raise ValueError("plan.query_localization must be an object")
        for entry in args.search_phrase:
            language, separator, phrase = entry.partition("=")
            if not separator or language not in TEMPLATES or not phrase.strip():
                raise ValueError("--search-phrase expects en|ru|zh=PHRASE")
            localization.setdefault("topics", {}).setdefault("__all__", {})[language] = phrase
        if args.question_gaps:
            records = question_queue(plan or {}, executed, load_jsonl(root / "sources.jsonl"), planned, languages, args.section)
        else:
            records = build_plan(
                branches=branches, families=families, languages=languages,
                entities=list(dict.fromkeys(entity.strip() for entity in args.entity if entity.strip())),
                markers=markers, year=year, existing_queries=existing_queries,
                existing_ids=existing_ids, coverage_enabled="coverage_contract_version" in manifest,
                localization=localization,
            )
        fresh_ids = {record["query_id"] for record in records if record["query_id"] not in existing_ids}
        targets = inspection_targets(args.min_inspected)
        if targets and not args.coverage_gaps:
            raise ValueError(
                "--min-inspected requires --coverage-gaps in the query planner"
            )
        if args.coverage_gaps:
            sections, planned_languages = planned_scopes(root)
            required = list(
                dict.fromkeys(
                    family if family in {"x", "reddit", "youtube"} else "web"
                    for family in families
                )
            )
            report = analyze_records(
                executed,
                load_jsonl(root / "sources.jsonl"),
                required=required,
                sections=args.section or sections,
                languages=args.language or planned_languages or languages,
                min_inspected=targets,
            )
            # Pending queries from an earlier plan are part of the work queue,
            # but --apply appends only fresh records. Completed/failed records
            # stay in the execution ledger and require an explicit retry.
            pending = [record for record in planned if record.get("family") in families]
            records = gap_queue(records, pending, executed, report["gap_details"])
            for record in records:
                if record["query_id"] in fresh_ids:
                    record["pass"] = "gap"
        budget_config = (plan or {}).get("research_budget", {})
        if not isinstance(budget_config, dict):
            raise ValueError("research_budget must be an object")
        budget = budget_config.get("max_queries")
        if budget is None and args.question_gaps:
            budget = {"quick": 10, "deep": 30, "exhaustive": 60}[depth]
        budget = args.max_queries if args.max_queries is not None else budget
        uncapped_count = len(records)
        records = apply_budget(records, executed, planned, budget)
        if len(records) < uncapped_count:
            print(f"budget limit: queued {len(records)}/{uncapped_count}; remaining questions stay unresolved", file=sys.stderr)
    except (OSError, ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for pass_name in {record["pass"] for record in records}:
        assert pass_name in QUERY_PASSES

    if args.json:
        for record in records:
            print(json.dumps(record, ensure_ascii=False))
    else:
        print(summarize(records))
        if args.coverage_gaps:
            print(
                f"- incomplete lanes: {len(report['gap_details'])}; queued queries: {len(records)}"
            )
            if report["gap_details"] and not records:
                print(
                    "- no untried templates remain: add named entities/branch labels, inspect original candidates, or document an unresolved gap"
                )
        if not markers:
            print("- note: no version markers; version-bound templates were skipped")
    new_records = [record for record in records if record["query_id"] in fresh_ids]
    updates = {record["query_id"]: record for record in records
               if args.question_gaps and record["query_id"] not in fresh_ids}
    if args.apply and updates:
        # Pending work is editable; executed evidence remains append-only.
        # Persist merged question provenance even when no new query was added.
        from os import replace
        from tempfile import NamedTemporaryFile
        revised = [updates.get(record.get("query_id"), record) for record in planned] + new_records
        with NamedTemporaryFile("w", encoding="utf-8", dir=root, delete=False) as stream:
            temporary = Path(stream.name)
            for record in revised:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        try:
            replace(temporary, root / PLAN_FILE)
        finally:
            temporary.unlink(missing_ok=True)
        print(f"Updated pending query provenance; added {len(new_records)} records", file=sys.stderr)
    elif args.apply and new_records:
        with (root / PLAN_FILE).open("a", encoding="utf-8") as stream:
            for record in new_records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(
            f"Appended {len(new_records)} records to {PLAN_FILE}",
            file=sys.stderr if args.json else sys.stdout,
        )
    elif not args.apply and not args.json:
        print("Preview only; use --apply to write the plan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
