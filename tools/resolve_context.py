#!/usr/bin/env python3
"""Resolve portable task metadata; does not execute workflows or install skills."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDENTIFIER = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
VERSION = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")


def load_catalog(root: Path, kind: str) -> tuple[dict[str, dict], str]:
    if kind not in {"games", "profiles"}:
        raise ValueError("unknown catalog kind")
    path = root / kind / "registry.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(catalog, dict)
        or type(catalog.get("schema_version")) is not int
        or catalog["schema_version"] != 1
        or not isinstance(catalog.get(kind), list)
        or not catalog[kind]
    ):
        raise ValueError(f"{kind}: nonempty catalog with schema_version 1 required")
    entries = {}
    for entry in catalog[kind]:
        if not isinstance(entry, dict) or set(entry) != {"id", "title", "version"}:
            raise ValueError(f"{kind}: each entry requires only id, title and version")
        if (
            not isinstance(entry["id"], str)
            or not IDENTIFIER.fullmatch(entry["id"])
            or not isinstance(entry["title"], str)
            or not entry["title"].strip()
            or not isinstance(entry["version"], str)
            or not VERSION.fullmatch(entry["version"])
        ):
            raise ValueError(f"{kind}: invalid id, title or version")
        if entry["id"] in entries:
            raise ValueError(f"{kind}: duplicate id {entry['id']}")
        entries[entry["id"]] = entry
    canonical = json.dumps(catalog, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return entries, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_context(
    root: Path,
    *,
    game: str | None,
    profile: str = "neutral",
    execution: str = "agent",
    patch: str | None = None,
) -> dict:
    games, game_hash = load_catalog(root, "games")
    profiles, profile_hash = load_catalog(root, "profiles")
    if game is not None and (not isinstance(game, str) or game not in games):
        raise ValueError(f"unknown game: {game}")
    if not isinstance(profile, str) or profile not in profiles:
        raise ValueError(f"unknown profile: {profile}")
    if execution not in ("agent", "server"):
        raise ValueError("execution must be agent or server")
    if patch is not None:
        if not isinstance(patch, str) or not patch.strip():
            raise ValueError("patch must be a nonempty string")
        if game is None:
            raise ValueError("patch requires a game")
    return {
        "schema_version": 1,
        "resolution_scope": "metadata_only",
        "game": dict(games[game]) if game is not None else None,
        "profile": dict(profiles[profile]),
        "execution": execution,
        "patch": patch,
        "catalog_sha256": {"games": game_hash, "profiles": profile_hash},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", help="Canonical game ID; omit for tasks unrelated to games")
    parser.add_argument("--profile", default="neutral")
    parser.add_argument("--execution", choices=("agent", "server"), default="agent")
    parser.add_argument("--patch", help="User-supplied patch/build; not independently verified")
    args = parser.parse_args()
    try:
        context = resolve_context(ROOT, **vars(args))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(context, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
