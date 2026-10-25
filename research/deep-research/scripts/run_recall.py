#!/usr/bin/env python3
"""Measure search recall in one command and keep its history.

``score`` scores every research bundle linked in ``results.jsonl`` (see
``validate_recall.py``). ``search`` runs a live discovery search for cases that
carry ``search_setup``: the ``baseline`` planner executes the old en/ru query
matrix in plan order; the ``waves`` planner runs ``search_waves.py`` waves with
one executor per source class (in parallel), en/ru/zh queries, link following,
a refutation pass and the saturation stop. Search goes through the existing
TinyFish adapter in ``community_sources.py``; responses are cached so planners
are compared on identical results. ``--record`` appends the result to
``history.jsonl``; ``history`` prints the trend. ``check-gold`` re-opens every
gold URL and venue.

Live recall is discovery-level by design: a gold page counts when the search
surfaced it (``discovery_recall``) and, separately, when a wave opened it
(``recall``). Neither replaces a researched bundle's inspected recall.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import validate_recall
from plan_queries import DEFAULT_FAMILIES_BY_DEPTH, build_plan
from search_support import canonical_url, next_id
from search_waves import (
    DEFAULT_MAX_LINKS,
    WaveContext,
    close_wave,
    fill_entity_names,
    interleave,
    new_state,
    plan_wave,
)
from source_classes import SOURCE_CLASSES

SCRIPTS = Path(__file__).resolve().parent
RESEARCH = SCRIPTS.parents[1]
RECALL_DIR = RESEARCH / "evaluation/recall"
BUILD_DIR = RESEARCH.parent / "build/recall"
HISTORY_FILE = "history.jsonl"
RESULTS_PER_QUERY = 10
MIN_WAVE_ACTIONS = 16
OPEN_LANES = ("official", "statistics", "chinese", "podcast", "reddit", "youtube")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git_revision() -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=SCRIPTS, capture_output=True, text=True, check=False).stdout.strip()

    return {"commit": git("rev-parse", "--short", "HEAD") or None, "dirty": bool(git("status", "--porcelain", "--", str(SCRIPTS)))}


def append_history(directory: Path, entry: dict[str, Any]) -> None:
    with (directory / HISTORY_FILE).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def history_entry(*, label: str, mode: str, summary: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    cases = {
        case_id: {key: report[key] for key in ("recall", "discovery_recall", "gold_found", "gold_discovered", "gold_total", "queries_total")}
        | {key: report[key] for key in ("actions", "waves_closed", "stop_reason") if key in report}
        for case_id, report in summary["results"].items()
        if report.get("status") in {"pass", "fail"}
    }
    return {
        "recorded_at": utc_now(),
        "label": label,
        "mode": mode,
        "oracle_version": validate_recall.ORACLE_VERSION,
        "git": git_revision(),
        "cases_scored": len(cases),
        "recall": summary["recall"],
        "discovery_recall": summary["discovery_recall"],
        "by_class": summary["by_class"],
        "cases": cases,
        **(extra or {}),
    }


# --- live search -------------------------------------------------------------


class Searcher:
    """TinyFish search/fetch through the existing adapter, cached on disk."""

    def __init__(self, cache_dir: Path, *, offline: bool = False) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.calls = {"search": 0, "fetch": 0, "cache_hits": 0}

    def _cached(self, kind: str, key: dict[str, Any], produce: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        digest = hashlib.sha256(json.dumps([kind, key], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        path = self.cache_dir / f"{kind}-{digest}.json"
        if path.is_file():
            self.calls["cache_hits"] += 1
            return json.loads(path.read_text(encoding="utf-8"))
        if self.offline:
            raise RuntimeError(f"offline: no cached {kind} response")
        value = produce()
        self.calls[kind] += 1
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        return value

    @staticmethod
    def _with_rate_limit(bucket: str, units: int, limit: int, call: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        from community_sources import ProviderError, reserve_rate_capacity

        for _ in range(20):
            try:
                reserve_rate_capacity(bucket, units, limit)
                break
            except ProviderError as exc:
                if exc.status != 429:
                    raise
                time.sleep(min(float(exc.retry_after or 5), 30.0))
        else:
            raise RuntimeError(f"{bucket}: rate limit did not clear")
        return call()

    def search(self, query: str, include_domains: list[str]) -> list[dict[str, Any]]:
        from community_sources import TINYFISH_SEARCH_LIMIT, normalize_tinyfish_search, tinyfish_search

        domains = ",".join(include_domains) or None

        def produce() -> dict[str, Any]:
            payload = self._with_rate_limit(
                "tinyfish-search", 1, TINYFISH_SEARCH_LIMIT,
                lambda: tinyfish_search(query, 0, include_domains=domains),
            )
            return normalize_tinyfish_search(payload, query, 0, include_domains=domains)

        envelope = self._cached("search", {"query": query, "domains": domains}, produce)
        return [row for row in envelope["results"] if row.get("source_url")][:RESULTS_PER_QUERY]

    def fetch(self, url: str) -> dict[str, Any] | None:
        from community_sources import TINYFISH_FETCH_URL_LIMIT, normalize_tinyfish_fetch, tinyfish_fetch

        def produce() -> dict[str, Any]:
            payload = self._with_rate_limit(
                "tinyfish-fetch", 1, TINYFISH_FETCH_URL_LIMIT, lambda: tinyfish_fetch([url], links=True)
            )
            return normalize_tinyfish_fetch(payload, [url])

        envelope = self._cached("fetch", {"url": url}, produce)
        results = envelope["results"]
        return results[0] if results and results[0].get("content") else None


class LiveRun:
    """One case, one planner: ledgers in a scratch bundle scored like any bundle."""

    def __init__(self, case: dict[str, Any], planner: str, root: Path, searcher: Searcher, *,
                 budget: int, threshold: int, min_new: int, max_waves: int, max_opens: int,
                 names: Callable[[int], dict[str, Any]] | None) -> None:
        self.case, self.planner, self.root, self.searcher = case, planner, root, searcher
        self.budget, self.max_opens = budget, max_opens
        self.actions = 0
        self.queries: list[dict[str, Any]] = []
        self.candidates: list[dict[str, Any]] = []
        self.sources: list[dict[str, Any]] = []
        self.planned: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        setup = case["search_setup"]
        localization = {
            "topics": {"__all__": dict(setup["topic"])},
            "entities": [dict(entry, names=dict(entry.get("names", {}))) for entry in setup.get("entities", [])],
        }
        if names:
            fill_entity_names(localization, ["en", "ru", "zh"], names)
        languages = ["en", "ru"] if planner == "baseline" else ["en", "ru", "zh"]
        self.ctx = WaveContext(
            branches=[(None, case["title"])], languages=languages, localization=localization,
            markers=list(setup.get("version_markers", [])), year=case["as_of"][:4], coverage_enabled=False,
        )
        self.depth = setup.get("depth", "deep")
        self.state = new_state(threshold, min_new, max_waves, languages)

    def _search(self, record: dict[str, Any], query: str, domains: list[str]) -> None:
        stamp = utc_now()
        try:
            rows = self.searcher.search(query, domains)
            status = "completed" if rows else "no_results"
        except Exception as exc:  # noqa: BLE001 -- provider failures are recorded per query, not hidden
            rows, status = [], "failed"
            record["failure_reason"] = f"{type(exc).__name__}: {exc}"
        with self.lock:
            candidate_ids = []
            for rank, row in enumerate(rows, 1):
                candidate_id = f"CAN-{len(self.candidates) + 1:05d}"
                self.candidates.append({"candidate_id": candidate_id, "query_id": record["query_id"], "url": row["source_url"],
                                        "decision": "deferred", "rank": rank, "title": row.get("title")})
                candidate_ids.append(candidate_id)
            record.update({"executed_at": stamp, "status": status, "result_source_ids": [], "result_candidate_ids": candidate_ids})
            self.queries.append(record)

    def _open(self, url: str, record: dict[str, Any]) -> bool:
        """Open one page as a researcher would: snapshot, outbound links, source record."""
        page = self.searcher.fetch(url)
        if not page:
            return False
        source_id = next_id("SRC", {source["source_id"] for source in self.sources})
        snapshot = self.root / "snapshots" / f"{source_id}.txt"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(str(page["content"]), encoding="utf-8")
        final = page.get("source_url") or url
        self.sources.append({
            "source_id": source_id, "title": page.get("title") or final, "requested_url": url, "final_url": final,
            "canonical_url": canonical_url(final), "access_integrity": "full", "source_type": "other",
            "lineage_id": f"LIN-{hashlib.sha256(canonical_url(final).encode()).hexdigest()[:10]}",
            "snapshot_path": f"snapshots/{source_id}.txt", "outbound_links": page.get("links", [])[:300],
            "found_by_query_ids": [record["query_id"]],
        })
        record.setdefault("result_source_ids", []).append(source_id)
        return True

    def run_baseline(self) -> None:
        families = list(DEFAULT_FAMILIES_BY_DEPTH[self.depth]) + ["localized"]
        ids: set[str] = set()
        records: list[dict[str, Any]] = []
        for language in self.ctx.languages:
            batch = build_plan(branches=self.ctx.branches, families=families, languages=[language], entities=[],
                               markers=self.ctx.markers, year=self.ctx.year, existing_queries=[r["query"] for r in records],
                               existing_ids=ids, coverage_enabled=False, localization=self.ctx.for_language(language))
            ids.update(record["query_id"] for record in batch)
            records.extend(batch)
        for record in records[: self.budget]:
            self.actions += 1
            self._search(record, record["query"], [])

    def run_waves(self) -> None:
        wave = 0
        backlog: list[dict[str, Any]] = []
        max_waves = self.state["config"]["max_waves"]
        while self.actions < self.budget and not self.state["saturation"]["stop"]:
            wave += 1
            fresh = plan_wave(self.ctx, wave, root=self.root, queries=self.queries, sources=self.sources, claims=[],
                              planned=self.planned + backlog, candidates=self.candidates, max_links=DEFAULT_MAX_LINKS)
            # Spread the budget over the remaining waves so later waves can follow links;
            # queries that do not fit stay in the backlog for the next wave.
            remaining = self.budget - self.actions
            cap = remaining if wave >= max_waves else max(MIN_WAVE_ACTIONS, -(-remaining // (max_waves - wave + 1)))
            queue = interleave([dict(record, wave=wave) for record in fresh + backlog])
            records, backlog = queue[: min(cap, remaining)], queue[min(cap, remaining):]
            self.planned.extend(records)
            self.state["waves_planned"][str(wave)] = [record["query_id"] for record in records]
            follows = [record for record in records if record.get("query_kind") == "follow_link"]
            searches = [record for record in records if record.get("query_kind") != "follow_link"]
            self.actions += len(records)
            lanes: dict[str, list[dict[str, Any]]] = {}
            for record in searches:
                lanes.setdefault(record["executor"], []).append(record)

            def run_lane(items: list[dict[str, Any]]) -> None:
                for item in items:
                    self._search(item, item["executor_query"], item["include_domains"])

            # One executor per source class, as the per-platform subagents would run.
            with ThreadPoolExecutor(max_workers=max(1, len(lanes))) as pool:
                list(pool.map(run_lane, lanes.values()))
            for record in follows:
                record.update({"executed_at": utc_now(), "result_source_ids": [], "result_candidate_ids": []})
                record["status"] = "completed" if self._open(record["follow_url"], record) else "failed"
                if record["status"] == "completed":
                    self.candidates.append({"candidate_id": f"CAN-{len(self.candidates) + 1:05d}", "query_id": record["query_id"],
                                            "url": record["follow_url"], "decision": "opened", "rank": 1})
                self.queries.append(record)
            self._open_top(wave)
            close_wave(self.state, wave, queries=self.queries, sources=self.sources + self._pseudo_sources(),
                       claims=[], evidence=[], novelty=lambda source: True)

    def _open_top(self, wave: int) -> None:
        """Open the best new candidate of each non-web lane so the next wave can follow links."""
        opened = {canonical_url(source["final_url"]) for source in self.sources}
        by_query = {record["query_id"]: record for record in self.queries if record.get("wave") == wave}
        for lane in OPEN_LANES:
            if self.actions >= self.budget:
                return
            picks = [
                candidate for candidate in self.candidates
                if by_query.get(candidate["query_id"], {}).get("executor") == lane and candidate["decision"] == "deferred"
                and canonical_url(candidate["url"]) not in opened
            ][: self.max_opens]
            for candidate in picks:
                if self.actions >= self.budget:
                    return
                self.actions += 1
                if self._open(candidate["url"], by_query[candidate["query_id"]]):
                    candidate["decision"] = "opened"
                    opened.add(canonical_url(candidate["url"]))

    def _pseudo_sources(self) -> list[dict[str, Any]]:
        """Discovery novelty: every surfaced URL is a candidate source for saturation."""
        records = []
        for candidate in self.candidates:
            records.append({"source_id": f"PSEUDO-{candidate['candidate_id']}", "final_url": candidate["url"],
                            "lineage_id": canonical_url(candidate["url"]), "found_by_query_ids": [candidate["query_id"]]})
        return records

    def write(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for name, records in (("queries.jsonl", self.queries), ("candidates.jsonl", self.candidates),
                              ("sources.jsonl", self.sources), ("query-plan.jsonl", self.planned)):
            (self.root / name).write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")
        (self.root / "search-waves.json").write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")


def live_search(args: argparse.Namespace, cases: list[dict[str, Any]]) -> int:
    selected = [case for case in cases if "search_setup" in case and (not args.case or case["case_id"] in args.case)]
    missing = sorted(set(args.case) - {case["case_id"] for case in selected})
    if missing:
        print(f"error: no search_setup for {', '.join(missing)}", file=sys.stderr)
        return 2
    planners = ["baseline", "waves"] if args.planner == "both" else [args.planner]
    out = Path(args.out).expanduser().resolve() if args.out else BUILD_DIR
    searcher = Searcher(out / "cache", offline=args.offline)
    names = None
    if not args.offline:
        from hearthstone_names import HearthstoneJsonNames, KolodaNameResolver, search_names

        koloda, hsjson = KolodaNameResolver(), HearthstoneJsonNames()

        def names(dbf: int) -> dict[str, Any]:
            return search_names(dbf, koloda=koloda, hsjson=hsjson)

    label = args.label or utc_now()
    failed_queries = 0
    for planner in planners:
        results: dict[str, Any] = {}
        for case in selected:
            root = out / label.replace(" ", "_") / planner / case["case_id"]
            run = LiveRun(case, planner, root, searcher, budget=args.budget, threshold=args.threshold,
                          min_new=args.min_new, max_waves=args.max_waves, max_opens=args.max_opens, names=names)
            (run.run_baseline if planner == "baseline" else run.run_waves)()
            run.write()
            report = validate_recall.score_bundle(case, root)
            failed_queries += sum(1 for record in run.queries if record.get("status") == "failed")
            report.update({"actions": run.actions, "waves_closed": len(run.state["waves"]),
                           "stop_reason": run.state["saturation"]["reason"] if planner == "waves" else "budget"})
            results[case["case_id"]] = report
            print(f"- {planner} {case['case_id']}: discovery {report['discovery_recall']} "
                  f"({report['gold_discovered']}/{report['gold_total']}), opened {report['recall']}, "
                  f"{run.actions} actions" + (f", {report['stop_reason']}" if planner == "waves" else ""))
        summary = summarize(results, len(selected))
        print(f"{planner}: discovery recall {summary['discovery_recall']}, opened recall {summary['recall']}; "
              f"by class: {validate_recall.format_classes(summary['by_class'])}")
        if args.record:
            append_history(Path(args.directory), history_entry(
                label=label, mode="live-search", summary=summary,
                extra={"planner": planner, "budget": args.budget, "provider": "tinyfish",
                       "saturation": {"threshold_waves": args.threshold, "min_new_sources": args.min_new}},
            ))
    print(f"provider calls: {searcher.calls}; failed queries: {failed_queries}")
    return 0


def summarize(results: dict[str, Any], count: int) -> dict[str, Any]:
    reports = list(results.values())
    total = sum(item["gold_total"] for item in reports)
    return {
        "cases": count,
        "results": results,
        "recall": round(sum(item["gold_found"] for item in reports) / total, 3) if total else None,
        "discovery_recall": round(sum(item["gold_discovered"] for item in reports) / total, 3) if total else None,
        "by_class": validate_recall.aggregate_by_class(reports),
    }


# --- gold checks ------------------------------------------------------------


def check_url(url: str, searcher: Searcher | None) -> tuple[str, str]:
    """(route, outcome). Direct GET first; TinyFish for bot-protected venues."""
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) ResearchTeam recall check"})
    try:
        with urlopen(request, timeout=45) as response:
            if response.status == 200:
                return "direct", "ok"
    except HTTPError as exc:
        if exc.code == 404:
            return "direct", "not_found"
    except (URLError, TimeoutError, OSError):
        pass
    if searcher is None:
        return "direct", "blocked"
    try:
        page = searcher.fetch(url)
    except Exception as exc:  # noqa: BLE001 -- reported per URL
        return "tinyfish", f"error: {type(exc).__name__}"
    return "tinyfish", "ok" if page else "empty"


def check_gold(args: argparse.Namespace, cases: list[dict[str, Any]]) -> int:
    out = Path(args.out).expanduser().resolve() if args.out else BUILD_DIR
    searcher = None if args.direct_only else Searcher(out / "gold-cache", offline=False)
    failures = 0
    for case in cases:
        if args.case and case["case_id"] not in args.case:
            continue
        for item in case["gold_sources"]:
            target = item.get("probe_url") or validate_recall.gold_target(item)
            route, outcome = check_url(target, searcher)
            failures += outcome != "ok"
            print(f"{case['case_id']} {item['source_class']:<10} {outcome:<10} {route:<8} {target}")
    print(f"gold check: {failures} not reachable")
    return int(bool(failures))


def show_history(directory: Path, last: int) -> int:
    entries = validate_recall.load_jsonl(directory / HISTORY_FILE)
    if not entries:
        print("no recall history yet")
        return 0
    previous: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries[-last:]:
        key = (entry["mode"], entry.get("planner", ""))
        before = previous.get(key)
        delta = ""
        if before and before.get("discovery_recall") is not None and entry.get("discovery_recall") is not None:
            delta = f" ({entry['discovery_recall'] - before['discovery_recall']:+.3f} vs previous)"
        classes = ", ".join(f"{lane} {bucket['discovery_recall']}" for lane, bucket in entry["by_class"].items())
        print(f"{entry['recorded_at']} {entry['label']} [{entry['mode']}{'/' + entry['planner'] if entry.get('planner') else ''}] "
              f"cases={entry['cases_scored']} recall={entry['recall']} discovery={entry['discovery_recall']}{delta}; {classes}")
        previous[key] = entry
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--directory", default=str(RECALL_DIR), help="Recall benchmark directory")
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser("score", help="Score linked bundles with per-class breakdown")
    score.add_argument("--record", metavar="LABEL", help="Append the result to history.jsonl")
    score.add_argument("--json", action="store_true")
    search = sub.add_parser("search", help="Live discovery search for cases with search_setup")
    search.add_argument("--case", action="append", default=[])
    search.add_argument("--planner", choices=("baseline", "waves", "both"), default="both")
    search.add_argument("--budget", type=int, default=60, help="Search queries plus page opens per case")
    search.add_argument("--threshold", type=int, default=2)
    search.add_argument("--min-new", type=int, default=5, help="New surfaced URLs a wave needs to not be dry")
    search.add_argument("--max-waves", type=int, default=4)
    search.add_argument("--max-opens", type=int, default=1, help="Pages opened per lane per wave for link following")
    search.add_argument("--label")
    search.add_argument("--record", action="store_true")
    search.add_argument("--offline", action="store_true", help="Use cached provider responses only")
    search.add_argument("--out", help=f"Scratch directory; default {BUILD_DIR}")
    gold = sub.add_parser("check-gold", help="Re-open every gold URL and venue")
    gold.add_argument("--case", action="append", default=[])
    gold.add_argument("--direct-only", action="store_true")
    gold.add_argument("--out")
    history = sub.add_parser("history", help="Show recorded recall over time")
    history.add_argument("--last", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    directory = Path(args.directory).expanduser().resolve()
    if args.command == "history":
        return show_history(directory, args.last)
    try:
        cases, results, errors = validate_recall.load_benchmark(directory)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("Recall benchmark: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    if args.command == "check-gold":
        return check_gold(args, cases)
    if args.command == "search":
        return live_search(args, cases)
    summary = validate_recall.score_all(directory, cases, results)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"Recall: {summary['scored']}/{summary['cases']} cases scored, recall {summary['recall']}, "
              f"discovery {summary['discovery_recall']}")
        for lane in SOURCE_CLASSES:
            bucket = summary["by_class"].get(lane)
            if bucket:
                print(f"- {lane}: {bucket['found']}/{bucket['gold']} found, {bucket['discovered']}/{bucket['gold']} surfaced")
        for case_id in summary["not_run"]:
            print(f"- not_run: {case_id}")
    if args.record:
        if not summary["scored"]:
            print("nothing scored; history not recorded", file=sys.stderr)
            return 1
        append_history(directory, history_entry(label=args.record, mode="bundle", summary=summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
