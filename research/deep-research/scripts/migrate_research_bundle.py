#!/usr/bin/env python3
"""Migrate schema 1.0 bundles, backfill legacy schema 1.1 profiles, and upgrade 1.1 to 1.2.

The 1.2 upgrade requires canonical query passes and families. Provide a JSON
map file with ``{"families": {...}, "passes": {...}}`` that translates the
bundle's free-text values; the migration refuses to guess an unmapped value.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from search_support import QUERY_FAMILIES, QUERY_PASSES


MIGRATED_FILES = ("manifest.json", "sources.jsonl", "handoff.md")
SEMANTIC_LEDGER = "semantic-audit.jsonl"
OUTPUT_PROFILES = {"editor-ready", "research-report", "raw-research"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="Research bundle directory")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true", help="Apply migration")
    group.add_argument("--rollback", help="Restore an explicit migration backup directory")
    parser.add_argument(
        "--to", choices=("1.1", "1.2"), default="1.1", help="Target schema version"
    )
    parser.add_argument(
        "--family-map",
        help="JSON file mapping free-text query families and passes to canonical values",
    )
    parser.add_argument(
        "--default-language", default="en", help="Language recorded on queries without one"
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: root must be an object")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{line_number}: record must be an object")
        records.append(value)
    return records


def atomic_write(path: Path, text: str) -> None:
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def serialize_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def serialize_jsonl(records: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records)


def handoff_output_profiles(markdown: str) -> list[str]:
    visible = re.sub(r"<!--.*?(?:-->|$)", "", markdown, flags=re.DOTALL)
    return [
        match.group(1).casefold()
        for match in re.finditer(
            r"(?im)^\s*(?:[-*]\s*)?output[_ ]profile\s*:\s*`?"
            r"([a-z][a-z0-9_-]*)`?\s*$",
            visible,
        )
    ]


def backfill_handoff_profile(markdown: str, output_profile: str) -> tuple[str, bool]:
    values = handoff_output_profiles(markdown)
    if len(values) > 1:
        raise ValueError("handoff.md: output_profile appears more than once")
    if values:
        if values[0] != output_profile:
            raise ValueError(
                "handoff.md: output_profile conflicts with inferred manifest profile"
            )
        return markdown, False

    line = f"Output profile: `{output_profile}`\n"
    research_id = re.search(
        r"(?im)^\s*(?:[-*]\s*)?research[_ ]id\s*:\s*`?[^\n`]+`?\s*$",
        markdown,
    )
    if research_id is not None:
        insertion = research_id.end()
        prefix = markdown[:insertion].rstrip("\n")
        suffix = markdown[insertion:].lstrip("\n")
        return f"{prefix}\n\n{line}\n{suffix}", True

    heading = re.search(r"(?m)^#\s+.+$", markdown)
    if heading is not None:
        insertion = heading.end()
        prefix = markdown[:insertion].rstrip("\n")
        suffix = markdown[insertion:].lstrip("\n")
        return f"{prefix}\n\n{line}\n{suffix}", True
    return f"{line}\n{markdown.lstrip()}", True


def rollback(root: Path, backup_arg: str) -> int:
    backup_root = (root / "migration-backups").resolve()
    backup = Path(backup_arg).expanduser().resolve()
    if not backup.is_relative_to(backup_root):
        print("error: rollback backup must be inside this bundle's migration-backups", file=sys.stderr)
        return 2
    for name in MIGRATED_FILES:
        source = backup / name
        if not source.is_file():
            print(f"error: backup is missing {name}", file=sys.stderr)
            return 2
    for name in MIGRATED_FILES:
        shutil.copy2(backup / name, root / name)
    queries_backup = backup / "queries.jsonl"
    if queries_backup.is_file():
        shutil.copy2(queries_backup, root / "queries.jsonl")
    semantic_backup = backup / SEMANTIC_LEDGER
    semantic_marker = backup / ".semantic-audit-was-absent"
    if semantic_backup.is_file():
        shutil.copy2(semantic_backup, root / SEMANTIC_LEDGER)
    elif semantic_marker.is_file():
        (root / SEMANTIC_LEDGER).unlink(missing_ok=True)
    print(f"Rolled back research bundle from: {backup}")
    return 0


def load_family_map(path: str | None) -> tuple[dict[str, str], dict[str, str]]:
    if not path:
        return {}, {}
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("family map must be an object")
    families = value.get("families", {})
    passes = value.get("passes", {})
    if not isinstance(families, dict) or not isinstance(passes, dict):
        raise ValueError("family map needs 'families' and 'passes' objects")
    for target in families.values():
        if target not in QUERY_FAMILIES:
            raise ValueError(f"family map targets unknown family {target!r}")
    for target in passes.values():
        if target not in QUERY_PASSES:
            raise ValueError(f"family map targets unknown pass {target!r}")
    return {str(k): str(v) for k, v in families.items()}, {str(k): str(v) for k, v in passes.items()}


def migrate_to_12(root: Path, manifest: dict[str, Any], args: argparse.Namespace) -> int:
    """Upgrade a schema 1.1 bundle to 1.2 with canonical query taxonomy."""

    if "output_profile" not in manifest or manifest.get("output_profile") not in OUTPUT_PROFILES:
        print("error: backfill output_profile (schema 1.1 migration) before upgrading to 1.2", file=sys.stderr)
        return 2
    try:
        queries = load_jsonl(root / "queries.jsonl")
        family_map, pass_map = load_family_map(args.family_map)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    unmapped_families: set[str] = set()
    unmapped_passes: set[str] = set()
    migrated: list[dict[str, Any]] = []
    changed_queries = 0
    for record in queries:
        item = dict(record)
        family = str(item.get("family", ""))
        if family not in QUERY_FAMILIES:
            if family in family_map:
                item["legacy_family"] = family
                item["family"] = family_map[family]
            else:
                unmapped_families.add(family)
        pass_value = str(item.get("pass", ""))
        if pass_value not in QUERY_PASSES:
            if pass_value in pass_map:
                item["legacy_pass"] = pass_value
                item["pass"] = pass_map[pass_value]
            else:
                unmapped_passes.add(pass_value)
        if not item.get("language"):
            item["language"] = args.default_language
        if item != record:
            changed_queries += 1
        migrated.append(item)
    if unmapped_families or unmapped_passes:
        print("error: schema 1.2 needs canonical query values; add these to --family-map:", file=sys.stderr)
        for value in sorted(unmapped_families):
            print(f"  family: {value!r}", file=sys.stderr)
        for value in sorted(unmapped_passes):
            print(f"  pass: {value!r}", file=sys.stderr)
        return 1

    print(
        f"Migration preview: schema 1.1 -> 1.2; {changed_queries} of {len(queries)} query "
        f"records updated; apply={args.apply}"
    )
    print(
        "Note: 1.2 final validation also requires exact_excerpt anchors for evidence with "
        "snapshots and a challenge_search or challenging evidence on critical claims; "
        "record those before final."
    )
    if not args.apply:
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = root / "migration-backups" / f"{stamp}-schema-1.1-to-1.2"
    backup.mkdir(parents=True, exist_ok=False)
    for name in MIGRATED_FILES + ("queries.jsonl",):
        shutil.copy2(root / name, backup / name)
    if (root / SEMANTIC_LEDGER).is_file():
        shutil.copy2(root / SEMANTIC_LEDGER, backup / SEMANTIC_LEDGER)
    else:
        (backup / ".semantic-audit-was-absent").touch()

    migrated_manifest = dict(manifest)
    migrated_manifest["schema_version"] = "1.2"
    migrated_manifest["updated_at"] = utc_now()
    provenance = dict(migrated_manifest.get("provenance", {}))
    provenance["migrated_from"] = "1.1"
    migrated_manifest["provenance"] = provenance
    atomic_write(root / "manifest.json", serialize_json(migrated_manifest))
    atomic_write(root / "queries.jsonl", serialize_jsonl(migrated))
    print("Applied schema 1.1 -> 1.2")
    print(f"Rollback backup: {backup}")
    return 0


def main() -> int:
    args = parse_args()
    root = Path(args.directory).expanduser().resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2
    if args.rollback:
        return rollback(root, args.rollback)

    try:
        manifest = load_json(root / "manifest.json")
        sources = load_jsonl(root / "sources.jsonl")
        handoff = (root / "handoff.md").read_text(encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    version = manifest.get("schema_version")
    if args.to == "1.2":
        if version != "1.1":
            print("error: schema 1.2 upgrade requires a schema 1.1 bundle", file=sys.stderr)
            return 2
        return migrate_to_12(root, manifest, args)
    if version not in {"1.0", "1.1"}:
        print(f"error: unsupported source schema {version}", file=sys.stderr)
        return 2

    legacy_modifiers = manifest.get("modifiers")
    if not isinstance(legacy_modifiers, list):
        legacy_modifiers = []
    existing_output_profile = manifest.get("output_profile")
    has_legacy_raw_modifier = "raw-research" in legacy_modifiers
    if existing_output_profile is not None and (
        not isinstance(existing_output_profile, str)
        or existing_output_profile not in OUTPUT_PROFILES
    ):
        print("error: invalid existing output_profile", file=sys.stderr)
        return 2
    if (
        has_legacy_raw_modifier
        and existing_output_profile is not None
        and existing_output_profile != "raw-research"
    ):
        print(
            "error: output_profile conflicts with legacy raw-research modifier",
            file=sys.stderr,
        )
        return 2

    migrated_sources: list[dict[str, Any]] = []
    for source in sources:
        item = dict(source)
        if version == "1.0":
            legacy_url = str(item.get("url", ""))
            item.setdefault("requested_url", legacy_url)
            item.setdefault("final_url", legacy_url)
            item.setdefault("mutable", True)
            item.setdefault("fingerprint_status", "unavailable")
            item.setdefault(
                "fingerprint_reason",
                "Migrated legacy source; inspected content was not preserved for hashing.",
            )
        migrated_sources.append(item)

    migrated_manifest = dict(manifest)
    inferred_output_profile = (
        existing_output_profile
        or ("raw-research" if has_legacy_raw_modifier else "research-report")
    )
    try:
        migrated_handoff, handoff_changed = backfill_handoff_profile(
            handoff, inferred_output_profile
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    manifest_changed = (
        version == "1.0"
        or existing_output_profile != inferred_output_profile
        or has_legacy_raw_modifier
    )
    if not manifest_changed and not handoff_changed:
        print("Research bundle is already schema 1.1 with matching output_profile")
        return 0

    migrated_manifest["output_profile"] = inferred_output_profile
    migrated_manifest["modifiers"] = [
        value for value in legacy_modifiers if value != "raw-research"
    ]
    migrated_manifest["updated_at"] = utc_now()
    if version == "1.0":
        migrated_manifest["schema_version"] = "1.1"
        migrated_manifest["provenance"] = {
            "fingerprint_policy": "when-permitted",
            "snapshot_policy": "local-only",
            "hash_algorithm": "sha256",
            "migrated_from": "1.0",
        }

    migration_name = (
        "schema 1.0 -> 1.1"
        if version == "1.0"
        else "schema 1.1 output_profile backfill with handoff"
    )

    print(
        f"Migration preview: {migration_name}; "
        f"output_profile={inferred_output_profile}; "
        f"{len(migrated_sources)} source records; apply={args.apply}"
    )
    if not args.apply:
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_suffix = (
        "schema-1.0-to-1.1"
        if version == "1.0"
        else "schema-1.1-output-profile-backfill"
    )
    backup = root / "migration-backups" / f"{stamp}-{backup_suffix}"
    backup.mkdir(parents=True, exist_ok=False)
    for name in MIGRATED_FILES:
        shutil.copy2(root / name, backup / name)
    if (root / SEMANTIC_LEDGER).is_file():
        shutil.copy2(root / SEMANTIC_LEDGER, backup / SEMANTIC_LEDGER)
    else:
        (backup / ".semantic-audit-was-absent").touch()

    atomic_write(root / "manifest.json", serialize_json(migrated_manifest))
    if handoff_changed:
        atomic_write(root / "handoff.md", migrated_handoff)
    if version == "1.0":
        atomic_write(root / "sources.jsonl", serialize_jsonl(migrated_sources))
        if not (root / SEMANTIC_LEDGER).exists():
            atomic_write(root / SEMANTIC_LEDGER, "")
    print(f"Applied {migration_name}")
    print(f"Rollback backup: {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
