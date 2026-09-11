#!/usr/bin/env python3
"""Check a research bundle against a machine-readable patch timeline.

The freshness policy says a source is current only relative to the patch that
last touched its subject. This script makes that checkable: the manifest's
declared patch must be the latest timeline entry for the run's mode as of the
run date, every source that names a patch must name a known one, and a source
whose patch predates the latest entry must carry a stale, partially stale,
historical, or version-compatible label instead of ``CURRENT``.

It cannot know which mechanic a source discusses; it flags candidates for the
freshness gate rather than proving compatibility.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

from search_support import infer_game_mode

DEFAULT_TIMELINE = Path(__file__).resolve().parents[1] / "references/domains/hearthstone-patches.json"
VERSION_RE = re.compile(r"\b(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)\b")
CONTEXT_PATCH_KEYS = ("client_patch", "patch", "version")
CONTEXT_BALANCE_KEYS = (
    "balance_patch",
    "latest_battlegrounds_balance_patch",
    "latest_substantive_balance",
    "latest_balance_patch",
)
OLDER_OK_PREFIXES = (
    "STALE",
    "PARTIALLY_STALE",
    "HISTORICAL",
    "VERSION_COMPATIBLE",
    "VERSION-COMPATIBLE",
    "CURRENT_WITH_OVERLAY",
    "DISCOVERY_ONLY",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="Research bundle directory")
    parser.add_argument("--timeline", help=f"Timeline JSON; default {DEFAULT_TIMELINE.name}")
    parser.add_argument("--mode", choices=("battlegrounds", "constructed", "arena", "all"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Exit 1 on blocking findings")
    return parser.parse_args(argv)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name}: expected an object")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def load_timeline(path: Path) -> list[dict[str, Any]]:
    timeline = load_json(path)
    if timeline.get("timeline_version") != "1.0":
        raise ValueError("unsupported timeline_version")
    patches = timeline.get("patches")
    if not isinstance(patches, list) or not patches:
        raise ValueError("timeline has no patches")
    seen: set[str] = set()
    for entry in patches:
        version = entry.get("version")
        if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
            raise ValueError(f"invalid patch version {version!r}")
        if version in seen:
            raise ValueError(f"duplicate patch version {version}")
        seen.add(version)
        date.fromisoformat(str(entry.get("released")))
        if not isinstance(entry.get("modes"), list) or not entry["modes"]:
            raise ValueError(f"patch {version} needs modes")
        if not str(entry.get("source_url", "")).startswith("https://"):
            raise ValueError(f"patch {version} needs an official source_url")
    return sorted(patches, key=lambda entry: version_key(entry["version"]))


def patches_for_mode(patches: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    return [
        entry for entry in patches if mode == "all" or mode in entry["modes"]
    ]


def balance_patches_for_mode(patches: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    """Patches that changed rules, pools, or numbers for ``mode`` (``balance_modes`` or ``modes``)."""

    result = []
    for entry in patches:
        balance_modes = entry.get("balance_modes", entry["modes"])
        if mode == "all" or mode in balance_modes:
            result.append(entry)
    return result


def latest_as_of(patches: list[dict[str, Any]], as_of: date) -> dict[str, Any] | None:
    eligible = [entry for entry in patches if date.fromisoformat(entry["released"]) <= as_of]
    return eligible[-1] if eligible else None


def versions_in(text: str) -> list[str]:
    return VERSION_RE.findall(text)


def analyze(root: Path, timeline_path: Path, mode_override: str | None) -> dict[str, Any]:
    manifest = load_json(root / "manifest.json")
    sources = load_jsonl(root / "sources.jsonl")
    patches = load_timeline(timeline_path)
    known = {entry["version"]: entry for entry in patches}
    context = manifest.get("current_context") if isinstance(manifest.get("current_context"), dict) else {}
    mode = mode_override or infer_game_mode(context)
    try:
        as_of = date.fromisoformat(str(manifest.get("as_of")))
    except ValueError as exc:
        raise ValueError("manifest as_of must be YYYY-MM-DD") from exc
    mode_patches = patches_for_mode(patches, mode)
    latest = latest_as_of(mode_patches, as_of)
    latest_balance = latest_as_of(balance_patches_for_mode(patches, mode), as_of)
    errors: list[str] = []
    warnings: list[str] = []

    declared_client = next(
        (str(context[key]) for key in CONTEXT_PATCH_KEYS if context.get(key)), None
    )
    declared_balance = next(
        (str(context[key]) for key in CONTEXT_BALANCE_KEYS if context.get(key)), None
    )
    if latest is None:
        warnings.append(f"timeline has no {mode} patch released on or before {as_of}")
    if declared_client is None:
        warnings.append("manifest current_context declares no client patch (client_patch/patch/version)")
    else:
        client_versions = versions_in(declared_client)
        if not client_versions:
            warnings.append(f"declared client patch {declared_client!r} contains no version number")
        elif client_versions[0] not in known:
            errors.append(f"declared client patch {client_versions[0]} is not in the timeline")
        elif latest is not None and version_key(client_versions[0]) < version_key(latest["version"]):
            errors.append(
                f"declared client patch {client_versions[0]} is older than {latest['version']} "
                f"released {latest['released']} (as_of {as_of})"
            )
        elif latest is not None and version_key(client_versions[0]) > version_key(latest["version"]):
            warnings.append(
                f"declared client patch {client_versions[0]} is newer than the timeline's latest "
                f"{latest['version']}; update the timeline"
            )
    if declared_balance:
        for version in versions_in(declared_balance):
            if version not in known:
                errors.append(f"declared balance patch {version} is not in the timeline")

    labeled_current_but_older: list[str] = []
    unknown_patch: list[str] = []
    unlabeled: list[str] = []
    published_before_latest: list[str] = []
    checked = 0
    for record in sources:
        source_id = str(record.get("source_id", "?"))
        patch_text = record.get("patch")
        status = str(record.get("freshness_status") or "").upper()
        if not isinstance(patch_text, str) or not patch_text.strip():
            unlabeled.append(source_id)
            published = str(record.get("published_at") or "")[:10]
            if (
                latest is not None
                and status == "CURRENT"
                and published
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", published)
                and latest_balance is not None
                and date.fromisoformat(published) < date.fromisoformat(latest_balance["released"])
            ):
                published_before_latest.append(source_id)
            continue
        checked += 1
        found = versions_in(patch_text)
        if not found:
            continue
        unknown = [version for version in found if version not in known]
        if unknown:
            unknown_patch.append(f"{source_id} ({', '.join(unknown)})")
            continue
        newest = max(found, key=version_key)
        if (
            latest_balance is not None
            and version_key(newest) < version_key(latest_balance["version"])
            and not status.startswith(OLDER_OK_PREFIXES)
        ):
            labeled_current_but_older.append(
                f"{source_id} ({newest} < {latest_balance['version']})"
            )

    if unknown_patch:
        errors.append("sources cite patches missing from the timeline: " + ", ".join(unknown_patch))
    if labeled_current_but_older:
        errors.append(
            "sources predate the latest balance patch for the mode without a stale/compatible label: "
            + ", ".join(labeled_current_but_older)
        )
    if published_before_latest:
        warnings.append(
            "sources labeled CURRENT were published before the latest balance patch and name no patch: "
            + ", ".join(published_before_latest)
        )
    if unlabeled:
        warnings.append(f"{len(unlabeled)} of {len(sources)} sources record no patch field")

    return {
        "research_id": manifest.get("research_id"),
        "mode": mode,
        "as_of": as_of.isoformat(),
        "timeline": timeline_path.name,
        "latest_patch": latest,
        "latest_balance_patch": latest_balance,
        "declared_client_patch": declared_client,
        "declared_balance_patch": declared_balance,
        "sources_total": len(sources),
        "sources_with_patch": checked,
        "sources_without_patch": unlabeled,
        "findings": {"errors": errors, "warnings": warnings},
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.directory).expanduser().resolve()
    timeline_path = Path(args.timeline).expanduser().resolve() if args.timeline else DEFAULT_TIMELINE
    try:
        report = analyze(root, timeline_path, args.mode)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        latest = report["latest_patch"]
        latest_text = f"{latest['version']} ({latest['released']})" if latest else "none"
        balance = report["latest_balance_patch"]
        balance_text = f"{balance['version']} ({balance['released']})" if balance else "none"
        verdict = "FAIL" if report["findings"]["errors"] else "PASS"
        print(
            f"Freshness check: {verdict} (mode {report['mode']}, as_of {report['as_of']}, "
            f"latest client patch {latest_text}, latest balance patch {balance_text}, "
            f"declared {report['declared_client_patch']})"
        )
        print(f"- sources with a patch field: {report['sources_with_patch']}/{report['sources_total']}")
        for error in report["findings"]["errors"]:
            print(f"- error: {error}")
        for warning in report["findings"]["warnings"]:
            print(f"- warning: {warning}")
    if args.strict and report["findings"]["errors"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
