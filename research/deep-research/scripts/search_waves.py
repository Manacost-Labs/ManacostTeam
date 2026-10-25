#!/usr/bin/env python3
"""Plan search in waves and stop when consecutive waves add nothing new.

Wave 1 seeds every executor lane (official, statistics, reddit, x, youtube,
chinese, podcast, web) across en/ru/zh with the localized entity names from
``plan.query_localization``. Each later wave combines three passes:

* follow links from sources inspected in earlier waves (``outbound_links`` from
  ``fetch_source.py``, or URLs printed in the snapshot);
* a refutation pass for critical/material claims that have neither challenging
  evidence nor a challenge search (the topic itself before any claim exists);
* gap queries for lanes that have not produced an inspected source yet.

``close`` records what a wave added: inspected sources with an unseen identity
and lineage, and claims first supported by them. The run is saturated after
``threshold_waves`` consecutive dry waves, a dry wave being one with no
pending queries, fewer than ``min_new_sources`` new sources and no new claim.
Configuration and every wave record live in ``search-waves.json``.

Planned records are not executed queries. Copy a record into ``queries.jsonl``
with ``executed_at``, ``status`` and ``result_source_ids`` once it ran; keep its
``wave`` and ``executor`` so the wave can be closed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from platform_coverage import INSPECTED, inspection_identity, platform_for_url
from plan_queries import (
    PLAN_FILE,
    TEMPLATES,
    branch_list,
    build_plan,
    load_json,
    load_jsonl,
    localized_phrase,
    render as template_render,
    version_markers,
)
from search_support import canonical_url, next_id, normalize_query
from source_classes import SOURCE_CLASSES, query_lane, source_class

WAVES_FILE = "search-waves.json"
SCHEMA_VERSION = "1.0"
DEFAULT_THRESHOLD = 2
DEFAULT_MIN_NEW = 1
DEFAULT_MAX_WAVES = 6
DEFAULT_MAX_LINKS = 20
DEFAULT_LANGUAGES = ("en", "ru", "zh")
SEED_FAMILIES = (
    "general", "primary", "statistics", "experts", "reddit", "x", "youtube",
    "mistakes", "counterargument", "freshness", "localized",
)
FAILED = {"blocked", "failed", "error", "unavailable"}
DONE = {"executed", "completed", "partial", "no_results"} | FAILED | {"skipped"}

# Domains each executor restricts its search to; ``web`` is unrestricted.
EXECUTOR_DOMAINS: dict[str, tuple[str, ...]] = {
    "official": ("hearthstone.blizzard.com", "news.blizzard.com", "us.forums.blizzard.com", "playhearthstone.com"),
    "statistics": ("hsreplay.net", "hsguru.com", "firestoneapp.com", "d0nkey.top", "vicioussyndicate.com"),
    "reddit": ("reddit.com",),
    "x": ("x.com", "twitter.com"),
    "youtube": ("youtube.com",),
    "chinese": ("hs.blizzard.cn", "nga.cn", "iyingdi.com", "bilibili.com", "lushi.163.com", "17173.com"),
    "podcast": (
        "vicioussyndicate.com", "coinconcede.com", "hearthstonecommute.libsyn.com",
        "borntobewildhs.com", "podcasts.apple.com", "open.spotify.com",
    ),
    "web": (),
}
PODCAST_TEMPLATES = {
    "en": ("{topic} podcast", "{topic} podcast {version}"),
    "ru": ("{topic} подкаст",),
    "zh": (),
}
# Patch notes govern most questions: every version marker gets its own
# official query first, in English and on the Chinese official site.
ANCHOR_TEMPLATES = {
    "en": (("official", "Hearthstone {version} patch notes"),),
    "ru": (),
    "zh": (("chinese", "炉石传说 {version} 补丁说明"),),
}
REFUTATION_EXECUTORS = ("web", "reddit")
GAP_TEMPLATES = {"en": ("{entity} {version}", "{entity}"), "ru": ("{entity} {version}", "{entity}"), "zh": ("{entity}",)}
SKIPPED_LINK_RE = re.compile(
    r"\.(?:css|js|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|mp4|mp3|zip)(?:$|\?)"
    r"|/(?:login|signin|signup|register|share|intent|privacy|terms|legal|cookie)",
    re.IGNORECASE,
)
URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>\"')\]]+")
LANE_PRIORITY = ("official", "statistics", "chinese", "podcast", "reddit", "youtube", "x", "web")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def strip_site(query: str) -> str:
    """Executors restrict domains themselves; drop the search-engine operator."""
    return " ".join(part for part in query.split() if not part.lower().startswith("site:"))


def executor_for(record: dict[str, Any]) -> str:
    return query_lane(record)


def annotate(record: dict[str, Any], wave: int, executor: str | None = None) -> dict[str, Any]:
    lane = executor or executor_for(record)
    sites = [part[5:].lower() for part in str(record["query"]).split() if part.lower().startswith("site:")]
    record.update(
        {
            "wave": wave,
            "executor": lane,
            # An explicit site: operator narrows the executor to that venue.
            "include_domains": sites or list(EXECUTOR_DOMAINS[lane]),
            "executor_query": strip_site(str(record["query"])) if record.get("query_kind") != "follow_link" else record["query"],
        }
    )
    return record


def _round_robin(queues: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    queues = [list(queue) for queue in queues]
    while any(queues):
        for queue in queues:
            if queue:
                ordered.append(queue.pop(0))
    return ordered


def interleave(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anchors first, then round-robin across executors (languages alternate inside each)."""
    anchors = [record for record in records if record.get("priority") == "anchor"]
    lanes: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for record in records:
        if record.get("priority") != "anchor":
            lanes.setdefault(record["executor"], {}).setdefault(str(record.get("language", "")), []).append(record)
    per_lane = [_round_robin([languages[key] for key in sorted(languages)]) for _, languages in
                sorted(lanes.items(), key=lambda item: LANE_PRIORITY.index(item[0]))]
    return anchors + _round_robin(per_lane)


class WaveContext:
    """Bundle inputs shared by every wave."""

    def __init__(
        self,
        *,
        branches: list[tuple[str | None, str]],
        languages: list[str],
        localization: dict[str, Any],
        markers: list[str],
        year: str,
        coverage_enabled: bool,
    ) -> None:
        unsupported = [language for language in languages if language not in TEMPLATES]
        if unsupported:
            raise ValueError(f"unsupported language: {', '.join(unsupported)}")
        self.branches = branches
        self.languages = languages
        self.localization = localization
        self.markers = markers
        self.year = year
        self.coverage_enabled = coverage_enabled

    @classmethod
    def from_bundle(cls, root: Path, languages: list[str]) -> "WaveContext":
        manifest = load_json(root / "manifest.json")
        plan_path = root / "plan.json"
        plan = load_json(plan_path) if plan_path.is_file() else None
        localization = (plan or {}).get("query_localization", {})
        if not isinstance(localization, dict):
            raise ValueError("plan.query_localization must be an object")
        as_of = str(manifest.get("as_of", ""))
        return cls(
            branches=branch_list(manifest, plan, [], []),
            languages=languages,
            localization=localization,
            markers=version_markers(manifest, []),
            year=as_of[:4] if as_of[:4].isdigit() else utc_now()[:4],
            coverage_enabled="coverage_contract_version" in manifest,
        )

    def topics(self, language: str) -> list[tuple[str | None, str, str]]:
        result = []
        for section_id, topic in self.branches:
            phrases = self.localization.get("topics", {}).get(section_id or "__all__", {})
            result.append((section_id, topic, localized_phrase(phrases, language, topic)))
        return result

    def for_language(self, language: str) -> dict[str, Any]:
        """Entities without a name in this language are skipped, not translated."""
        entries = [
            entry for entry in self.localization.get("entities", [])
            if isinstance(entry, dict) and isinstance(entry.get("names"), dict) and entry["names"].get(language)
        ]
        return {**self.localization, "entities": entries}

    def missing_names(self) -> dict[str, list[str]]:
        missing: dict[str, list[str]] = {}
        for entry in self.localization.get("entities", []):
            names = entry.get("names", {}) if isinstance(entry, dict) else {}
            gaps = [language for language in self.languages if not names.get(language)]
            if gaps:
                missing[str(entry.get("entity_id"))] = gaps
        return missing

    def entities(self, language: str) -> list[str]:
        names = []
        for entry in self.localization.get("entities", []):
            value = entry.get("names", {}).get(language) if isinstance(entry, dict) else None
            names.extend([value] if isinstance(value, str) else value or [])
        return [name for name in names if isinstance(name, str) and name.strip()]


def _record(query_id: str, *, language: str, query: str, topic: str, family: str, pass_name: str,
            section_id: str | None, coverage: bool, **extra: Any) -> dict[str, Any]:
    record = {
        "query_id": query_id, "pass": pass_name, "family": family, "language": language,
        "query": " ".join(query.split()), "topic": topic, "status": "planned", "planned_at": utc_now(),
        "target_platform": "web",
    }
    if coverage and section_id:
        record["deliverable_section_ids"] = [section_id]
    record.update(extra)
    return record


def render(template: str, *, topic: str, year: str = "", version: str | None = None, entity: str | None = None) -> str | None:
    return template_render(template, topic=topic, year=year, version=version, entity=entity)


def seed_wave(ctx: WaveContext, existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = {str(record.get("query_id")) for record in existing}
    texts = [str(record.get("query", "")) for record in existing if record.get("query")]
    anchors: list[dict[str, Any]] = []
    for language in ctx.languages:
        for lane, template in ANCHOR_TEMPLATES.get(language, ()):
            for version in ctx.markers:
                query_id = next_id("QRY", ids)
                ids.add(query_id)
                anchors.append(annotate(_record(
                    query_id, language=language, query=template.format(version=version), topic=ctx.branches[0][1],
                    family="primary", pass_name="discovery", section_id=None, coverage=ctx.coverage_enabled,
                    version_marker=version, priority="anchor",
                ), 1, lane))
    records: list[dict[str, Any]] = []
    for language in ctx.languages:
        lane_records = build_plan(
            branches=ctx.branches, families=list(SEED_FAMILIES), languages=[language],
            entities=[], markers=ctx.markers, year=ctx.year, existing_queries=texts + [r["query"] for r in records],
            existing_ids=ids, coverage_enabled=ctx.coverage_enabled, localization=ctx.for_language(language),
        )
        ids.update(record["query_id"] for record in lane_records)
        records.extend(annotate(record, 1) for record in lane_records)
        for section_id, topic, phrase in ctx.topics(language):
            for template in PODCAST_TEMPLATES.get(language, ()):
                for version in ctx.markers if "{version}" in template else [None]:
                    query = render(template, topic=phrase, version=version)
                    if not query:
                        continue
                    query_id = next_id("QRY", ids)
                    ids.add(query_id)
                    records.append(annotate(_record(
                        query_id, language=language, query=query, topic=topic, family="experts",
                        pass_name="discovery", section_id=section_id, coverage=ctx.coverage_enabled,
                    ), 1, "podcast"))
    return interleave(anchors + records)


def source_waves(queries: list[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, int]:
    """First wave in which each source was linked to an executed query."""
    wave_of = {
        str(record.get("query_id")): int(record["wave"])
        for record in queries
        if isinstance(record.get("wave"), int) and record.get("executed_at") and record.get("status") != "planned"
    }
    first: dict[str, int] = {}
    for record in queries:
        wave = wave_of.get(str(record.get("query_id")))
        if wave is None:
            continue
        for source_id in record.get("result_source_ids") or []:
            first[source_id] = min(first.get(source_id, wave), wave)
    for source in sources:
        for query_id in source.get("found_by_query_ids") or []:
            wave = wave_of.get(str(query_id))
            if wave is not None:
                identity = str(source.get("source_id"))
                first[identity] = min(first.get(identity, wave), wave)
    return first


def source_url(source: dict[str, Any]) -> str:
    for field in ("canonical_url", "final_url", "url", "requested_url"):
        if isinstance(source.get(field), str) and source[field].startswith(("http://", "https://")):
            return source[field]
    return ""


def outbound_links(root: Path | None, source: dict[str, Any]) -> list[str]:
    links = [link for link in source.get("outbound_links") or [] if isinstance(link, str)]
    snapshot = source.get("snapshot_path")
    if not links and root is not None and isinstance(snapshot, str):
        path = (root / snapshot).resolve()
        if path.is_file() and root.resolve() in path.parents:
            links = URL_IN_TEXT_RE.findall(path.read_text(encoding="utf-8", errors="replace"))
    return links


def follow_wave(root: Path | None, wave: int, queries: list[dict[str, Any]], sources: list[dict[str, Any]],
                planned: list[dict[str, Any]], candidates: list[dict[str, Any]], ids: set[str],
                *, max_links: int, coverage: bool) -> list[dict[str, Any]]:
    first = source_waves(queries, sources)
    known = {canonical_url(source_url(source)) for source in sources if source_url(source)}
    known |= {canonical_url(str(record.get("url"))) for record in candidates if record.get("url")}
    known |= {canonical_url(str(record.get("follow_url"))) for record in planned + queries if record.get("follow_url")}
    picks: dict[str, tuple[str, dict[str, Any]]] = {}
    for source in sources:
        identity = str(source.get("source_id"))
        if source.get("access_integrity") not in INSPECTED or first.get(identity, 0) >= wave:
            continue
        origin_host = (canonical_url(source_url(source)).split("/") + ["", "", ""])[2]
        for link in outbound_links(root, source):
            canonical = canonical_url(link)
            if canonical in known or canonical in picks or SKIPPED_LINK_RE.search(link):
                continue
            lane = source_class(link)
            host = canonical.split("/")[2] if canonical.count("/") >= 2 else ""
            # Unknown web links count only when they stay on the origin's site.
            if lane == "web" and host != origin_host:
                continue
            picks[canonical] = (link, source)
    ordered = sorted(picks.items(), key=lambda item: LANE_PRIORITY.index(source_class(item[1][0])))
    records = []
    for _, (link, source) in ordered[:max_links]:
        query_id = next_id("QRY", ids)
        ids.add(query_id)
        sections = source.get("deliverable_section_ids") or []
        record = _record(
            query_id, language=str(source.get("language") or "en"), query=link,
            topic=f"link from {source.get('source_id')}", family="general", pass_name="gap",
            section_id=sections[0] if sections else None, coverage=coverage,
            query_kind="follow_link", follow_url=link, origin_source_ids=[source.get("source_id")],
            target_platform=platform_for_url(link),
        )
        records.append(annotate(record, wave, source_class(link)))
    return records


def unchallenged_claims(claims: list[dict[str, Any]]) -> list[str]:
    return [
        str(claim.get("claim_id")) for claim in claims
        if claim.get("importance") in {"critical", "material"}
        and claim.get("status") != "rejected"
        and not claim.get("challenging_evidence_ids")
        and not (isinstance(claim.get("challenge_search"), dict) and claim["challenge_search"].get("query_ids"))
    ]


def refutation_wave(ctx: WaveContext, wave: int, claims: list[dict[str, Any]], prior: list[dict[str, Any]],
                    ids: set[str]) -> list[dict[str, Any]]:
    targets = unchallenged_claims(claims)
    challenged = {cid for record in prior for cid in record.get("challenge_claim_ids", [])}
    has_topic_pass = any(record.get("pass") == "contradiction" and record.get("wave") for record in prior)
    if claims:
        targets = [claim_id for claim_id in targets if claim_id not in challenged]
        if not targets:
            return []
    elif has_topic_pass:
        return []
    seen = {(record.get("executor"), normalize_query(str(record.get("query", "")))) for record in prior}
    by_id = {str(claim.get("claim_id")): claim for claim in claims}
    records = []
    for language in ctx.languages:
        entities = ctx.entities(language)
        # A claim's own search phrase targets it; the topic covers claims without one.
        phrases = [
            (None, str(by_id[claim_id].get("claim", claim_id)), by_id[claim_id]["search_phrases"][language], [claim_id])
            for claim_id in targets
            if isinstance(by_id.get(claim_id, {}).get("search_phrases"), dict) and by_id[claim_id]["search_phrases"].get(language)
        ]
        phrases += [(section_id, topic, phrase, targets) for section_id, topic, phrase in ctx.topics(language)]
        for section_id, topic, phrase, claim_ids in phrases:
            for template in TEMPLATES[language].get("counterargument", ()):
                values = entities if "{entity}" in template else [None]
                for entity in values:
                    query = render(template, topic=phrase, entity=entity)
                    if not query:
                        continue
                    for lane in REFUTATION_EXECUTORS if language != "zh" else ("chinese",):
                        key = (lane, normalize_query(query))
                        if key in seen:
                            continue
                        seen.add(key)
                        query_id = next_id("QRY", ids)
                        ids.add(query_id)
                        record = _record(
                            query_id, language=language, query=query, topic=topic, family="counterargument",
                            pass_name="contradiction", section_id=section_id, coverage=ctx.coverage_enabled,
                            challenge_claim_ids=claim_ids,
                        )
                        records.append(annotate(record, wave, lane))
    return records


def lane_yield(queries: list[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, int]:
    by_id = {str(source.get("source_id")): source for source in sources}
    found = dict.fromkeys(SOURCE_CLASSES, 0)
    for record in queries:
        if record.get("status") in FAILED or not record.get("executed_at"):
            continue
        for source_id in record.get("result_source_ids") or []:
            source = by_id.get(source_id, {})
            if source.get("access_integrity") in INSPECTED:
                found[executor_for(record)] += 1
    return found


def gap_wave(ctx: WaveContext, wave: int, queries: list[dict[str, Any]], sources: list[dict[str, Any]],
             prior: list[dict[str, Any]], ids: set[str]) -> list[dict[str, Any]]:
    tried = {executor_for(record) for record in queries if record.get("executed_at")}
    found = lane_yield(queries, sources)
    seen = {(record.get("executor"), normalize_query(str(record.get("query", "")))) for record in prior}
    records = []
    for lane in SOURCE_CLASSES:
        if lane == "web" or found[lane] or lane not in tried:
            continue
        languages = ["zh"] if lane == "chinese" else [language for language in ctx.languages if language != "zh"]
        for language in languages:
            if language not in ctx.languages:
                continue
            for section_id, topic, phrase in ctx.topics(language):
                for template in GAP_TEMPLATES[language]:
                    for entity in ctx.entities(language) or [phrase]:
                        for version in ctx.markers if "{version}" in template else [None]:
                            query = render(template, topic=phrase, entity=entity, version=version)
                            if not query:
                                continue
                            key = (lane, normalize_query(query))
                            if key in seen:
                                continue
                            seen.add(key)
                            query_id = next_id("QRY", ids)
                            ids.add(query_id)
                            records.append(annotate(_record(
                                query_id, language=language, query=query, topic=topic, family="general",
                                pass_name="gap", section_id=section_id, coverage=ctx.coverage_enabled,
                                queue_reason=f"{lane} lane has no inspected source yet",
                            ), wave, lane))
    return records


def plan_wave(ctx: WaveContext, wave: int, *, root: Path | None, queries: list[dict[str, Any]],
              sources: list[dict[str, Any]], claims: list[dict[str, Any]], planned: list[dict[str, Any]],
              candidates: list[dict[str, Any]], max_links: int = DEFAULT_MAX_LINKS) -> list[dict[str, Any]]:
    prior = planned + queries
    if wave == 1:
        return seed_wave(ctx, prior)
    ids = {str(record.get("query_id")) for record in prior}
    records = follow_wave(root, wave, queries, sources, planned, candidates, ids,
                          max_links=max_links, coverage=ctx.coverage_enabled)
    records += refutation_wave(ctx, wave, claims, prior + records, ids)
    records += gap_wave(ctx, wave, queries, sources, prior + records, ids)
    return interleave(records)


def claim_waves(claims: list[dict[str, Any]], evidence: list[dict[str, Any]], first: dict[str, int]) -> dict[str, int]:
    source_of = {str(item.get("evidence_id")): str(item.get("source_id")) for item in evidence}
    result: dict[str, int] = {}
    for claim in claims:
        waves = [
            first[source_of[eid]]
            for field in ("supporting_evidence_ids", "challenging_evidence_ids")
            for eid in claim.get(field) or []
            if source_of.get(eid) in first
        ]
        if waves:
            result[str(claim.get("claim_id"))] = min(waves)
    return result


def close_wave(state: dict[str, Any], wave: int, *, queries: list[dict[str, Any]], sources: list[dict[str, Any]],
               claims: list[dict[str, Any]], evidence: list[dict[str, Any]],
               novelty: Callable[[dict[str, Any]], bool] | None = None) -> dict[str, Any]:
    """Append the wave record and recompute saturation; returns the record."""
    planned_ids = state["waves_planned"].get(str(wave), [])
    in_wave = [record for record in queries if record.get("wave") == wave]
    executed_ids = {str(record.get("query_id")) for record in in_wave if record.get("status") in DONE and record.get("executed_at")}
    pending = sorted(set(planned_ids) - executed_ids)
    first = source_waves(queries, sources)
    counts = novelty or (lambda source: source.get("access_integrity") in INSPECTED)
    seen_identities: set[str] = set()
    seen_lineages: set[str] = set()
    new_sources: list[str] = []
    for source in sorted(sources, key=lambda item: (first.get(str(item.get("source_id")), 10**6), str(item.get("source_id")))):
        identity = str(source.get("source_id"))
        source_wave = first.get(identity)
        if source_wave is None or source_wave > wave or not counts(source):
            continue
        key = inspection_identity(source_url(source)) if source_url(source) else identity
        lineage = str(source.get("lineage_id") or key)
        fresh = key not in seen_identities and lineage not in seen_lineages
        seen_identities.add(key)
        seen_lineages.add(lineage)
        if source_wave == wave and fresh:
            new_sources.append(identity)
    new_claims = sorted(claim_id for claim_id, value in claim_waves(claims, evidence, first).items() if value == wave)
    executors: dict[str, dict[str, int]] = {}
    for record in in_wave:
        lane = executors.setdefault(executor_for(record), {"executed": 0, "failed": 0, "new_sources": 0})
        if record.get("status") in FAILED:
            lane["failed"] += 1
        elif str(record.get("query_id")) in executed_ids:
            lane["executed"] += 1
    wave_of_source = {}
    for record in in_wave:
        for source_id in record.get("result_source_ids") or []:
            wave_of_source.setdefault(source_id, executor_for(record))
    for source_id in new_sources:
        lane = wave_of_source.get(source_id)
        if lane:
            executors[lane]["new_sources"] += 1
    config = state["config"]
    record = {
        "wave": wave,
        "closed_at": utc_now(),
        "queries_planned": len(planned_ids),
        "queries_executed": len(executed_ids),
        "queries_failed": sum(1 for item in in_wave if item.get("status") in FAILED),
        "pending_query_ids": pending,
        "new_source_ids": new_sources,
        "new_claim_ids": new_claims,
        "executors": executors,
        "dry": not pending and len(new_sources) < config["min_new_sources"] and not new_claims,
    }
    state["waves"] = [item for item in state["waves"] if item["wave"] != wave] + [record]
    state["waves"].sort(key=lambda item: item["wave"])
    state["saturation"] = saturation(state)
    return record


def saturation(state: dict[str, Any]) -> dict[str, Any]:
    config = state["config"]
    trailing = 0
    for record in reversed(state["waves"]):
        if not record["dry"]:
            break
        trailing += 1
    saturated = trailing >= config["threshold_waves"]
    exhausted = len(state["waves"]) >= config["max_waves"]
    reason = (
        f"{trailing} consecutive dry waves (threshold {config['threshold_waves']})" if saturated
        else f"wave limit {config['max_waves']} reached before saturation" if exhausted
        else f"{trailing}/{config['threshold_waves']} consecutive dry waves"
    )
    return {
        "saturated": saturated,
        "consecutive_dry_waves": trailing,
        "waves_closed": len(state["waves"]),
        "stop": saturated or exhausted,
        "reason": reason,
        "decided_at": utc_now(),
    }


def new_state(threshold: int, min_new: int, max_waves: int, languages: list[str]) -> dict[str, Any]:
    for name, value in (("threshold", threshold), ("min-new", min_new), ("max-waves", max_waves)):
        if type(value) is not int or value < 1:
            raise ValueError(f"--{name} must be a positive integer")
    return {
        "schema_version": SCHEMA_VERSION,
        "config": {"threshold_waves": threshold, "min_new_sources": min_new, "max_waves": max_waves, "languages": languages},
        "waves_planned": {},
        "waves": [],
        "saturation": {"saturated": False, "consecutive_dry_waves": 0, "waves_closed": 0, "stop": False,
                       "reason": "no wave closed yet", "decided_at": utc_now()},
    }


def validate_state(state: Any) -> list[str]:
    """Structural check used by the bundle validator."""
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION:
        return [f"{WAVES_FILE}: schema_version must be {SCHEMA_VERSION}"]
    errors = []
    config = state.get("config", {})
    for field in ("threshold_waves", "min_new_sources", "max_waves"):
        if type(config.get(field)) is not int or config[field] < 1:
            errors.append(f"{WAVES_FILE}: config.{field} must be a positive integer")
    waves = state.get("waves", [])
    if [item.get("wave") for item in waves] != list(range(1, len(waves) + 1)):
        errors.append(f"{WAVES_FILE}: waves must be closed in order 1..n")
    if errors:
        return errors
    for item in waves:
        expected = (not item.get("pending_query_ids") and len(item.get("new_source_ids", [])) < config["min_new_sources"]
                    and not item.get("new_claim_ids"))
        if item.get("dry") is not expected:
            errors.append(f"{WAVES_FILE}: wave {item.get('wave')} dry flag disagrees with its counts")
    recomputed = saturation(state)
    if bool(state.get("saturation", {}).get("saturated")) != recomputed["saturated"]:
        errors.append(f"{WAVES_FILE}: saturation.saturated disagrees with the wave records")
    return errors


def load_state(root: Path) -> dict[str, Any] | None:
    path = root / WAVES_FILE
    if not path.is_file():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_state(state)
    if errors:
        raise ValueError("; ".join(errors))
    return state


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def fill_entity_names(localization: dict[str, Any], languages: list[str],
                      resolve: Callable[[int], dict[str, Any]]) -> list[str]:
    """Add missing en/ru/zh names for entities that carry a DBF id."""
    changed = []
    for entry in localization.get("entities", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("dbf"), int):
            continue
        names = entry.setdefault("names", {})
        if all(names.get(language) for language in languages):
            continue
        result = resolve(entry["dbf"])
        for language in languages:
            if not names.get(language) and result["names"].get(language):
                names[language] = result["names"][language]
                entry.setdefault("name_sources", {})[language] = result["name_sources"][language]
                changed.append(f"{entry.get('entity_id')}:{language}")
    return changed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="Plan the next wave into query-plan.jsonl")
    plan.add_argument("directory")
    plan.add_argument("--language", action="append", default=[], help="Default en, ru, zh")
    plan.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD, help="Dry waves in a row that saturate the run")
    plan.add_argument("--min-new", type=int, default=DEFAULT_MIN_NEW, help="New inspected sources a wave needs to not be dry")
    plan.add_argument("--max-waves", type=int, default=DEFAULT_MAX_WAVES)
    plan.add_argument("--max-links", type=int, default=DEFAULT_MAX_LINKS)
    plan.add_argument("--apply", action="store_true")
    plan.add_argument("--json", action="store_true")
    tasks = sub.add_parser("tasks", help="Print one executor's queue for a wave as JSONL")
    tasks.add_argument("directory")
    tasks.add_argument("--wave", type=int, required=True)
    tasks.add_argument("--executor", choices=SOURCE_CLASSES, required=True)
    close = sub.add_parser("close", help="Record what the wave added and recompute saturation")
    close.add_argument("directory")
    close.add_argument("--wave", type=int, required=True)
    names = sub.add_parser("names", help="Fill en/ru/zh entity names from DBF ids (Koloda + HearthstoneJSON)")
    names.add_argument("directory")
    names.add_argument("--language", action="append", default=[])
    names.add_argument("--apply", action="store_true")
    status = sub.add_parser("status", help="Print saturation and whether to continue")
    status.add_argument("directory")
    status.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.directory).expanduser().resolve()
    try:
        state = load_state(root)
        if args.command == "status":
            if state is None:
                raise ValueError(f"no {WAVES_FILE}; run: search_waves.py plan {args.directory} --apply")
            if args.json:
                print(json.dumps(state, ensure_ascii=False, indent=2))
            else:
                sat = state["saturation"]
                print(f"Search waves: {sat['waves_closed']} closed; {sat['reason']}; next: {'stop' if sat['stop'] else 'continue'}")
                for item in state["waves"]:
                    print(f"- wave {item['wave']}: {item['queries_executed']}/{item['queries_planned']} executed, "
                          f"{len(item['new_source_ids'])} new sources, {len(item['new_claim_ids'])} new claims"
                          + (" (dry)" if item["dry"] else ""))
            return 0
        if args.command == "names":
            from hearthstone_names import HearthstoneJsonNames, KolodaNameResolver, search_names

            plan_path = root / "plan.json"
            plan = load_json(plan_path)
            localization = plan.setdefault("query_localization", {"topics": {}, "entities": []})
            koloda, hsjson = KolodaNameResolver(), HearthstoneJsonNames()
            changed = fill_entity_names(
                localization, list(dict.fromkeys(args.language)) or list(DEFAULT_LANGUAGES),
                lambda dbf: search_names(dbf, koloda=koloda, hsjson=hsjson),
            )
            print(f"Entity names: {len(changed)} added" + (f" ({', '.join(changed)})" if changed else ""))
            if args.apply and changed:
                write_json(plan_path, plan)
            elif changed:
                print("Preview only; use --apply to write plan.json")
            return 0
        planned = load_jsonl(root / PLAN_FILE)
        queries = load_jsonl(root / "queries.jsonl")
        if args.command == "tasks":
            ids = set((state or {}).get("waves_planned", {}).get(str(args.wave), []))
            for record in planned:
                if record.get("query_id") in ids and record.get("executor") == args.executor:
                    print(json.dumps(record, ensure_ascii=False))
            return 0
        sources = load_jsonl(root / "sources.jsonl")
        claims = load_jsonl(root / "claims.jsonl")
        if args.command == "close":
            if state is None or str(args.wave) not in state["waves_planned"]:
                raise ValueError(f"wave {args.wave} was not planned")
            if args.wave != len(state["waves"]) + 1 and args.wave not in {item["wave"] for item in state["waves"]}:
                raise ValueError(f"close wave {len(state['waves']) + 1} first")
            record = close_wave(state, args.wave, queries=queries, sources=sources, claims=claims,
                                evidence=load_jsonl(root / "evidence.jsonl"))
            write_json(root / WAVES_FILE, state)
            sat = state["saturation"]
            print(f"Wave {args.wave}: {len(record['new_source_ids'])} new sources, {len(record['new_claim_ids'])} new claims, "
                  f"{len(record['pending_query_ids'])} pending{' (dry)' if record['dry'] else ''}; "
                  f"{sat['reason']}; next: {'stop' if sat['stop'] else 'continue'}")
            return 0
        languages = list(dict.fromkeys(args.language)) or list((state or {}).get("config", {}).get("languages") or DEFAULT_LANGUAGES)
        if state is None:
            state = new_state(args.threshold, args.min_new, args.max_waves, languages)
        wave = len(state["waves"]) + 1
        if str(wave - 1) in state["waves_planned"] and wave - 1 > len(state["waves"]):
            raise ValueError(f"close wave {wave - 1} before planning the next one")
        if str(wave) in state["waves_planned"]:
            raise ValueError(f"wave {wave} is already planned; execute and close it")
        if state["saturation"]["stop"]:
            raise ValueError(f"search stopped: {state['saturation']['reason']}")
        ctx = WaveContext.from_bundle(root, languages)
        records = plan_wave(ctx, wave, root=root, queries=queries, sources=sources, claims=claims,
                            planned=planned, candidates=load_jsonl(root / "candidates.jsonl"), max_links=args.max_links)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for entity_id, gaps in ctx.missing_names().items() if wave == 1 else ():
        print(f"note: {entity_id} has no {', '.join(gaps)} name; run search_waves.py names DIR --apply or add it to plan.json",
              file=sys.stderr)
    lanes: dict[str, int] = {}
    for record in records:
        lanes[record["executor"]] = lanes.get(record["executor"], 0) + 1
    if args.json:
        for record in records:
            print(json.dumps(record, ensure_ascii=False))
    else:
        print(f"Wave {wave}: {len(records)} planned queries; " + ", ".join(f"{lane}={count}" for lane, count in sorted(lanes.items())))
    if not records:
        print(f"wave {wave} has no new work: close it to count it as dry", file=sys.stderr)
    if args.apply:
        with (root / PLAN_FILE).open("a", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        state["waves_planned"][str(wave)] = [record["query_id"] for record in records]
        write_json(root / WAVES_FILE, state)
        print(f"Appended wave {wave} to {PLAN_FILE}; per-executor queues: search_waves.py tasks DIR --wave {wave} --executor NAME",
              file=sys.stderr if args.json else sys.stdout)
    elif not args.json:
        print("Preview only; use --apply to write the wave")
    return 0


if __name__ == "__main__":
    sys.exit(main())
