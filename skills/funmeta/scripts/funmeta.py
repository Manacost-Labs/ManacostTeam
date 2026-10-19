#!/usr/bin/env python3
"""Scaffold and check Funmeta selection records; never infer game facts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

CLASSES = (
    "death-knight", "demon-hunter", "druid", "hunter", "mage", "paladin",
    "priest", "rogue", "shaman", "warlock", "warrior",
)
SKILL = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def iso_date(value: object) -> date:
    require(isinstance(value, str), "date must be YYYY-MM-DD")
    parsed = date.fromisoformat(value)
    require(parsed.isoformat() == value, "date must be YYYY-MM-DD")
    return parsed


def records(value: object, label: str) -> dict:
    require(isinstance(value, list), f"{label}: expected array")
    result = {}
    for item in value:
        require(isinstance(item, dict) and nonempty(item.get("id")),
                f"{label}: every record needs an id")
        require(item["id"] not in result, f"{label}: duplicate id {item['id']}")
        result[item["id"]] = item
    return result


def references(value: object, sources: dict, label: str) -> list:
    require(isinstance(value, list) and bool(value), f"{label}: sources required")
    require(all(isinstance(ref, str) and ref in sources for ref in value),
            f"{label}: unknown source")
    require(len(set(value)) == len(value), f"{label}: duplicate source")
    return value


def initialize(directory: Path, as_of: str, game_format: str) -> Path:
    iso_date(as_of)
    require(game_format in ("standard", "wild"), "unsupported format")
    # mkdir without exist_ok prevents replacement of another run, even an empty one.
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "sources").mkdir()
    selection = {
        "schema_version": 1, "as_of": as_of, "format": game_format,
        "patch": "", "patch_source_id": "", "meta_source_ids": [],
        "sources": [], "candidates": [], "fun_cards": [],
        "gaps": {name: "Поиск ещё не выполнен." for name in CLASSES},
    }
    path = directory / "selection.json"
    path.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    (directory / "material.md").write_text(
        (SKILL / "references" / "output-template.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return path


def validate(data: object, directory: Path) -> dict:
    require(isinstance(data, dict), "selection must be an object")
    require(type(data.get("schema_version")) is int and data["schema_version"] == 1,
            "schema_version must be 1")
    as_of = iso_date(data.get("as_of"))
    game_format = data.get("format")
    require(game_format in ("standard", "wild"), "unsupported format")
    patch = data.get("patch")
    require(nonempty(patch), "patch: current official check required")
    sources = records(data.get("sources"), "sources")
    root = directory.resolve()
    for source_id, source in sources.items():
        label = f"source {source_id}"
        require(nonempty(source.get("url")), f"{label}: URL required")
        url = urlsplit(source["url"])
        require(url.scheme in ("http", "https") and bool(url.hostname)
                and not url.username and not url.password, f"{label}: invalid public URL")
        require(nonempty(source.get("title")), f"{label}: title required")
        require(source.get("kind") in ("official", "meta", "deck", "card", "community"),
                f"{label}: invalid kind")
        checked_on = iso_date(source.get("checked_on"))
        require(checked_on <= as_of, f"{label}: check is after as_of")
        require(nonempty(source.get("snapshot")), f"{label}: snapshot required")
        relative = Path(source["snapshot"])
        snapshot = (root / relative).resolve()
        require(not relative.is_absolute() and snapshot.is_relative_to(root),
                f"{label}: snapshot must stay inside run")
        require(snapshot.is_file(), f"{label}: snapshot missing")
        content = snapshot.read_bytes()
        require(bool(content.strip()), f"{label}: empty snapshot")
        require(hashlib.sha256(content).hexdigest() == source.get("sha256"),
                f"{label}: snapshot hash mismatch")

    patch_id = data.get("patch_source_id")
    require(isinstance(patch_id, str) and patch_id in sources,
            "patch_source_id: source required")
    official = sources[patch_id]
    require(official["kind"] == "official" and official.get("patch") == patch
            and official["checked_on"] == data["as_of"],
            "patch: official source must confirm patch and be checked on as_of")

    meta_ids = references(data.get("meta_source_ids"), sources, "meta_source_ids")
    hosts = set()
    for source_id in meta_ids:
        source = sources[source_id]
        require(source["kind"] == "meta" and source.get("format") == game_format
                and source.get("patch") == patch,
                f"meta {source_id}: wrong kind, format or patch")
        require(source.get("access") == "full" and nonempty(source.get("scope")),
                f"meta {source_id}: full table access and scope required")
        require((as_of - iso_date(source["checked_on"])).days <= 14,
                f"meta {source_id}: check older than 14 days")
        hosts.add(urlsplit(source["url"]).hostname.lower().removeprefix("www."))
    require(len(hosts) >= 2, "meta: at least two distinct publishers required")

    candidates = records(data.get("candidates"), "candidates")
    selected_classes = set()
    selected = 0
    for candidate_id, candidate in candidates.items():
        label = f"candidate {candidate_id}"
        require(candidate.get("class") in CLASSES, f"{label}: unknown class")
        require(nonempty(candidate.get("name")), f"{label}: name required")
        decision = candidate.get("decision")
        require(decision in ("include", "reject", "pending"), f"{label}: invalid decision")
        require(nonempty(candidate.get("reason")), f"{label}: decision reason required")
        if decision != "include":
            continue
        selected += 1
        selected_classes.add(candidate["class"])
        for field in ("premise", "game_plan", "fun_moment", "limitations", "legality_reason"):
            require(nonempty(candidate.get(field)), f"{label}: {field} required")
        require(candidate.get("legality") == "verified", f"{label}: legality unverified")
        refs = references(candidate.get("source_ids"), sources, label)
        require(any(sources[ref]["kind"] == "deck" for ref in refs),
                f"{label}: full deck source required")
        references(candidate.get("mechanics_source_ids"), sources, f"{label} mechanics")
        require(candidate.get("deck_code_status") in ("verified", "unavailable"),
                f"{label}: unverified deck code cannot be delivered")
        require(nonempty(candidate.get("deck_code_reason")), f"{label}: code check reason required")
        if candidate["deck_code_status"] == "verified":
            require(nonempty(candidate.get("deck_code")), f"{label}: verified code missing")
        else:
            require(not candidate.get("deck_code"), f"{label}: omit unavailable deck code")
        checks = candidate.get("meta_checks")
        require(isinstance(checks, list), f"{label}: meta_checks required")
        checked = []
        for check in checks:
            require(isinstance(check, dict), f"{label}: invalid meta check")
            source_id = check.get("source_id")
            require(isinstance(source_id, str) and source_id in meta_ids,
                    f"{label}: unknown meta table")
            require(check.get("result") == "absent" and nonempty(check.get("reason")),
                    f"{label}: present/unknown archetype cannot be included")
            checked.append(source_id)
        require(len(checked) == len(meta_ids) and set(checked) == set(meta_ids),
                f"{label}: every meta table must be checked exactly once")

    gaps = data.get("gaps")
    require(isinstance(gaps, dict), "gaps must be an object")
    require(all(key in CLASSES and nonempty(reason) for key, reason in gaps.items()),
            "gaps: unknown class or missing reason")
    require(not selected_classes.intersection(gaps), "selected class also has a gap")
    require(selected_classes.union(gaps) == set(CLASSES),
            "every class needs an included deck or explicit gap")
    fun_cards = records(data.get("fun_cards"), "fun_cards")
    require(not selected or bool(fun_cards), "fun_cards: explain at least one card")
    for card_id, card in fun_cards.items():
        require(nonempty(card.get("name")) and nonempty(card.get("why_fun")),
                f"card {card_id}: name and explanation required")
        references(card.get("source_ids"), sources, f"card {card_id}")
    return {
        "status": "structure_valid", "mechanical_checks_only": True,
        "coverage": "complete" if not gaps else "partial",
        "selected_decks": selected, "classes_with_decks": len(selected_classes),
        "class_gaps": list(gaps),
        "notice": "Source meaning, meta absence, mechanics and final prose require review.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a new run; never overwrite")
    init.add_argument("directory", type=Path)
    init.add_argument("--as-of", required=True)
    init.add_argument("--format", choices=("standard", "wild"), default="standard")
    check = commands.add_parser("check", help="Check records and snapshot integrity only")
    check.add_argument("selection", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            path = initialize(args.directory, args.as_of, args.format)
            result = {"status": "initialized", "selection": str(path.resolve())}
        else:
            data = json.loads(args.selection.read_text(encoding="utf-8-sig"))
            result = validate(data, args.selection.parent)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
