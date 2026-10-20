"""Evidence, search continuation and file-bound review for Funmeta v2."""

import hashlib
import json
import re
from pathlib import Path

from deck_code import decode, normalize_deck

CLASS_NAMES = {
    "death-knight": ("Рыцарь смерти", "Death Knight"),
    "demon-hunter": ("Охотник на демонов", "Demon Hunter"),
    "druid": ("Друид", "Druid"), "hunter": ("Охотник", "Hunter"),
    "mage": ("Маг", "Mage"), "paladin": ("Паладин", "Paladin"),
    "priest": ("Жрец", "Priest"), "rogue": ("Разбойник", "Rogue"),
    "shaman": ("Шаман", "Shaman"), "warlock": ("Чернокнижник", "Warlock"),
    "warrior": ("Воин", "Warrior"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def refs(value, index, label):
    require(isinstance(value, list) and bool(value), f"{label}: references required")
    require(all(isinstance(key, str) and key in index for key in value),
            f"{label}: unknown reference")
    require(len(set(value)) == len(value), f"{label}: duplicate reference")
    return value


def search_rows(data, sources):
    rows = data.get("search_log")
    require(isinstance(rows, list), "search_log: array required")
    ids = set()
    for row in rows:
        require(isinstance(row, dict) and text(row.get("id")), "search_log: id required")
        require(row["id"] not in ids, "search_log: duplicate id")
        ids.add(row["id"])
        require(isinstance(row.get("class"), str) and row["class"] in CLASS_NAMES
                and row.get("language") in ("ru", "en"),
                "search_log: class and ru/en language required")
        require(text(row.get("query")) and text(row.get("notes")),
                "search_log: actual query and outcome notes required")
        status = row.get("status")
        require(status in ("inspected", "empty", "blocked"), "search_log: invalid status")
        if status == "inspected":
            refs(row.get("source_ids"), sources, "search_log")
        else:
            require(row.get("source_ids") == [], "search_log: unread sources cannot count")
    return rows


def validate_v2(data, directory, sources):
    from catalog import audit_captures
    audit_captures(data, directory)
    if "discovery_policy" in data:
        from discovery import plan, provenance
        discovery = plan(data)
        for candidate in data["candidates"]:
            if candidate["decision"] == "include":
                require(candidate.get("deck_code_status") == "verified",
                        "include: verified deck code required; unresolved code stays pending")
                provenance(candidate, sources)
        for row in discovery["coverage"]:
            if row["class"] in data["gaps"]:
                require(row["gap_search_complete"],
                        f"gap {row['class']}: broaden source channels and record a focused card/mechanic search")
    root = Path(directory)
    rows = search_rows(data, sources)
    evidence = {}
    require(isinstance(data.get("evidence"), list), "evidence: array required")
    for item in data["evidence"]:
        require(isinstance(item, dict) and text(item.get("id")), "evidence: id required")
        require(item["id"] not in evidence, "evidence: duplicate id")
        source_id = item.get("source_id")
        require(isinstance(source_id, str) and source_id in sources, "evidence: unknown source")
        quote = item.get("quote")
        require(text(quote), "evidence: exact quote required")
        snapshot = (root / sources[source_id]["snapshot"]).read_text(encoding="utf-8-sig")
        require(quote in snapshot, f"evidence {item['id']}: quote not found in snapshot")
        evidence[item["id"]] = item

    publishers = set()
    for source_id in data["meta_source_ids"]:
        publisher = sources[source_id].get("publisher")
        require(text(publisher), f"meta {source_id}: publisher identity required")
        publishers.add(publisher.strip().casefold())
    require(len(publishers) >= 2, "meta: mirrors are not independent publishers")
    identities = set()
    for candidate in data["candidates"]:
        if candidate["decision"] != "include":
            continue
        label = f"candidate {candidate['id']}"
        deck = normalize_deck(candidate.get("deck_list"))
        require(deck["format"] == (2 if data["format"] == "standard" else 1),
                f"{label}: deck_list format mismatch")
        identity = json.dumps([candidate["class"], deck["cards"], deck["sideboards"]])
        require(identity not in identities, f"{label}: duplicate deck under another name")
        identities.add(identity)
        if candidate["deck_code_status"] == "verified":
            require(decode(candidate["deck_code"]) == deck, f"{label}: code/list mismatch")
        for source_id in candidate["source_ids"]:
            if sources[source_id]["kind"] == "deck":
                require(sources[source_id].get("access") == "full", f"{label}: deck is an excerpt")
        evidence_map = candidate.get("explanation_evidence")
        require(isinstance(evidence_map, dict), f"{label}: explanation_evidence required")
        for field in ("game_plan", "fun_moment", "limitations", "legality"):
            evidence_ids = refs(evidence_map.get(field), evidence, f"{label} {field}")
            candidate_sources = set(candidate["source_ids"] + candidate["mechanics_source_ids"])
            require(all(evidence[key]["source_id"] in candidate_sources for key in evidence_ids),
                    f"{label}: explanation evidence belongs to an unrelated source")
        require(text(candidate.get("closest_meta_plan")) and text(candidate.get("plan_difference")),
                f"{label}: compare the closest meta plan and explain the difference")
        require(any(row["class"] == candidate["class"] and row["status"] == "inspected"
                    and set(row["source_ids"]).intersection(candidate["source_ids"]) for row in rows),
                f"{label}: no inspected discovery source for this class")
    for card in data["fun_cards"]:
        card_refs = refs(card.get("evidence_ids"), evidence, f"card {card['id']}")
        require(all(evidence[key]["source_id"] in card["source_ids"] for key in card_refs),
                f"card {card['id']}: unrelated evidence")
    attempted = {(row["class"], row["language"]) for row in rows}
    require(all((class_name, language) in attempted
                for class_name in CLASS_NAMES for language in ("ru", "en")),
            "search_log: each class needs actual RU and EN attempts (including explicit failures)")
    return {"inspected_searches": sum(row["status"] == "inspected" for row in rows),
            "failed_or_empty_searches": sum(row["status"] != "inspected" for row in rows),
            "evidence_items": len(evidence)}


def next_actions(data, limit=6):
    if isinstance(data, dict) and "discovery_policy" in data:
        from discovery import plan
        return plan(data, limit)
    require(isinstance(data, dict) and data.get("schema_version") == 2,
            "next requires a v2 run; old runs remain readable with check")
    require(data.get("format") in ("standard", "wild"), "unsupported format")
    sources = data.get("sources", [])
    require(isinstance(sources, list) and all(isinstance(row, dict) and text(row.get("id"))
                                            for row in sources), "sources: invalid records")
    rows = search_rows(data, {row["id"]: row for row in sources})
    attempted = {(row["class"], row["language"]) for row in rows}
    tasks = []
    exhausted = []
    gaps = data.get("gaps")
    require(isinstance(gaps, dict), "gaps must be an object")
    # First show unattempted lanes, then failed lanes. A suggestion is not an executed search.
    for retry in (False, True):
        for class_name, names in CLASS_NAMES.items():
            for language, name in zip(("ru", "en"), names, strict=True):
                lane = (class_name, language)
                if (lane in attempted) != retry:
                    continue
                previous = [row for row in rows if (row["class"], row["language"]) == lane]
                if previous and class_name not in gaps:
                    continue
                if len(previous) >= 2:
                    exhausted.append({"class": class_name, "language": language,
                                      "reason": gaps.get(class_name, "Unresolved")})
                    continue
                query = (f"Hearthstone {name} необычная фан колода" if language == "ru"
                         else f"Hearthstone {name} off meta homebrew deck")
                query += f" {data['format']} {data.get('patch', '')}".rstrip()
                tasks.append({"class": class_name, "language": language,
                              "query": None if retry else query,
                              "focus": gaps.get(class_name, "") if retry else "",
                              "instruction": ("Write a targeted query in this language from the gap and prior findings; do not repeat the first query."
                                              if retry else "Inspect results before recording a successful search."),
                              "reason": ("unresolved_class" if any(row["status"] == "inspected" for row in previous)
                                         else "blocked_or_empty") if retry else "not_attempted"})
    candidates = data.get("candidates", [])
    require(isinstance(candidates, list) and all(isinstance(row, dict) for row in candidates),
            "candidates: invalid records")
    return {"status": "research_in_progress", "suggested_queries": tasks[:limit],
            "remaining_search_lanes": len(tasks),
            "exhausted_lanes": exhausted,
            "pending_candidates": [row.get("id") for row in candidates if row.get("decision") == "pending"],
            "class_gaps": data.get("gaps", {}),
            "next_step": "Inspect sources, record real outcomes; then check and review the material."}


def review_digests(selection_path):
    selection_path = Path(selection_path)
    material = selection_path.parent / "material.md"
    return {"selection_sha256": hashlib.sha256(selection_path.read_bytes()).hexdigest(),
            "material_sha256": hashlib.sha256(material.read_bytes()).hexdigest(),
            "notice": "Digests only; not a review or approval."}


def export_material(selection_path, data, validation, output):
    require(data["schema_version"] == 2, "export requires v2 evidence and review")
    require(validation["selected_decks"] > 0, "export: no selected decks; deliver a gap report")
    directory = Path(selection_path).parent
    review = json.loads((directory / "review.json").read_text(encoding="utf-8-sig"))
    require(isinstance(review, dict), "review must be an object")
    for field, digest in review_digests(selection_path).items():
        if field.endswith("_sha256"):
            require(review.get(field) == digest, f"review: stale {field}")
    require(review.get("verdict") == "pass" and review.get("checked_on") == data["as_of"],
            "review: pass on as_of required")
    require(all(review.get(field) is True for field in
                ("facts_checked", "plan_explained", "coverage_checked")),
            "review: facts, deck explanation and coverage checks required")
    require(review.get("findings") == [] and text(review.get("notes")),
            "review: resolve findings and record a substantive review note")
    material = (directory / "material.md").read_text(encoding="utf-8")
    require(bool(material.strip()), "export: empty material")
    code_blocks = re.findall(r"(?ms)^```(?:text|plaintext)?[ \t]*\n(.*?)^```[ \t]*$", material)
    printed_codes = {line.strip() for block in code_blocks for line in block.splitlines()}
    for candidate in data["candidates"]:
        if candidate["decision"] != "include":
            continue
        require(candidate.get("deck_code_status") == "verified",
                f"export {candidate['id']}: verified deck code required; keep unresolved decks pending")
        require(candidate.get("deck_code") in printed_codes,
                f"export {candidate['id']}: selected deck code missing from a copyable code block")
    if validation["coverage"] == "partial":
        require(review.get("gaps_disclosed") is True, "review: disclose partial coverage")
    # Exclusive creation protects both drafts and previous exports, including path aliases.
    with Path(output).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(material)
    return {"status": "exported_after_recorded_review", "output": str(Path(output).resolve()),
            "coverage": validation["coverage"], "mechanical_checks_only": True}
