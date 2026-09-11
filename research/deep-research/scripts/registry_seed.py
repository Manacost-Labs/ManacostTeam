#!/usr/bin/env python3
"""Seed a research bundle with direct opens from a domain source registry.

Known venues should be opened before any search engine is consulted. The
registry lists hosts, datasets, creators, communities, and Chinese venues for
a domain; this script filters them by game mode and writes planned records
into ``query-plan.jsonl`` so ``search_coverage.py`` can report which known
venues were actually consulted. Registry presence never replaces inspection.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from search_support import QUERY_FAMILIES, infer_game_mode, next_id

DEFAULT_REGISTRY = Path(__file__).resolve().parents[1] / "references/domains/hearthstone-sources.json"
PLAN_FILE = "query-plan.jsonl"
SECTIONS = ("hosts", "datasets", "creators", "communities", "chinese")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="Research bundle directory")
    parser.add_argument("--registry", help=f"Registry JSON; default {DEFAULT_REGISTRY.name}")
    parser.add_argument(
        "--mode",
        choices=("battlegrounds", "constructed", "arena", "all"),
        help="Game mode filter; default inferred from manifest current_context",
    )
    parser.add_argument(
        "--section",
        action="append",
        default=[],
        choices=SECTIONS,
        help="Registry sections to seed; default all",
    )
    parser.add_argument(
        "--deliverable-section",
        action="append",
        default=[],
        help="plan.json section ID to attach to seeded records; repeatable",
    )
    parser.add_argument("--apply", action="store_true", help=f"Append to {PLAN_FILE}")
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
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_registry(path: Path) -> dict[str, Any]:
    registry = load_json(path)
    if registry.get("registry_version") != "1.0":
        raise ValueError("unsupported registry_version")
    for section in SECTIONS:
        entries = registry.get(section, [])
        if not isinstance(entries, list):
            raise ValueError(f"registry section {section} must be a list")
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                raise ValueError(f"registry section {section} has an entry without id")
            if entry["id"] in seen:
                raise ValueError(f"duplicate registry id {entry['id']}")
            seen.add(entry["id"])
            families = entry.get("use_for", [])
            if not isinstance(families, list) or not families:
                raise ValueError(f"registry entry {entry['id']} needs use_for families")
            for family in families:
                if family not in QUERY_FAMILIES:
                    raise ValueError(f"registry entry {entry['id']} uses unknown family {family!r}")
    return registry


def mode_matches(entry: dict[str, Any], mode: str) -> bool:
    modes = entry.get("modes", ["all"])
    if not isinstance(modes, list):
        return False
    return mode == "all" or "all" in modes or mode in modes


def entry_urls(section: str, entry: dict[str, Any]) -> list[str]:
    if section == "creators":
        urls = entry.get("observed_urls", [])
    elif section == "communities":
        urls = [entry.get("url")]
    elif section == "datasets":
        return []
    else:
        urls = entry.get("entry_urls", [])
    return [url for url in urls if isinstance(url, str) and url]


def seed_records(
    registry: dict[str, Any],
    *,
    mode: str,
    sections: list[str],
    existing_ids: set[str],
    existing_registry_ids: set[str],
    deliverable_sections: list[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    ids = set(existing_ids)
    planned_at = utc_now()
    for section in sections:
        for entry in registry.get(section, []):
            if entry["id"] in existing_registry_ids or not mode_matches(entry, mode):
                continue
            family = entry["use_for"][0]
            urls = entry_urls(section, entry)
            command = entry.get("command")
            if not urls and not command:
                continue
            query_id = next_id("QRY", ids)
            ids.add(query_id)
            name = entry.get("name") or entry.get("host") or entry.get("id")
            record: dict[str, Any] = {
                "query_id": query_id,
                "pass": "discovery",
                "family": family,
                "language": "zh" if section == "chinese" else "en",
                "query": f"open registry {section[:-1] if section.endswith('s') else section}: {name}",
                "status": "planned",
                "planned_at": planned_at,
                "registry_id": entry["id"],
                "registry_section": section,
            }
            if urls:
                record["urls"] = urls
            if command:
                record["command"] = command
            if entry.get("notes"):
                record["notes"] = entry["notes"]
            if deliverable_sections:
                record["deliverable_section_ids"] = list(deliverable_sections)
            records.append(record)
    return records


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.directory).expanduser().resolve()
    registry_path = Path(args.registry).expanduser().resolve() if args.registry else DEFAULT_REGISTRY
    try:
        manifest = load_json(root / "manifest.json")
        registry = load_registry(registry_path)
        executed = load_jsonl(root / "queries.jsonl")
        planned = load_jsonl(root / PLAN_FILE)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    mode = args.mode or infer_game_mode(manifest.get("current_context"))
    sections = list(dict.fromkeys(args.section)) or list(SECTIONS)
    existing_ids = {
        str(record.get("query_id")) for record in executed + planned if record.get("query_id")
    }
    existing_registry_ids = {
        str(record.get("registry_id")) for record in executed + planned if record.get("registry_id")
    }
    records = seed_records(
        registry,
        mode=mode,
        sections=sections,
        existing_ids=existing_ids,
        existing_registry_ids=existing_registry_ids,
        deliverable_sections=list(dict.fromkeys(args.deliverable_section)),
    )
    if args.json:
        for record in records:
            print(json.dumps(record, ensure_ascii=False))
    else:
        print(f"Registry seed: {len(records)} new direct opens for mode {mode} from {registry_path.name}")
        for record in records:
            target = record.get("urls", [record.get("command")])[0]
            print(f"- {record['query_id']} [{record['family']}] {record['query']} -> {target}")
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
