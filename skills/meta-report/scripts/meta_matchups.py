"""Comparable field models with explicit missing mass, never observed winrates."""

import json
from datetime import datetime, timezone
from urllib.parse import urlsplit


def need(condition, message):
    if not condition:
        raise ValueError(message)


def profiles(report, sources, handoff):
    rows = report.get("matchup_profiles")
    need(isinstance(rows, list), "matchup_profiles array required")
    need(rows or isinstance(report.get("matchup_profile_gap"), str) and report["matchup_profile_gap"].strip(), "matchup profiles or explicit matchup_profile_gap required")
    stats = {row["id"]: row for row in report["statistics"]}
    groups = {row["id"]: row for row in report["archetypes"]}
    source_map = {row["id"]: row for row in sources}
    chapters = {row["chapter_id"]: set(row["required_claim_ids"]) for row in handoff["chapters"]}
    identities, result = set(), []
    for profile in rows:
        need(isinstance(profile, dict), "invalid matchup profile")
        identity, gid = profile.get("id"), profile.get("archetype_id")
        need(isinstance(identity, str) and identity.strip() and identity not in identities and isinstance(gid, str) and gid in groups, "invalid/duplicate matchup profile identity")
        identities.add(identity)
        group = groups[gid]
        decks = profile.get("deck_ids")
        need(isinstance(decks, list) and len(decks) >= 2 and all(isinstance(d, str) for d in decks)
             and len(set(decks)) == len(decks) and set(decks) == set(group["deck_ids"]), "profile must compare every archetype candidate")
        chapter = report["classes"][group["class"]]["chapter_id"]
        for field in ("scope_claim_ids", "limitation_claim_ids"):
            ids = profile.get(field)
            need(isinstance(ids, list) and ids and all(isinstance(cid, str) and cid in chapters[chapter] for cid in ids), f"profile {field} outside class chapter")
        selected = {}
        for field in ("opponent_share_ids", "matchup_ids"):
            ids = profile.get(field)
            need(isinstance(ids, list) and ids and all(isinstance(sid, str) and sid in stats for sid in ids), f"profile invalid {field}")
            need(len(ids) == len(set(ids)), f"duplicate {field}")
            selected[field] = [stats[sid] for sid in ids]
        population = set()
        for row in selected["opponent_share_ids"] + selected["matchup_ids"]:
            times = [datetime.fromisoformat(row[key].replace("Z", "+00:00")).astimezone(timezone.utc).isoformat() for key in ("start", "end")]
            population.add(json.dumps([urlsplit(source_map[row["source_id"]]["url"]).hostname,
                                      *[row[key] for key in ("patch", "format", "rank", "region", "population")],
                                      *times, row.get("source_period"), row.get("filters", {})], sort_keys=True))
        need(len(population) == 1, "profile mixes incomparable population or providers")
        shares = {}
        for row in selected["opponent_share_ids"]:
            need(row["metric"] == "popularity" and row["grain"] == "archetype" and not row.get("opponent"), "profile opponent share must be overall archetype popularity")
            need(row["subject_id"] not in shares, "duplicate opponent share")
            shares[row["subject_id"]] = row
        need(sum(row["value"] for row in shares.values()) <= 100 + 1e-9, "opponent shares exceed 100 percent")
        cells = {}
        for row in selected["matchup_ids"]:
            need(row["metric"] == "winrate" and row["grain"] == "deck" and row["subject_id"] in decks, "profile needs exact deck matchup winrates")
            need(row.get("opponent") in shares, "matchup opponent absent from field shares")
            key = (row["subject_id"], row["opponent"])
            need(key not in cells, "duplicate deck/opponent matchup")
            cells[key] = row
        common = [opponent for opponent in shares if all((deck, opponent) in cells for deck in decks)]
        coverage = sum(shares[opponent]["value"] for opponent in common)
        estimates = {}
        for deck in decks:
            contribution = sum(shares[opponent]["value"] * cells[deck, opponent]["value"] / 100 for opponent in common)
            estimates[deck] = {"covered_estimate_percent": round(contribution * 100 / coverage, 6) if coverage else None,
                               "overall_bounds_percent": [round(contribution, 6), round(contribution + 100 - coverage, 6)],
                               "matchups": [cells[deck, opponent] for opponent in common]}
        tasks = [{"deck_id": deck, "opponent_id": opponent, "field_share_percent": shares[opponent]["value"],
                  "reason": "Missing exact deck matchup; both candidates excluded on this opponent."}
                 for opponent in shares for deck in decks if (deck, opponent) not in cells]
        tasks.sort(key=lambda task: (-task["field_share_percent"], task["deck_id"], task["opponent_id"]))
        result.append({**profile, "model_only": True, "coverage_percent": round(coverage, 6),
                       "unknown_field_percent": round(100 - coverage, 6), "common_opponents": common,
                       "decks": estimates, "research_tasks": tasks,
                       "interpretation": "Conditional estimate on common coverage, not observed overall winrate. Bounds span unknown mass at 0-100%; they are not confidence intervals. Matchup sampling uncertainty remains."})
    return result
