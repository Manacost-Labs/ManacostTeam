"""Read-only research diagnostics. Recorded checks are not factual approval."""

import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from deck_code import decode, normalize_deck
from quality import CLASS_NAMES, require, text


def timestamp(value):
    require(isinstance(value, str), "timestamp: explicit timezone required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.tzinfo is not None, "timestamp: explicit timezone required")
    return result.astimezone(timezone.utc)


def meta_issues(data, sources):
    """Additional temporal contract for new runs; legacy data stays readable."""
    if "readiness_policy" not in data:
        return []
    require(data.get("schema_version") == 2 and type(data["readiness_policy"]) is int
            and data["readiness_policy"] == 1, "readiness_policy: expected version 1 in v2")
    meta_ids = data.get("meta_source_ids", [])
    require(isinstance(meta_ids, list) and all(isinstance(key, str) for key in meta_ids),
            "meta_source_ids: expected an array of source ids")
    issues = []
    context = data.get("meta_context")
    context = context if isinstance(context, dict) else {}
    try:
        effective = timestamp(context.get("effective_at"))
        require(effective.date() <= date.fromisoformat(data["as_of"]), "future context")
    except (ValueError, TypeError, KeyError):
        effective = None
        issues.append({"code": "meta_context_time", "message": "Record the official latest relevant expansion/balance time, with timezone."})
    official = sources.get(context.get("source_id")) if isinstance(context.get("source_id"), str) else None
    if not (official and official.get("kind") == "official" and official.get("access") == "full"
            and official.get("checked_on") == data.get("as_of") and text(context.get("reason"))):
        issues.append({"code": "meta_context_source", "message": "Link the fully read official context source, checked on as_of, and explain the boundary."})
    for key in meta_ids:
        source = sources.get(key, {})
        if source.get("data_kind") != "observed":
            issues.append({"code": "meta_not_observed", "source_id": key,
                           "message": "Theorycraft and forecasts are not observed meta tables."})
        period = source.get("data_period")
        try:
            require(isinstance(period, dict), "period missing")
            start, end = timestamp(period.get("start")), timestamp(period.get("end"))
            require(start < end and end.date() <= date.fromisoformat(data["as_of"]), "invalid period")
        except (ValueError, TypeError, KeyError):
            issues.append({"code": "meta_period_invalid", "source_id": key,
                           "message": "Record the actual nonempty observation interval; checked_on/fetched_at is not the data period."})
            continue
        if effective is not None and start < effective:
            issues.append({"code": "meta_before_context", "source_id": key,
                           "message": "The interval includes games before the relevant release/balance. Obtain a filtered post-event table."})
    return issues


def assess(data, directory):
    require(isinstance(data, dict) and data.get("schema_version") == 2, "assess requires a v2 run")
    require(data.get("format") in ("standard", "wild"), "assess: unsupported format")
    sources, candidates = data.get("sources"), data.get("candidates")
    require(isinstance(sources, list) and isinstance(candidates, list), "assess: record arrays required")
    index = {}
    for source in sources:
        require(isinstance(source, dict) and text(source.get("id")) and source["id"] not in index,
                "assess: unique source ids required")
        index[source["id"]] = source
    root, snapshots, global_issues = Path(directory).resolve(), {}, []
    for key, source in index.items():
        try:
            relative = Path(source.get("snapshot", ""))
            path = (root / relative).resolve()
            require(not relative.is_absolute() and path.is_relative_to(root), "snapshot leaves run")
            payload = path.read_bytes()
            require(bool(payload.strip()) and hashlib.sha256(payload).hexdigest() == source.get("sha256"), "snapshot hash/content mismatch")
            snapshots[key] = payload.decode("utf-8-sig")
        except (OSError, ValueError, TypeError):
            global_issues.append({"code": "source_integrity", "source_id": key,
                                  "message": "Read and hash a nonempty source snapshot inside this run."})
    patch_source = index.get(data.get("patch_source_id")) if isinstance(data.get("patch_source_id"), str) else None
    if not (text(data.get("patch")) and patch_source and patch_source.get("kind") == "official"
            and patch_source.get("patch") == data["patch"] and patch_source.get("checked_on") == data.get("as_of")):
        global_issues.append({"code": "patch_unverified", "message": "Check the current patch in an official source on as_of."})
    meta_ids = data.get("meta_source_ids", [])
    require(isinstance(meta_ids, list) and all(isinstance(key, str) for key in meta_ids), "assess: meta ids array required")
    hosts, publishers = set(), set()
    for key in meta_ids:
        source = index.get(key, {})
        try:
            age = (date.fromisoformat(data["as_of"]) - date.fromisoformat(source["checked_on"])).days
            valid = (source.get("kind") == "meta" and source.get("format") == data.get("format")
                     and source.get("patch") == data.get("patch") and source.get("access") == "full"
                     and text(source.get("scope")) and text(source.get("publisher")) and 0 <= age <= 14)
            url = urlsplit(source.get("url", ""))
            valid = valid and url.scheme in ("http", "https") and bool(url.hostname) and not url.username and not url.password
            require(valid, "unusable table")
        except (ValueError, KeyError, TypeError):
            global_issues.append({"code": "meta_source_unusable", "source_id": key,
                                  "message": "A current full table with scope, publisher and a public URL is required."})
            continue
        hosts.add(url.hostname.lower().removeprefix("www."))
        publishers.add(source["publisher"].strip().casefold())
    if len(hosts) < 2 or len(publishers) < 2:
        global_issues.append({"code": "meta_coverage", "message": "Read two independent complete current meta tables; mirrors do not count twice."})
    global_issues.extend(meta_issues(data, index))
    evidence = data.get("evidence", [])
    require(isinstance(evidence, list) and all(isinstance(e, dict) and text(e.get("id")) for e in evidence), "assess: evidence records required")
    evidence_index = {e["id"]: e for e in evidence}
    require(len(evidence_index) == len(evidence), "assess: duplicate evidence id")
    reports, distribution, candidate_ids = [], {}, set()
    for row in candidates:
        require(isinstance(row, dict) and text(row.get("id")) and row["id"] not in candidate_ids
                and row.get("class") in CLASS_NAMES and row.get("decision") in ("include", "pending", "reject"),
                "assess: invalid/duplicate candidate")
        candidate_ids.add(row["id"])
        if row["decision"] == "reject":
            continue
        issues = []
        source_ids = row.get("source_ids", [])
        require(isinstance(source_ids, list) and all(isinstance(key, str) for key in source_ids), "assess: source ids required")
        full = [key for key in source_ids if key in index and index[key].get("kind") == "deck" and index[key].get("access") == "full"]
        if not full:
            issues.append("full_deck_source")
        candidate_publishers = {index[key]["publisher"].strip().casefold()
                                if text(index[key].get("publisher")) else "unknown" for key in full}
        for publisher in candidate_publishers:
            distribution.setdefault(publisher, []).append(row["id"])
        try:
            require(row.get("deck_code_status") == "verified", "unverified")
            deck = normalize_deck(row.get("deck_list"))
            require(deck["format"] == (2 if data.get("format") == "standard" else 1), "format")
            require(decode(row.get("deck_code")) == deck, "code/list mismatch")
        except (ValueError, TypeError):
            issues.append("deck_code_and_independent_list")
        try:
            from discovery import provenance
            provenance(row, index)
        except (ValueError, TypeError):
            issues.append("code_provenance")
        if row.get("legality") != "verified" or not text(row.get("legality_reason")):
            issues.append("current_legality")
        if any(not text(row.get(field)) for field in ("premise", "game_plan", "fun_moment", "limitations", "closest_meta_plan", "plan_difference")):
            issues.append("distinct_game_plan_and_limits")
        bindings = row.get("explanation_evidence", {})
        mechanics = row.get("mechanics_source_ids", [])
        require(isinstance(mechanics, list) and all(isinstance(key, str) for key in mechanics), "assess: mechanics source ids required")
        allowed = set(source_ids + mechanics)
        for field in ("game_plan", "fun_moment", "limitations", "legality"):
            keys = bindings.get(field) if isinstance(bindings, dict) else None
            valid = isinstance(keys, list) and bool(keys) and all(isinstance(k, str) for k in keys)
            if valid:
                for key in keys:
                    item = evidence_index.get(key, {})
                    quote, sid = item.get("quote"), item.get("source_id")
                    if not (isinstance(sid, str) and sid in allowed and text(quote) and quote in snapshots.get(sid, "")):
                        valid = False
            if not valid:
                issues.append("evidence_" + field)
        checks = row.get("meta_checks", [])
        checks = checks if isinstance(checks, list) else []
        if any(isinstance(c, dict) and c.get("source_id") in meta_ids and c.get("result") == "present" for c in checks):
            issues.append("meta_plan_present")
        else:
            for key in meta_ids:
                matches = [c for c in checks if isinstance(c, dict) and c.get("source_id") == key]
                if len(matches) != 1 or matches[0].get("result") != "absent" or not text(matches[0].get("reason")):
                    issues.append("meta_comparison")
                    break
        reports.append({"candidate": row["id"], "class": row["class"], "decision": row["decision"],
                        "blocking_checks": issues, "recorded_checks_complete": not issues and not global_issues})
    warnings = []
    dominant = max(distribution, key=lambda key: len(distribution[key])) if distribution else None
    if len(reports) > 1 and dominant and len(distribution[dominant]) > len(reports) / 2:
        warnings.append("Most full deck sources name one publisher. Search independent authors/communities and compare game plans; this is not an automatic rejection or a numeric quota.")
    else:
        dominant = None
    if "readiness_policy" not in data:
        warnings.append("Legacy run: observation periods are not enforced. Check release/balance timing manually before reusing this research.")
    return {"status": "research_diagnostics", "global_blockers": global_issues,
            "candidates": reports, "publisher_distribution": distribution,
            "dominant_publisher": dominant, "warnings": warnings,
            "mechanical_checks_only": True, "export_approved": False,
            "notice": "Read-only. No decisions, dates, evidence or approvals are created. This report does not replace check, material audit or factual/style review."}
