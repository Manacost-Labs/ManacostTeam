"""Source-aware, read-only research planning. Suggestions are not evidence."""

import json
from urllib.parse import urlsplit, urlunsplit

from deck_code import decode, normalize_deck
from quality import CLASS_NAMES, require, search_rows, text

MCP_CLASSES = {key: name.replace(" ", "") for key, (_, name) in CLASS_NAMES.items()}
CHANNELS = ("catalog", "creators", "community", "build-around")


def policy(data):
    value = data.get("discovery_policy")
    require(type(value) is int and value == 1, "discovery_policy: expected version 1")


def full_refs(candidate, sources):
    return [key for key in candidate.get("source_ids", []) if key in sources
            and sources[key].get("kind") == "deck" and sources[key].get("access") == "full"]


def provenance(candidate, sources):
    value = candidate.get("code_provenance")
    require(isinstance(value, dict) and value.get("kind") in
            ("author-export", "reconstructed-list"), "code_provenance: origin required")
    keys = value.get("source_ids")
    require(isinstance(keys, list) and bool(keys) and all(isinstance(key, str) for key in keys)
            and len(keys) == len(set(keys))
            and all(key in full_refs(candidate, sources) for key in keys),
            "code_provenance: independently read full deck source required")


def source_urls(candidate, sources):
    urls = set()
    for key in full_refs(candidate, sources):
        url = urlsplit(sources[key].get("url", ""))
        if url.hostname:
            urls.add(urlunsplit((url.scheme.lower(), url.netloc.lower(), url.path.rstrip("/"), url.query, "")))
    return urls


def shortlist_count(candidates, sources):
    """Connected copies count once, including partially transcribed mirrors."""
    groups = []
    for candidate in candidates:
        if not full_refs(candidate, sources):
            continue
        keys = {("url", url) for url in source_urls(candidate, sources)}
        deck_key = identity(candidate)
        if deck_key:
            keys.add(("deck", deck_key))
        if not keys:
            continue
        matched = [group for group in groups if group.intersection(keys)]
        for group in matched:
            keys.update(group)
            groups.remove(group)
        groups.append(keys)
    return len(groups)


def identity(candidate):
    if candidate.get("deck_list"):
        deck = normalize_deck(candidate["deck_list"])
        return json.dumps([candidate["class"], deck["cards"], deck["sideboards"]])
    return None


def plan(data, limit=6):
    from catalog import inspection_queue
    require(isinstance(data, dict) and data.get("schema_version") == 2,
            "plan requires a v2 run")
    require(data.get("format") in ("standard", "wild"), "unsupported format")
    require(type(limit) is int and 1 <= limit <= 22, "limit must be 1..22")
    # Explicit plan also upgrades planning for old journals, without modifying them.
    if "discovery_policy" in data:
        policy(data)
    source_rows = data.get("sources", [])
    require(isinstance(source_rows, list) and all(isinstance(row, dict) and text(row.get("id"))
            for row in source_rows), "sources: invalid records")
    sources = {row["id"]: row for row in source_rows}
    require(len(sources) == len(source_rows), "sources: duplicate id")
    rows = search_rows(data, sources)
    catalog_offsets = {}
    for row in rows:
        require("channel" not in row or row["channel"] in CHANNELS, "search_log: invalid channel")
        if "next_offset" in row:
            require(type(row["next_offset"]) is int and row["next_offset"] > 0
                    and row.get("channel") == "catalog" and row["status"] == "inspected",
                    "search_log: invalid catalog continuation")
            lane = (row["class"], row["language"])
            require(row["next_offset"] > catalog_offsets.get(lane, 0),
                    "search_log: catalog continuation must advance")
            catalog_offsets[lane] = row["next_offset"]
    candidates = data.get("candidates", [])
    require(isinstance(candidates, list) and all(isinstance(row, dict)
            and row.get("class") in CLASS_NAMES and row.get("decision") in
            ("include", "pending", "reject") for row in candidates), "candidates: invalid records")
    tasks, checks, coverage = [], [], []
    for class_name, (ru, en) in CLASS_NAMES.items():
        class_rows = [row for row in rows if row["class"] == class_name]
        active = [c for c in candidates if c["class"] == class_name and c["decision"] != "reject"]
        leads = shortlist_count(active, sources)
        selected = any(c["decision"] == "include" for c in active)
        channels = {row.get("channel") for row in class_rows}
        focused = any(row.get("channel") == "build-around" and text(row.get("focus"))
                      for row in class_rows)
        gap_ready = ({"ru", "en"} <= {row["language"] for row in class_rows}
                     and {"creators", "community", "build-around"} <= channels and focused)
        coverage.append({"class": class_name, "distinct_full_source_leads": leads,
                         "shortlist_target": 2, "gap_search_complete": gap_ready,
                         "selected": selected})
        for c in active:
            todo = []
            if not full_refs(c, sources):
                todo.append("read_full_deck_source")
            if not c.get("deck_list"):
                todo.append("transcribe_independent_list")
            try:
                require(c.get("deck_code_status") == "verified", "unverified")
                require(decode(c.get("deck_code")) == normalize_deck(c.get("deck_list")), "mismatch")
                provenance(c, sources)
            except (ValueError, TypeError):
                todo.append("obtain_or_reconstruct_and_compare_code")
            if c.get("legality") != "verified":
                todo.append("verify_current_legality_and_zones")
            if not c.get("explanation_evidence") or not c.get("plan_difference"):
                todo.append("verify_mechanics_and_distinct_game_plan")
            checked = {row.get("source_id") for row in c.get("meta_checks", [])
                       if row.get("result") == "absent"}
            if len(data.get("meta_source_ids", [])) < 2 or not set(data.get("meta_source_ids", [])) <= checked:
                todo.append("compare_with_current_meta_tables")
            if todo:
                checks.append({"candidate": c.get("id"), "tasks": todo})
        missing_languages = {"ru", "en"} - {row["language"] for row in class_rows}
        for channel, language in (("catalog", "en"), ("creators", "en"),
                                  ("community", "ru"), ("community", "en"),
                                  ("build-around", "ru"), ("build-around", "en")):
            if (selected or leads >= 2) and (channel != "community" or language not in missing_languages):
                continue
            previous = [r for r in class_rows if r.get("channel") == channel and r["language"] == language]
            continuation = previous[-1].get("next_offset") if previous else None
            if len(previous) >= 2 and continuation is None:
                continue
            focus = next((c["search_focus"] for c in active if text(c.get("search_focus"))), "")
            task = {"class": class_name, "channel": channel, "language": language,
                    "attempt": len(previous) + 1, "focus": focus,
                    "query": None, "instruction": "Read complete source and record actual outcome."}
            if channel == "catalog":
                task.update(tool="mcp__manacost__search_decks", arguments={"format": data["format"],
                            "className": MCP_CLASSES[class_name], "limit": 30,
                            "offset": continuation or 0})
                task["instruction"] = "Broad class scan, no title/author filter. Follow reported pagination; reject meta plans separately."
                if previous and continuation is None:
                    continue  # Never repeat the same first page after empty/blocked results.
            elif channel == "build-around":
                task["query"] = (f"Hearthstone {ru if language == 'ru' else en} {focus} {data['format']}" if focus else None)
                task["instruction"] = "Choose an actual current card/mechanic from a read source; record it as focus. Change the query on retry."
            else:
                term = ("необычная фан колода" if language == "ru" else
                        ("homebrew off meta deck author video" if channel == "creators" else "off meta deck reddit"))
                task["query"] = f"Hearthstone {ru if language == 'ru' else en} {term} {data['format']}"
                if previous:
                    task["query"] = None
                    task["instruction"] = "Use a different site/author and a targeted query from prior findings; blocked sites do not exhaust other channels."
            tasks.append(task)
    # All untouched channels/classes before retries; missing classes before second leads.
    counts = {row["class"]: row["distinct_full_source_leads"] for row in coverage}
    tasks.sort(key=lambda row: (row["attempt"] > 1, counts[row["class"]],
                               CHANNELS.index(row["channel"]), row["language"] == "en" and row["channel"] == "community"))
    return {"status": "research_in_progress", "suggested_queries": tasks[:limit],
            **inspection_queue(data, limit),
            "remaining_search_lanes": len(tasks), "candidate_tasks": checks, "coverage": coverage,
            "meta_tasks": ["Read two independent current meta tables; do not stop discovery if one is blocked."],
            "notice": "Read-only suggestions, not executed searches or proof of fun, legality or meta absence."}
