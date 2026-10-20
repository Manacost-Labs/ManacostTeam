#!/usr/bin/env python3
"""ResearchTeam/EditorTeam adapter for Hearthstone meta reports.

Local checkout workflow, stdlib only. Consumes the existing publication handoff
and source-candidate contracts; delegates publication state/reviews/export to
editorteam.publication_run and deck serialization to Funmeta's strict decoder.
It does not search, generate prose, verify game legality, or manufacture reviews.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
CLASSES = {
    "death-knight": "Рыцарь смерти", "demon-hunter": "Охотник на демонов",
    "druid": "Друид", "hunter": "Охотник", "mage": "Маг", "paladin": "Паладин",
    "priest": "Жрец", "rogue": "Разбойник", "shaman": "Шаман",
    "warlock": "Чернокнижник", "warrior": "Воин",
}
INPUTS = ("meta-report.json", "sources.json", "publication-handoff.json")


def read_json(path):
    def invalid(value):
        raise ValueError(f"non-finite JSON number: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=invalid)


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def iso_date(value):
    require(isinstance(value, str), "date must use YYYY-MM-DD")
    parsed = date.fromisoformat(value)
    require(parsed.isoformat() == value, "date must use YYYY-MM-DD")
    return parsed


def timestamp(value):
    require(text(value), "timestamp required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "timestamp timezone required")
    return parsed


def valid_url(value):
    if not text(value) or any(char.isspace() or ord(char) < 32 for char in value) or "\\" in value:
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and parsed.username is None and parsed.password is None
    except ValueError:
        return False


def runtimes():
    runtime = ROOT / "editor/src"
    require((runtime / "editorteam/publication_run.py").is_file(), "main ManacostTeam checkout required")
    if str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))
    from editorteam import publication_review, publication_run
    spec = importlib.util.spec_from_file_location("meta_report_deck_code", ROOT / "skills/funmeta/scripts/deck_code.py")
    deck_code = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(deck_code)
    return publication_run, publication_review, deck_code


def initialize(run, *, as_of, game_format="standard", rank="all-ranks", region="all-regions", window_hours=24):
    run = Path(run).resolve()
    iso_date(as_of)
    require(game_format in {"standard", "wild"}, "unsupported format")
    require(text(rank) and text(region), "rank and region required")
    require(type(window_hours) is int and window_hours > 0, "positive window_hours required")
    require(not run.exists(), "run directory already exists")
    report = {
        "schema_version": 2, "as_of": as_of, "format": game_format, "patch": None,
        "rank": rank, "region": region, "window_hours": window_hours, "scope_note": "",
        "official_checks": [], "trend_claim_ids": [],
        "classes": {key: {"status": "pending", "chapter_id": key, "assessment_claim_ids": [],
                           "deck_ids": [], "gap": ""} for key in CLASSES},
        "decks": [], "statistics": [], "statistics_gap": "", "rankings": [],
        "assessments": [], "gaps": [],
        "archetypes": [], "dominance": [], "dominance_gap": "",
    }
    command = [sys.executable, str(ROOT / "research/deep-research/scripts/init_research_run.py"),
               str(run / "research"), "--question", "Мета-отчет Hearthstone: что выбрать для ладдера и почему",
               "--as-of", as_of, "--depth", "deep", "--output-profile", "editor-ready", "--domain", "hearthstone"]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    require(result.returncode == 0, "research initialization failed: " + result.stderr)
    write_json(run / "meta-report.json", report)
    return report


def cohort_key(row):
    """A matchup filter is part of the population, never an aggregate rate."""
    fields = ("metric", "grain", "source_id", "patch", "format", "rank", "region", "population", "opponent")
    period = tuple(timestamp(row[field]).astimezone(timezone.utc).isoformat() for field in ("start", "end"))
    return (*[row.get(key) for key in fields], *period, json.dumps(row.get("filters", {}), sort_keys=True, allow_nan=False))


def published_decks(report):
    return [deck for deck in report["decks"] if report["schema_version"] == 1 or deck.get("publish") is True]


def scope_mismatches(report):
    warnings = []
    for row in report["statistics"]:
        differences = {field: {"requested": report[field], "observed": row[field]}
                       for field in ("rank", "region") if row[field] != report[field]}
        hours = (timestamp(row["end"]) - timestamp(row["start"])).total_seconds() / 3600
        if hours != report["window_hours"]:
            differences["window_hours"] = {"requested": report["window_hours"], "observed": hours}
        if timestamp(row["end"]).date().isoformat() != report["as_of"]:
            differences["end_date"] = {"requested": report["as_of"], "observed": timestamp(row["end"]).date().isoformat()}
        if differences:
            warnings.append({"stat_id": row["id"], "differences": differences})
    return warnings


def compare_decks(left, right):
    """Exact multiset differences, including sideboard owner/copy changes."""
    codec = runtimes()[2]
    normalized = []
    for deck in (left, right):
        value = codec.normalize_deck(deck.get("deck_list"))
        require(codec.decode(deck.get("code")) == value, "comparison code/list mismatch")
        normalized.append(value)
    a, b = normalized
    require(a["format"] == b["format"] and left.get("class") == right.get("class"), "comparison format/class mismatch")
    main_a, main_b = (Counter(dict(value["cards"])) for value in (a, b))
    side_a, side_b = (Counter({(cid, owner): count for cid, count, owner in value["sideboards"]}) for value in (a, b))
    return {
        "common_main_copies": sum((main_a & main_b).values()),
        "left_only": [[cid, count] for cid, count in sorted((main_a - main_b).items())],
        "right_only": [[cid, count] for cid, count in sorted((main_b - main_a).items())],
        "left_sideboard_only": [[cid, count, owner] for (cid, owner), count in sorted((side_a - side_b).items())],
        "right_sideboard_only": [[cid, count, owner] for (cid, owner), count in sorted((side_b - side_a).items())],
    }


def validate_analysis(report, sources, handoff, stats):
    """Validate research decisions; evidence meaning remains a reviewer task."""
    require(isinstance(report.get("archetypes"), list), "archetype analysis required")
    require(bool(report["archetypes"]) or not report["decks"], "archetype analysis required for every candidate")
    decks = {deck["id"]: deck for deck in report["decks"]}
    claims = {claim["claim_id"]: claim for claim in handoff["claims"]}
    chapters = {chapter["chapter_id"]: set(chapter["required_claim_ids"]) for chapter in handoff["chapters"]}
    source_ids = {source["id"] for source in sources}
    groups, assigned, comparison_ids = {}, set(), set()

    def refs(value, label, chapter, required=True):
        require(isinstance(value, list) and (bool(value) or not required)
                and all(text(cid) and cid in claims and cid in chapters[chapter] for cid in value)
                and len(set(value)) == len(value), f"{label}: supported class claim ids required")

    def contrary(value, label, chapter):
        require(isinstance(value, dict), f"{label}: counterargument or explicit gap required")
        ids, gap = value.get("claim_ids"), value.get("gap", "")
        refs(ids, label, chapter, required=False)
        require(bool(ids) or text(gap), f"{label}: counterargument or explicit gap required")

    for deck in decks.values():
        require(type(deck.get("publish")) is bool, "archetype candidate needs explicit publish flag")
    for group in report["archetypes"]:
        require(isinstance(group, dict), "archetype must be an object")
        gid, key, ids = group.get("id"), group.get("class"), group.get("deck_ids")
        require(text(gid) and gid not in groups and text(group.get("name")) and key in report["classes"], "invalid archetype id/class/name")
        require(isinstance(ids, list) and bool(ids) and all(text(did) and did in decks and decks[did]["class"] == key for did in ids)
                and len(set(ids)) == len(ids) and not (set(ids) & assigned), f"{gid}: invalid/duplicate archetype candidates")
        chapter = report["classes"][key]["chapter_id"]
        refs(group.get("identity_claim_ids"), f"{gid}/archetype identity", chapter)
        search = group.get("search")
        require(isinstance(search, dict) and text(search.get("note")) and isinstance(search.get("source_ids"), list)
                and bool(search["source_ids"]) and all(text(sid) and sid in source_ids for sid in search["source_ids"]), f"{gid}: candidate search provenance required")
        selection = group.get("selection")
        require(isinstance(selection, dict), f"{gid}: selection required")
        verdict, preferred, basis = (selection.get(field) for field in ("verdict", "preferred_deck_id", "basis"))
        require(verdict in {"preferred", "conditional", "inconclusive", "single-candidate"}, f"{gid}: invalid selection verdict")
        require(basis in {"statistics", "mechanism", "mixed", "insufficient"}, f"{gid}: invalid selection basis")
        require(selection.get("confidence") in {"high", "medium", "low"}, f"{gid}: selection confidence required")
        for field in ("reason_claim_ids", "scope_claim_ids", "caveat_claim_ids"):
            refs(selection.get(field), f"{gid}/selection/{field}", chapter)
        if len(ids) == 1:
            require(verdict == "single-candidate" and preferred == ids[0] and text(search.get("gap")), f"{gid}: single-candidate needs a search gap, not a comparative winner")
        else:
            require(verdict != "single-candidate", f"{gid}: multiple candidates need comparisons")
        if verdict in {"preferred", "single-candidate"}:
            require(preferred in ids and decks[preferred]["publish"], f"{gid}: preferred candidate must be published")
            require(basis != "insufficient", f"{gid}: insufficient evidence cannot select a winner")
        elif verdict == "inconclusive":
            require(preferred is None, f"{gid}: inconclusive research cannot name a winner")
        else:
            require(preferred is None or (preferred in ids and decks[preferred]["publish"]), f"{gid}: invalid conditional preference")
            require(sum(decks[did]["publish"] for did in ids) >= 2, f"{gid}: conditional selection needs published alternatives")
        comparisons, pairs, covered, has_stats, unknown_sample = group.get("comparisons"), set(), set(), False, False
        require(isinstance(comparisons, list) and (bool(comparisons) or len(ids) == 1), f"{gid}: comparison required")
        for comparison in comparisons:
            require(isinstance(comparison, dict), f"{gid}: invalid comparison")
            cid, left, right = (comparison.get(field) for field in ("id", "left", "right"))
            require(text(cid) and cid not in comparison_ids and left in ids and right in ids and left != right, f"{gid}: invalid comparison identities")
            pair = frozenset((left, right))
            require(pair not in pairs, f"{gid}: duplicate comparison pair")
            pairs.add(pair)
            covered.update(pair)
            comparison_ids.add(cid)
            delta = compare_decks(decks[left], decks[right])
            changed = {row[0] for field in ("left_only", "right_only", "left_sideboard_only", "right_sideboard_only") for row in delta[field]}
            require(bool(changed), f"{cid}: candidate lists have no changed cards")
            impacts, explained = comparison.get("impacts"), set()
            require(isinstance(impacts, list) and bool(impacts), f"{cid}: changed cards need explanations")
            for impact in impacts:
                require(isinstance(impact, dict), f"{cid}: invalid card impact")
                cards = impact.get("card_ids")
                require(isinstance(cards, list) and bool(cards) and all(type(card) is int and card in changed for card in cards), f"{cid}: impacts must name changed cards")
                explained.update(cards)
                refs(impact.get("reason_claim_ids"), f"{cid}/reason", chapter)
                refs(impact.get("tradeoff_claim_ids"), f"{cid}/tradeoff", chapter)
            require(explained == changed, f"{cid}: unexplained changed cards")
            for field in ("conclusion_claim_ids", "scope_claim_ids"):
                refs(comparison.get(field), f"{cid}/{field}", chapter)
            contrary(comparison.get("counterargument"), f"{cid}/counterargument", chapter)
            stat_pairs = comparison.get("stat_pairs")
            require(isinstance(stat_pairs, list), f"{cid}: stat_pairs array required")
            for record in stat_pairs:
                require(isinstance(record, dict) and text(record.get("left")) and text(record.get("right"))
                        and record["left"] in stats and record["right"] in stats, f"{cid}: unknown comparison statistics")
                a, b = stats[record["left"]], stats[record["right"]]
                require(a["grain"] == b["grain"] == "deck" and a["metric"] == b["metric"] == "winrate"
                        and a["subject_id"] == left and b["subject_id"] == right, f"{cid}: wrong comparison statistic subject/grain")
                require(cohort_key(a) == cohort_key(b), f"{cid}: incomparable statistic cohorts")
                has_stats = True
                unknown_sample |= a["sample_games"] is None or b["sample_games"] is None
            if basis == "statistics":
                require(bool(stat_pairs), f"{cid}: statistical preference needs comparison statistics")
        if len(ids) > 1:
            require(covered == set(ids), f"{gid}: candidates missing from comparisons")
        if verdict == "preferred":
            require(all(frozenset((preferred, other)) in pairs for other in ids if other != preferred), f"{gid}: preferred list needs direct comparison with every alternative")
        if basis in {"statistics", "mixed"}:
            if len(ids) == 1:
                supporting = [row for row in stats.values() if row["grain"] == "deck" and row["subject_id"] == preferred
                              and row["metric"] == "winrate" and not row.get("opponent")]
                require(bool(supporting), f"{gid}: single-candidate statistical recommendation needs its own results")
                unknown_sample |= any(row["sample_games"] is None for row in supporting)
            else:
                require(has_stats, f"{gid}: selection basis requires comparable statistics")
            require(not (unknown_sample and selection["confidence"] == "high"), f"{gid}: unknown sample cannot support high confidence")
        confidence = {"low": 1, "medium": 2, "high": 3}
        require(all(confidence[selection["confidence"]] <= confidence[claims[cid]["confidence"]]
                    for cid in selection["reason_claim_ids"]), f"{gid}: selection strengthens research confidence")
        groups[gid] = group
        assigned.update(ids)
    require(assigned == set(decks), "every candidate needs exactly one archetype analysis")

    dominance = report.get("dominance")
    require(isinstance(dominance, list) and (bool(dominance) or text(report.get("dominance_gap"))), "dominance analysis or explicit gap required")
    dominance_ids = set()
    for item in dominance:
        require(isinstance(item, dict), "dominance record must be an object")
        did, gid, status = (item.get(field) for field in ("id", "archetype_id", "status"))
        require(text(did) and did not in dominance_ids and gid in groups, "invalid dominance identity/archetype")
        require(status in {"supported", "hypothesis", "not-established"}, f"{did}: dominance status required")
        explanation_status = item.get("explanation_status")
        require(explanation_status in {"supported-inference", "hypothesis", "unknown"}, f"{did}: explanation status required separately from dominance observation")
        group = groups[gid]
        chapter = report["classes"][group["class"]]["chapter_id"]
        refs(item.get("observation_claim_ids"), f"{did}/observation", chapter)
        refs(item.get("driver_claim_ids"), f"{did}/drivers", chapter, required=explanation_status != "unknown")
        refs(item.get("counterplay_claim_ids"), f"{did}/counterplay", chapter, required=False)
        require(bool(item["counterplay_claim_ids"]) or text(item.get("counterplay_gap")), f"{did}: counterplay evidence or gap required")
        refs(item.get("limitation_claim_ids"), f"{did}/limitations", chapter)
        contrary(item.get("rival_explanations"), f"{did}/rival explanations", chapter)
        require((status == "supported" and explanation_status == "supported-inference") or text(item.get("uncertainty")), f"{did}: hypothesis/unknown needs uncertainty")
        dimensions, metrics = item.get("dimensions"), item.get("metric_ids")
        require(isinstance(dimensions, list) and bool(dimensions) and set(dimensions) <= {"popularity", "performance"}, f"{did}: dominance dimensions required")
        require(isinstance(metrics, list) and all(text(mid) and mid in stats for mid in metrics), f"{did}: invalid dominance metrics")
        for mid in metrics:
            statistic = stats[mid]
            require((statistic["grain"] == "archetype" and statistic["subject_id"] == gid)
                    or (statistic["grain"] == "deck" and statistic["subject_id"] in group["deck_ids"]), f"{did}: unrelated dominance statistic subject")
            require(not statistic.get("opponent"), f"{did}: one matchup cannot establish overall dominance")
        for field in ("matchup_metric_ids", "opponent_share_ids"):
            extra = item.get(field, [])
            require(isinstance(extra, list) and all(text(mid) and mid in stats for mid in extra), f"{did}: invalid {field}")
            for mid in extra:
                statistic = stats[mid]
                if field == "matchup_metric_ids":
                    require(statistic["metric"] == "winrate" and text(statistic.get("opponent"))
                            and ((statistic["grain"] == "archetype" and statistic["subject_id"] == gid)
                                 or (statistic["grain"] == "deck" and statistic["subject_id"] in group["deck_ids"])), f"{did}: unrelated matchup metric")
                else:
                    require(statistic["metric"] == "popularity" and statistic["grain"] == "archetype"
                            and not statistic.get("opponent"), f"{did}: opponent share needs archetype popularity")
        if status == "supported":
            require(bool(metrics), f"{did}: supported dominance needs metrics")
            for dimension in dimensions:
                metric = "winrate" if dimension == "performance" else "popularity"
                require(any(stats[mid]["metric"] == metric for mid in metrics), f"{did}: no {dimension} metric")
        dominance_ids.add(did)
    return {"archetypes": len(groups), "comparisons": len(comparison_ids), "dominance_assessments": len(dominance)}


def analysis_brief(report, sources, handoff):
    validate_package(report, sources, handoff)
    if report["schema_version"] == 1:
        return {"mechanical_checks_only": True, "legacy_run": True}
    decks = {deck["id"]: deck for deck in report["decks"]}
    stats = {row["id"]: row for row in report["statistics"]}
    claims = {row["claim_id"]: row for row in handoff["claims"]}

    def details(value):
        ids = set()
        def visit(node):
            if isinstance(node, dict):
                for key, item in node.items():
                    if key.endswith("claim_ids") and isinstance(item, list):
                        ids.update(item)
                    else:
                        visit(item)
            elif isinstance(node, list):
                for item in node:
                    visit(item)
        visit(value)
        return {cid: claims[cid] for cid in sorted(ids)}

    groups = []
    for group in report["archetypes"]:
        comparisons = []
        for record in group["comparisons"]:
            statistics = []
            for pair in record["stat_pairs"]:
                a, b = stats[pair["left"]], stats[pair["right"]]
                statistics.append({"left": a, "right": b, "difference_pp": round(a["value"] - b["value"], 6),
                                   "sample_games": [a["sample_games"], b["sample_games"]],
                                   "interpretation": "Observed difference; not a causal effect or significance test."})
            comparisons.append({**record, "card_delta": compare_decks(decks[record["left"]], decks[record["right"]]), "statistics": statistics})
        groups.append({**group, "comparisons": comparisons, "claims": details(group)})
    return {"mechanical_checks_only": True,
            "target_scope": {key: report[key] for key in ("as_of", "format", "patch", "rank", "region", "window_hours", "scope_note")},
            "scope_warnings": scope_mismatches(report), "archetypes": groups,
            "dominance": [{**item, "claims": details(item), "observed_metrics": [stats[mid] for mid in item["metric_ids"]],
                           "matchups": [stats[mid] for mid in item.get("matchup_metric_ids", [])],
                           "opponent_shares": [stats[mid] for mid in item.get("opponent_share_ids", [])]} for item in report["dominance"]],
            "dominance_gap": report.get("dominance_gap", "")}


def validate_analysis_review(report, article, review):
    if report["schema_version"] == 1:
        return []
    if not isinstance(review, dict):
        return ["factual review needs an object with meta_analysis"]
    errors, assessment = [], review.get("meta_analysis")
    if not isinstance(assessment, dict):
        return ["factual review needs meta_analysis with actual article quotes"]
    if scope_mismatches(report) and (not text(assessment.get("scope_quote")) or assessment["scope_quote"] not in article):
        errors.append("meta_analysis/scope_quote: disclose requested versus observed statistical scope in article")
    for field, expected in (("archetypes", report["archetypes"]), ("dominance", report["dominance"])):
        rows = assessment.get(field)
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not text(row.get("id")) for row in rows):
            errors.append(f"meta_analysis/{field}: invalid review rows")
            continue
        by_id = {row["id"]: row for row in rows}
        if set(by_id) != {row["id"] for row in expected} or len(by_id) != len(rows):
            errors.append(f"meta_analysis/{field}: incomplete or duplicate analysis coverage")
        for item in expected:
            row = by_id.get(item["id"], {})
            required = ["selection_quote", "limitation_quote"] if field == "archetypes" else ["observation_quote", "explanation_quote", "limitation_quote"]
            if field == "archetypes" and item["comparisons"]:
                required.append("comparison_quote")
            for key in required:
                if not text(row.get(key)) or row[key] not in article:
                    errors.append(f"meta_analysis/{item['id']}/{key}: actual article quote required")
    return errors


def validate_package(report, sources, handoff):
    """Check evidence links and comparability, never the semantic truth of prose."""
    require(isinstance(report, dict) and type(report.get("schema_version")) is int
            and report["schema_version"] in {1, 2}, "meta report schema_version must be 1 or 2")
    as_of = iso_date(report.get("as_of"))
    require(report.get("format") in {"standard", "wild"} and text(report.get("patch")), "patch/format required")
    require(all(text(report.get(key)) for key in ("rank", "region", "scope_note")), "scope, rank and region required")
    require(type(report.get("window_hours")) is int and report["window_hours"] > 0, "positive window_hours required")
    _, review, codec = runtimes()
    from editorteam.editorial_lab import canonical_url
    errors = review.validate_handoff(handoff, report["patch"])
    require(not errors, "; ".join(errors))
    require(handoff["style_profile"] == "meta-report", "handoff profile must be meta-report")
    # Source candidates use the same public contract as publication_run.submit.
    require(isinstance(sources, list) and bool(sources), "full source candidates required")
    source_ids, by_url, canonical_urls = {}, {}, set()
    for source in sources:
        require(isinstance(source, dict), "source candidate must be an object")
        sid, url, body = source.get("id"), source.get("url"), source.get("text")
        require(text(sid) and sid not in source_ids and valid_url(url), "invalid/duplicate source id or URL")
        canonical = canonical_url(url)
        require(canonical not in canonical_urls, "duplicate source URL")
        canonical_urls.add(canonical)
        require(text(body) and source.get("access") in {"public", "full"}, "full source snapshot required")
        require(source.get("sha256") == hashlib.sha256(body.encode("utf-8")).hexdigest(), "source hash mismatch")
        require(text(source.get("source")), "source provenance required")
        timestamp(source.get("retrieved_at"))
        source_ids[sid], by_url[url] = source, source
    evidence = {row["source_id"]: row for row in handoff["sources"]}
    claims = {row["claim_id"]: row for row in handoff["claims"]}
    chapters = {row["chapter_id"]: row for row in handoff["chapters"]}
    counterevidence = [row for claim in claims.values() for row in claim.get("research_context", {}).get("counterevidence", [])]
    for row in [*evidence.values(), *counterevidence]:
        require(row["url"] in by_url and row["quote"] in by_url[row["url"]]["text"], "evidence quote absent from full source")
        if row.get("content_sha256"):
            body = by_url[row["url"]]["text"].replace("\r\n", "\n")
            require(row["content_sha256"] == hashlib.sha256(body.encode()).hexdigest(), "evidence hash mismatch")

    def claim_ids(ids, label, chapter=None):
        require(isinstance(ids, list) and bool(ids) and all(text(cid) for cid in ids), f"{label}: claim ids required")
        require(len(set(ids)) == len(ids) and all(cid in claims for cid in ids), f"{label}: unknown/duplicate claim")
        if chapter is not None:
            require(chapter in chapters and set(ids) <= set(chapters[chapter]["required_claim_ids"]), f"{label}: claim outside class chapter")

    def linked(cid, ref, label):
        require(cid in claims and ref in evidence and ref in claims[cid]["evidence_refs"], f"{label}: unlinked evidence/claim")
        return evidence[ref]

    checks = report.get("official_checks")
    require(isinstance(checks, list) and any(isinstance(c, dict) and c.get("kind") == "patch" for c in checks), "official patch check required")
    for check in checks:
        require(isinstance(check, dict), "official check must be an object")
        proof = linked(check.get("claim_id"), check.get("evidence_ref"), "official patch")
        host = urlsplit(proof["url"]).hostname or ""
        require(host == "blizzard.com" or host.endswith(".blizzard.com"), "official patch needs Blizzard source")
        require(iso_date(check.get("effective_on")) <= as_of, "patch was not effective as of report date")
        iso_date(check.get("checked_on"))
    claim_ids(report.get("trend_claim_ids"), "trends")

    classes = report.get("classes")
    require(isinstance(classes, dict) and set(classes) == set(CLASSES), "account for all 11 classes")
    for key, row in classes.items():
        require(isinstance(row, dict) and row.get("chapter_id") in chapters, f"{key}: class chapter required")
    require(len({row["chapter_id"] for row in classes.values()}) == len(CLASSES), "distinct class chapters required")
    decks = report.get("decks")
    require(isinstance(decks, list) and all(isinstance(d, dict) for d in decks), "decks array required")
    by_deck, names, codes = {}, set(), set()
    for deck in decks:
        did, key, name = deck.get("id"), deck.get("class"), deck.get("name")
        require(text(did) and did not in by_deck and key in classes and text(name), "invalid deck identity/class/name")
        require((key, name.casefold()) not in names and text(deck.get("archetype")), "duplicate deck name or missing archetype")
        names.add((key, name.casefold()))
        for field in ("plan_claim_ids", "limitation_claim_ids", "legality_claim_ids"):
            claim_ids(deck.get(field), f"{did}/{field}", classes[key].get("chapter_id"))
        ref = deck.get("list_evidence_ref")
        require(ref in evidence, f"{did}: list evidence required")
        require(ref in {r for cid in deck["plan_claim_ids"] for r in claims[cid]["evidence_refs"]}, f"{did}: list evidence must support plan")
        normalized = codec.normalize_deck(deck.get("deck_list"))
        require(normalized["format"] == (2 if report["format"] == "standard" else 1), f"{did}: deck format mismatch")
        require(codec.decode(deck.get("code")) == normalized, f"{did}: code/list mismatch")
        require(deck["code"] not in codes, "duplicate deck code")
        codes.add(deck["code"])
        provenance = deck.get("code_provenance")
        require(provenance in {"author-export", "reconstructed-list"}, f"{did}: code provenance required")
        if provenance == "author-export":
            require(deck["code"] in by_url[evidence[ref]["url"]]["text"], f"{did}: author export absent from source")
        else:
            require(text(deck.get("reconstruction_note")), f"{did}: reconstruction note required")
        by_deck[did] = deck
    gaps, assigned = [], set()
    for key, row in classes.items():
        require(isinstance(row, dict) and row.get("status") in {"covered", "gap"}, f"{key}: unresolved class")
        ids = row.get("deck_ids")
        require(isinstance(ids, list) and all(text(did) for did in ids) and len(set(ids)) == len(ids), f"{key}: invalid deck ids")
        require(all(did in by_deck and by_deck[did]["class"] == key for did in ids), f"{key}: wrong class deck")
        claim_ids(row.get("assessment_claim_ids"), key, row.get("chapter_id"))
        visible = [did for did in ids if report["schema_version"] == 1 or by_deck[did].get("publish") is True]
        require(bool(visible) or text(row.get("gap")), f"{key}: published deck or gap required")
        if row["status"] == "gap" or not visible:
            require(text(row.get("gap")), f"{key}: gap reason required")
            gaps.append(key)
        assigned.update(ids)
    require(assigned == set(by_deck), "unassigned deck in report")

    stats, unknown = {}, []
    rows = report.get("statistics")
    require(isinstance(rows, list), "statistics array required")
    require(bool(rows) or text(report.get("statistics_gap")), "statistics or explicit statistics_gap required")
    for row in rows:
        require(isinstance(row, dict), "statistic must be an object")
        sid = row.get("id")
        require(text(sid) and sid not in stats, "invalid/duplicate statistic id")
        require(row.get("metric") in {"winrate", "popularity"} and row.get("grain") in {"deck", "archetype"}, f"{sid}: metric/grain required")
        require(text(row.get("subject_id")), f"{sid}: statistic subject required")
        if row["grain"] == "deck":
            require(row["subject_id"] in by_deck, f"{sid}: unknown deck subject")
        require(row.get("patch") == report["patch"] and row.get("format") == report["format"], f"{sid}: patch/format mismatch")
        for field in ("rank", "region", "population"):
            require(text(row.get(field)), f"{sid}: {field} required")
        require(row.get("opponent") is None or text(row["opponent"]), f"{sid}: invalid opponent filter")
        require(isinstance(row.get("filters", {}), dict), f"{sid}: filters must be an object")
        start, end = timestamp(row.get("start")), timestamp(row.get("end"))
        require(start < end and end.date() <= as_of, f"{sid}: invalid/future statistics period")
        count = row.get("sample_games")
        require((type(count) is int and count > 0) or (count is None and text(row.get("sample_note"))), f"{sid}: sample count or unknown sample note required")
        if count is None:
            unknown.append(sid)
        value = row.get("value")
        require(type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 100, f"{sid}: invalid percentage")
        source = source_ids.get(row.get("source_id"))
        require(source is not None, f"{sid}: source required")
        proof = linked(row.get("claim_id"), row.get("evidence_ref"), sid)
        require(proof["url"] == source["url"], f"{sid}: evidence/source mismatch")
        percentages = {float(n.replace(",", ".")) for n in re.findall(r"(?<![\w.,])([0-9]+(?:[.,][0-9]+)?)\s*%", proof["quote"])}
        require(value in percentages, f"{sid}: percentage absent from evidence quote")
        stats[sid] = row
    rankings = report.get("rankings")
    require(isinstance(rankings, list), "rankings array required")
    for ranking in rankings:
        require(isinstance(ranking, dict) and text(ranking.get("title")) and text(ranking.get("scope_note")), "ranking title/scope required")
        ids = ranking.get("stat_ids")
        require(isinstance(ids, list) and bool(ids) and all(text(sid) and sid in stats for sid in ids)
                and len(set(ids)) == len(ids), "ranking needs unique known statistics")
        selected = [stats[sid] for sid in ids]
        require(len({cohort_key(row) for row in selected}) == 1, "ranking mixes incomparable cohorts")
        require(len({row["subject_id"] for row in selected}) == len(selected), "ranking repeats the same subject")
        require([row["value"] for row in selected] == sorted((row["value"] for row in selected), reverse=True), "ranking must use descending percentages")
        require(ranking.get("universe") in {"source-table", "selected-decks"}, "ranking universe required")
        if ranking["universe"] == "source-table":
            ref = ranking.get("table_evidence_ref")
            require(ref in evidence and evidence[ref]["url"] == source_ids[selected[0]["source_id"]]["url"], "source-table ranking proof required")
    assessments = report.get("assessments", [])
    require(isinstance(assessments, list), "assessments array required")
    for row in assessments:
        require(isinstance(row, dict) and row.get("kind") in {"underrated", "overrated", "emerging"}
                and text(row.get("subject")) and text(row.get("scope_note")), "invalid editorial assessment")
        claim_ids(row.get("claim_ids"), "assessment")
    require(isinstance(report.get("gaps"), list) and all(text(g) for g in report["gaps"]), "gaps must be strings")
    analysis = validate_analysis(report, sources, handoff, stats) if report["schema_version"] == 2 else {}
    return {"status": "structure_valid", "mechanical_checks_only": True, "class_gaps": gaps,
            "selected_decks": len(published_decks(report)), "inspected_decks": len(decks),
            "statistics": len(stats), "statistics_with_unknown_sample": unknown,
            "scope_warnings": scope_mismatches(report), **analysis}


def audit_material(report, material):
    """Check required class sections and copyable codes, not prose quality."""
    errors, sections = [], {}
    headings = list(re.finditer(r"^## ([^\n]+)\s*$", material, re.MULTILINE))
    for index, match in enumerate(headings):
        title = match.group(1).strip()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(material)
        if title in sections:
            errors.append("duplicate class/section heading: " + title)
        sections[title] = material[match.end():end]
    def has_prose(section):
        section = re.sub(r"```.*?```", "", section, flags=re.DOTALL)
        section = re.sub(r"^#{1,6} .*?$", "", section, flags=re.MULTILINE)
        return bool(re.search(r"[А-Яа-яЁёA-Za-z]", section))

    for name in CLASSES.values():
        if name not in sections:
            errors.append("missing class section: " + name)
        elif not has_prose(sections[name]):
            errors.append("empty class section: " + name)
    expected = set()
    for deck in published_decks(report):
        section = sections.get(CLASSES[deck["class"]], "")
        heading = re.search(r"^### " + re.escape(deck["name"]) + r"\s*$", section, re.MULTILINE)
        if not heading:
            errors.append("missing deck heading: " + deck["name"])
            continue
        tail = section[heading.end():]
        boundary = re.search(r"^### ", tail, re.MULTILINE)
        if boundary:
            tail = tail[:boundary.start()]
        if not has_prose(tail):
            errors.append("missing deck explanation: " + deck["name"])
        blocks = re.findall(r"^```(?:text)?\n([^\n]+)\n```\s*$", tail, re.MULTILINE)
        if deck["code"] not in blocks:
            errors.append("missing code under correct deck: " + deck["name"])
        expected.add(deck["code"])
        if deck["code_provenance"] == "reconstructed-list" and "восстановлен" not in tail.casefold():
            errors.append("reconstructed code needs reader disclosure: " + deck["name"])
    for block in re.findall(r"^```(?:text)?\n([A-Za-z0-9+/=]+)\n```\s*$", material, re.MULTILINE):
        if block not in expected:
            errors.append("unselected deck code in material")
    allowed = {float(row["value"]) for row in report["statistics"]}
    for value in re.findall(r"(?<![\w.,])([0-9]+(?:[.,][0-9]+)?)\s*%", material):
        if float(value.replace(",", ".")) not in allowed:
            errors.append("percentage absent from research statistics: " + value)
    return errors


def accepted(run):
    run = Path(run)
    receipt = read_json(run / "accepted.json")
    for name in INPUTS:
        require(digest(run / name) == receipt["sha256"][name], f"accepted input changed: {name}; start a new research run")
    return read_json(run / "meta-report.json")


def prepare(run):
    run = Path(run)
    report, sources, handoff = (read_json(run / name) for name in INPUTS)
    result = validate_package(report, sources, handoff)
    require(not (run / "publication").exists() and not (run / "accepted.json").exists(), "publication already exists")
    pub, _, _ = runtimes()
    pub.init_run(run / "publication", brief=handoff["brief"], patch=report["patch"], profile="meta-report", shortcodes="off")
    pub.submit(run / "publication", stage="sources", artifact=run / "sources.json")
    state = pub.submit(run / "publication", stage="research", artifact=run / "publication-handoff.json")
    require(state["stage"] == "draft" and not state["blocked"], "publication research was blocked: " + str(state["blocked"]))
    write_json(run / "accepted.json", {"schema_version": 1, "sha256": {name: digest(run / name) for name in INPUTS}, "validation": result})
    return state


def next_task(run):
    run = Path(run)
    require((run / "meta-report.json").is_file(), "meta report run not initialized")
    if not (run / "accepted.json").exists():
        return {"stage": "research", "role": "research-team", "run": str(run.resolve()),
                "inputs": {"meta_report": str((run / "meta-report.json").resolve()), "research": str((run / "research").resolve())},
                "instructions": "Read skills/meta-report/SKILL.md and skills/meta-report/references/workflow.md. Research the verified patch, all 11 classes, lists and comparable statistics. Compile the ResearchTeam handoff; prepare only after evidence audit. No search has been performed by this helper."}
    accepted(run)
    pub, _, _ = runtimes()
    task = pub.next_task(run / "publication")
    task.setdefault("inputs", {})["meta_report"] = str((run / "meta-report.json").resolve())
    report = read_json(run / "meta-report.json")
    if report["schema_version"] == 2:
        task["analysis_brief"] = analysis_brief(report, read_json(run / "sources.json"), read_json(run / "publication-handoff.json"))
    if task["stage"] == "draft":
        task["instructions"] += " Read teams/editor-team/SKILL.md and skills/meta-report/references/workflow.md. Cover all classes using ## Russian class and ### exact deck name headings. Explain plan, key cards, conditions and limitations in connected prose. Copy each accepted code below its own deck. Preserve statistical scope and unknown sample sizes."
    elif task["stage"] == "fact_review":
        task["instructions"] += " Check every number's subject, source, grain, ranks, period, region and sample; distinguish popularity, performance and editorial judgement. Check current legality, runes, independent list provenance and all gameplay explanations. Inspect the entire article for contradictory recommendations and causal overclaims."
    elif task["stage"] == "literary_review":
        task["instructions"] += " Review the whole meta report for a clear ladder story, useful class choices, distinctive deck explanations and readable limits. Preserve author rhythm and strong passages; do not force identical paragraphs or introduce game facts."
    if report["schema_version"] == 2:
        task["instructions"] += " Read skills/meta-report/references/archetype-analysis.md. Use analysis_brief for exact list changes, conditional selection, matchup evidence, competing explanations and dominance hypotheses. Publish codes only for publish=true lists."
        if task["analysis_brief"]["scope_warnings"]:
            task["instructions"] += " target_scope differs from observed statistics: disclose these limits in the article and do not project all-rank/older data onto the requested ladder. Factual meta_analysis needs scope_quote from the article."
        if task["stage"] == "fact_review":
            task["instructions"] += " Add meta_analysis to factual JSON: archetypes [{id,selection_quote,comparison_quote,limitation_quote}], dominance [{id,observation_quote,explanation_quote,limitation_quote}]. Quote the actual article; verify the substantive explanation and uncertainty, not just quote presence. Do not treat selected research conclusions as a predetermined verdict."
    return task


def submit(run, *, stage, artifact, retry_review=False):
    run = Path(run)
    report = accepted(run)
    require(stage in {"draft", "fact_review", "literary_review"}, "sources/research are accepted together by prepare")
    if stage == "draft":
        errors = audit_material(report, Path(artifact).read_text(encoding="utf-8-sig"))
        require(not errors, "; ".join(errors))
    pub, _, _ = runtimes()
    if stage == "fact_review" and report["schema_version"] == 2:
        state = pub.status(run / "publication")
        draft = run / "publication" / state["artifacts"]["draft"]["path"]
        payload = read_json(artifact)
        errors = validate_analysis_review(report, draft.read_text(encoding="utf-8"), payload)
        # A negative review can identify missing prose: never demand invented
        # quotes before recording that rejection in the normal revision flow.
        negative = isinstance(payload, dict) and payload.get("status") in {"repair", "blocked"}
        require(not errors or negative, "; ".join(errors))
    return pub.submit(run / "publication", stage=stage, artifact=Path(artifact), retry_review=retry_review)


def revise(run, artifact):
    run = Path(run)
    report = accepted(run)
    errors = audit_material(report, Path(artifact).read_text(encoding="utf-8-sig"))
    require(not errors, "; ".join(errors))
    return runtimes()[0].revise(run / "publication", artifact=Path(artifact))


def export(run, output):
    run = Path(run)
    accepted(run)
    return runtimes()[0].export(run / "publication", output=Path(output))


def main(argv=None):
    # Windows pipes may inherit a legacy or ASCII encoding even on resumed runs.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "check", "prepare", "next", "status", "compare", "analysis", "submit", "revise", "export"):
        command = sub.add_parser(name)
        command.add_argument("run", type=Path)
        if name == "init":
            command.add_argument("--as-of", required=True)
            command.add_argument("--format", choices=("standard", "wild"), default="standard", dest="game_format")
            command.add_argument("--rank", default="all-ranks")
            command.add_argument("--region", default="all-regions")
            command.add_argument("--window-hours", type=int, default=24)
        if name in {"submit", "revise"}:
            command.add_argument("--artifact", required=True, type=Path)
        if name == "submit":
            command.add_argument("--stage", required=True, choices=("draft", "fact_review", "literary_review"))
            command.add_argument("--retry-review", action="store_true")
        if name == "export":
            command.add_argument("--output", required=True, type=Path)
        if name == "compare":
            command.add_argument("--left", required=True)
            command.add_argument("--right", required=True)
    args = vars(parser.parse_args(argv))
    command, run = args.pop("command"), args.pop("run")
    try:
        if command == "init":
            result = initialize(run, **args)
        elif command == "check":
            result = validate_package(*(read_json(run / name) for name in INPUTS))
        elif command == "prepare":
            result = prepare(run)
        elif command == "compare":
            decks = {deck["id"]: deck for deck in read_json(run / "meta-report.json")["decks"]}
            result = compare_decks(decks[args["left"]], decks[args["right"]])
        elif command == "analysis":
            result = analysis_brief(*(read_json(run / name) for name in INPUTS))
        elif command in {"next", "status"}:
            result = next_task(run)
        elif command == "submit":
            result = submit(run, **args)
        elif command == "revise":
            result = revise(run, args["artifact"])
        else:
            result = export(run, args["output"])
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"status": "blocked", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
