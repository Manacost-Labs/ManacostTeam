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
from urllib.parse import urlsplit

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
        url = str(entry.get("source_url", ""))
        host = (urlsplit(url).hostname or "").lower()
        official_hosts = timeline.get("official_hosts", ["blizzard.com"])
        if not url.startswith("https://") or not any(host == domain or host.endswith("." + domain) for domain in official_hosts):
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
    return max(eligible, key=lambda entry: (entry["released"], version_key(entry["version"]))) if eligible else None


def versions_in(text: str) -> list[str]:
    return VERSION_RE.findall(text)


def record_date(value: Any, label: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date or datetime") from exc


def registry_freshness(timeline: dict[str, Any], run_date: date, question_date: date, mode: str, historical: bool) -> tuple[dict[str, Any], list[str], list[str]]:
    """A checked registry bounds the search; its last patch is not proof of today."""
    errors, warnings = [], []
    checked = record_date(timeline.get("checked_at"), "timeline.checked_at")
    updated = record_date(timeline.get("updated_at"), "timeline.updated_at")
    max_age = timeline.get("max_age_days", 3)
    if type(max_age) is not int or max_age < 0:
        raise ValueError("timeline.max_age_days must be a nonnegative integer")
    if checked is None:
        errors.append("registry has no checked_at: updated_at does not prove that official changes were checked")
    elif checked > run_date:
        errors.append(f"registry checked_at {checked} is in the future relative to run date {run_date}")
    elif not historical and (run_date - checked).days > max_age:
        errors.append(f"registry checked_at {checked} is stale for current question {question_date}; recheck official updates")
    official_hosts = timeline.get("official_hosts", ["blizzard.com"])
    checks = timeline.get("official_checks", [])
    if not isinstance(checks, list) or not isinstance(official_hosts, list):
        raise ValueError("timeline official_checks and official_hosts must be lists")
    applicable = []
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("timeline official_checks entries must be objects")
        url = str(check.get("source_url", ""))
        host = (urlsplit(url).hostname or "").lower()
        check_date = record_date(check.get("checked_at"), "official check.checked_at")
        through = record_date(check.get("through"), "official check.through")
        modes = check.get("modes", [])
        if check_date and check_date > run_date:
            errors.append(f"registry official check {check_date} is in the future relative to run date {run_date}")
            continue
        if (not url.startswith("https://") or not any(host == domain or host.endswith("." + domain) for domain in official_hosts)
                or check_date is None or through is None or through > check_date
                or check.get("result") not in {"no_later_relevant_changes", "changes_recorded"}):
            errors.append("registry official check needs official HTTPS URL, checked_at, through <= checked_at, and an explicit result")
            continue
        if through >= question_date and (mode in modes or "all" in modes):
            if historical or (run_date - check_date).days <= max_age:
                applicable.append(check)
    if not applicable:
        errors.append(f"registry has no official update check covering {mode} through {question_date}")
    return {"checked_at": checked.isoformat() if checked else None,
            "updated_at": updated.isoformat() if updated else None,
            "max_age_days": max_age, "applicable_official_checks": applicable}, errors, warnings


def analyze(root: Path, timeline_path: Path, mode_override: str | None) -> dict[str, Any]:
    manifest = load_json(root / "manifest.json")
    sources = load_jsonl(root / "sources.jsonl")
    timeline = load_json(timeline_path)
    patches = load_timeline(timeline_path)
    known = {entry["version"]: entry for entry in patches}
    context = manifest.get("current_context") if isinstance(manifest.get("current_context"), dict) else {}
    mode = mode_override or infer_game_mode(context)
    try:
        as_of = date.fromisoformat(str(manifest.get("as_of")))
    except ValueError as exc:
        raise ValueError("manifest as_of must be YYYY-MM-DD") from exc
    temporal = manifest.get("temporal_scope", {})
    if not isinstance(temporal, dict) or temporal.get("mode", "current") not in {"current", "historical"}:
        raise ValueError("manifest.temporal_scope.mode must be current or historical")
    historical = temporal.get("mode") == "historical"
    question_date = record_date(temporal.get("as_of"), "temporal_scope.as_of") if historical else as_of
    if question_date is None or question_date > as_of:
        raise ValueError("historical temporal_scope.as_of must be present and not after manifest.as_of")
    mode_patches = patches_for_mode(patches, mode)
    latest = latest_as_of(mode_patches, question_date)
    latest_balance = latest_as_of(balance_patches_for_mode(patches, mode), question_date)
    registry_report, errors, warnings = registry_freshness(timeline, as_of, question_date, mode, historical)

    declared_client = next(
        (str(context[key]) for key in CONTEXT_PATCH_KEYS if context.get(key)), None
    )
    declared_balance = next(
        (str(context[key]) for key in CONTEXT_BALANCE_KEYS if context.get(key)), None
    )
    if latest is None:
        errors.append(f"timeline has no {mode} patch released on or before question date {question_date}")
    if declared_client is None:
        errors.append("manifest current_context declares no client patch (client_patch/patch/version)")
    else:
        client_versions = versions_in(declared_client)
        if not client_versions:
            warnings.append(f"declared client patch {declared_client!r} contains no version number")
        elif client_versions[0] not in known:
            errors.append(f"declared client patch {client_versions[0]} is not in the timeline")
        elif latest is not None and version_key(client_versions[0]) < version_key(latest["version"]):
            errors.append(
                f"declared client patch {client_versions[0]} is older than {latest['version']} "
                f"released {latest['released']} (question as_of {question_date})"
            )
        elif latest is not None and version_key(client_versions[0]) > version_key(latest["version"]):
            errors.append(
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
    source_dates: dict[str, Any] = {}
    checked = 0
    for record in sources:
        source_id = str(record.get("source_id", "?"))
        patch_text = record.get("patch")
        status = str(record.get("freshness_status") or "").upper()
        subjects = record.get("freshness_subjects", [])
        if not isinstance(subjects, list) or any(not isinstance(item, str) for item in subjects):
            raise ValueError(f"{source_id}.freshness_subjects must be a list of strings")
        relevant_patches = [patch for patch in balance_patches_for_mode(patches, mode)
                            if not subjects or not patch.get("subjects") or set(subjects) & set(patch["subjects"])]
        relevant_balance = latest_as_of(relevant_patches, question_date)
        published_date = record_date(record.get("published_at"), f"{source_id}.published_at")
        updated_date = record_date(record.get("updated_at"), f"{source_id}.updated_at")
        accessed_date = record_date(record.get("accessed_at"), f"{source_id}.accessed_at")
        # A page-level edit/access date says nothing about an unchanged statistic.
        content_date = record_date(record.get("content_updated_at"), f"{source_id}.content_updated_at") or published_date
        stats = record.get("statistical_context", {})
        if not isinstance(stats, dict):
            raise ValueError(f"{source_id}.statistical_context must be an object")
        window = stats.get("time_window", record.get("data_timeframe"))
        if isinstance(window, dict):
            window_start = record_date(window.get("start"), f"{source_id}.statistical_context.time_window.start")
            window_end = record_date(window.get("end"), f"{source_id}.statistical_context.time_window.end")
        else:
            dates = re.findall(r"\d{4}-\d{2}-\d{2}", str(window or ""))
            window_start = record_date(dates[0], f"{source_id}.data_timeframe") if dates else None
            window_end = record_date(dates[-1], f"{source_id}.data_timeframe") if dates else None
        if window_start and window_end and window_start > window_end:
            errors.append(f"{source_id}: data window start is after its end")
        if status in {"CURRENT", "LIKELY_CURRENT"} and record.get("source_type") in {"statistics", "dataset"}:
            if window_end is None:
                errors.append(f"{source_id}: current statistics have no verified data window")
            elif relevant_balance and window_end < date.fromisoformat(relevant_balance["released"]):
                errors.append(f"{source_id}: data window ends {window_end} before relevant change {relevant_balance['version']}")
            elif relevant_balance and window_start and window_start < date.fromisoformat(relevant_balance["released"]):
                errors.append(f"{source_id}: data window straddles relevant change {relevant_balance['version']}; filter the sample or label partial staleness")
        source_dates[source_id] = {"published_at": published_date.isoformat() if published_date else None,
                                   "updated_at": updated_date.isoformat() if updated_date else None,
                                   "accessed_at": accessed_date.isoformat() if accessed_date else None,
                                   "content_date": content_date.isoformat() if content_date else None,
                                   "data_window_start": window_start.isoformat() if window_start else None,
                                   "data_window_end": window_end.isoformat() if window_end else None,
                                   "latest_relevant_balance_patch": relevant_balance["version"] if relevant_balance else None}
        if content_date and content_date > question_date and not historical:
            errors.append(f"{source_id}: source content is after the requested question date")
        if not isinstance(patch_text, str) or not patch_text.strip():
            unlabeled.append(source_id)
            if (
                latest is not None
                and status in {"CURRENT", "LIKELY_CURRENT"}
                and content_date
                and relevant_balance is not None
                and content_date < date.fromisoformat(relevant_balance["released"])
            ):
                published_before_latest.append(source_id)
            if status in {"CURRENT", "LIKELY_CURRENT"} and not content_date:
                errors.append(f"{source_id}: current source has no patch or content date; freshness is unverified")
            continue
        checked += 1
        found = versions_in(patch_text)
        if not found:
            errors.append(f"{source_id}: unverified patch {patch_text!r}; record an exact version or an explicit historical limitation")
            continue
        unknown = [version for version in found if version not in known]
        if unknown:
            unknown_patch.append(f"{source_id} ({', '.join(unknown)})")
            continue
        newest = max(found, key=version_key)
        if date.fromisoformat(known[newest]["released"]) > question_date:
            errors.append(f"{source_id}: patch {newest} postdates the requested period {question_date}")
        if (
            relevant_balance is not None
            and version_key(newest) < version_key(relevant_balance["version"])
            and not status.startswith(OLDER_OK_PREFIXES)
        ):
            labeled_current_but_older.append(
                f"{source_id} ({newest} < {relevant_balance['version']})"
            )
        if (status.startswith(("VERSION_COMPATIBLE", "VERSION-COMPATIBLE", "CURRENT_WITH_OVERLAY"))
                and relevant_balance and version_key(newest) < version_key(relevant_balance["version"])):
            review = record.get("freshness_review", {})
            reviewed_versions = review.get("checked_versions", []) if isinstance(review, dict) else []
            affected = {patch["version"] for patch in relevant_patches
                        if version_key(newest) < version_key(patch["version"]) and date.fromisoformat(patch["released"]) <= question_date}
            urls = review.get("official_source_urls", []) if isinstance(review, dict) else []
            review_date = record_date(review.get("checked_at"), f"{source_id}.freshness_review.checked_at") if isinstance(review, dict) else None
            if (not isinstance(review, dict) or not review.get("reason") or not review.get("checked_at")
                    or review_date is None or review_date < date.fromisoformat(relevant_balance["released"])
                    or not isinstance(reviewed_versions, list) or not affected.issubset(set(reviewed_versions))
                    or not isinstance(urls, list) or any(known[version]["source_url"] not in urls for version in affected)):
                errors.append(f"{source_id}: older compatible/overlay source needs freshness_review with reason, checked_at and all relevant official changes")

    if unknown_patch:
        errors.append("sources cite patches missing from the timeline: " + ", ".join(unknown_patch))
    if labeled_current_but_older:
        errors.append(
            "sources predate the latest balance patch for the mode without a stale/compatible label: "
            + ", ".join(labeled_current_but_older)
        )
    if published_before_latest:
        errors.append(
            "sources labeled CURRENT/LIKELY_CURRENT were published before the latest balance patch and name no patch: "
            + ", ".join(published_before_latest)
        )
    if unlabeled:
        warnings.append(f"{len(unlabeled)} of {len(sources)} sources record no patch field")

    return {
        "research_id": manifest.get("research_id"),
        "mode": mode,
        "as_of": as_of.isoformat(),
        "question_as_of": question_date.isoformat(),
        "temporal_mode": "historical" if historical else "current",
        "registry": registry_report,
        "freshness_status": "unverified" if errors else "verified_against_registry",
        "source_dates": source_dates,
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
