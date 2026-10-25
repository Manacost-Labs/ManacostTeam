#!/usr/bin/env python3
"""Search waves, saturation, coverage map, recall harness and localized names."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
WAVES = SCRIPTS / "search_waves.py"
INIT = SCRIPTS / "init_research_run.py"
sys.path.insert(0, str(SCRIPTS))

import community_sources  # noqa: E402
import fetch_source  # noqa: E402
import hearthstone_names  # noqa: E402
import platform_coverage  # noqa: E402
import run_recall  # noqa: E402
import search_waves  # noqa: E402
import validate_recall  # noqa: E402
from source_classes import query_lane, source_class  # noqa: E402

LOCALIZATION = {
    "topics": {"__all__": {"en": "Battlegrounds Aberrations", "ru": "Поля сражений Аберрации", "zh": "酒馆战棋 畸变体"}},
    "entities": [{"entity_id": "hero", "names": {"en": "Drest'agath", "ru": "Дрестагат", "zh": "德雷阿佳丝"}},
                 {"entity_id": "card", "names": {"en": "Windpeak Wyrm"}}],
}


def run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(script), *args], check=False, capture_output=True, text=True)


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def context(languages: list[str] | None = None) -> search_waves.WaveContext:
    return search_waves.WaveContext(branches=[(None, "Aberrations")], languages=languages or ["en", "ru", "zh"],
                                    localization=json.loads(json.dumps(LOCALIZATION)), markers=["36.6.3"],
                                    year="2026", coverage_enabled=False)


def executed(record: dict[str, Any], sources: list[str], status: str = "completed") -> dict[str, Any]:
    return {**record, "executed_at": "2026-10-01T10:00:00Z", "status": status, "result_source_ids": sources}


def inspected(source_id: str, url: str, **extra: Any) -> dict[str, Any]:
    return {"source_id": source_id, "final_url": url, "access_integrity": "full", "lineage_id": f"LIN-{source_id}", **extra}


class SourceClassTest(unittest.TestCase):
    def test_lanes_follow_registry_platforms_and_overrides(self) -> None:
        expected = {
            "https://hearthstone.blizzard.com/en-us/news/24301454": "official",
            "https://hs.blizzard.cn/news/24301454/": "chinese",
            "https://www.bilibili.com/video/BV1": "chinese",
            "https://www.vicioussyndicate.com/vs-data-reaper-report-359/": "statistics",
            "https://www.vicioussyndicate.com/vs-data-reaper-podcast-episode-213/": "podcast",
            "https://coinconcede.com/568": "podcast",
            "https://x.com/PlayHearthstone/status/1": "x",
            "https://old.reddit.com/r/hearthstone/": "reddit",
            "https://youtu.be/abc": "youtube",
            "https://liquipedia.net/hearthstone/x": "web",
        }
        for url, lane in expected.items():
            self.assertEqual(source_class(url), lane, url)
        self.assertEqual(query_lane({"family": "primary", "language": "en"}), "official")
        self.assertEqual(query_lane({"family": "general", "language": "zh"}), "chinese")
        self.assertEqual(query_lane({"family": "general", "executor": "podcast"}), "podcast")


class SearchWavesTest(unittest.TestCase):
    def test_seed_wave_covers_every_lane_and_language_with_localized_names(self) -> None:
        records = search_waves.plan_wave(context(), 1, root=None, queries=[], sources=[], claims=[], planned=[], candidates=[])
        lanes = {record["executor"] for record in records}
        self.assertTrue({"official", "statistics", "reddit", "x", "youtube", "chinese", "podcast", "web"} <= lanes)
        self.assertEqual({record["language"] for record in records}, {"en", "ru", "zh"})
        queries = " ".join(record["query"] for record in records)
        self.assertIn("德雷阿佳丝", queries)
        self.assertIn("Дрестагат", queries)
        self.assertNotIn("Windpeak Wyrm 酒馆战棋", queries, "an entity without a zh name is skipped, not translated")
        nga = next(record for record in records if record["query"].startswith("site:nga.cn"))
        self.assertEqual(nga["include_domains"], ["nga.cn"])
        self.assertNotIn("site:", nga["executor_query"])
        # Round-robin: the first eight records already span several lanes.
        self.assertEqual(len({record["executor"] for record in records[2:10]}), 8)

    def test_later_wave_follows_links_refutes_claims_and_fills_gap_lanes(self) -> None:
        ctx = context(["en", "zh"])
        seed = search_waves.plan_wave(ctx, 1, root=None, queries=[], sources=[], claims=[], planned=[], candidates=[])
        official = next(record for record in seed if record["executor"] == "official")
        reddit = next(record for record in seed if record["executor"] == "reddit")
        queries = [executed(official, ["SRC-0001"]), executed(reddit, [], status="no_results")]
        sources = [inspected("SRC-0001", "https://hearthstone.blizzard.com/en-us/news/24302091", outbound_links=[
            "https://us.forums.blizzard.com/en/hearthstone/t/aberrations/1",
            "https://hearthstone.blizzard.com/en-us/news/24303864",
            "https://unrelated.example/page",
            "https://hearthstone.blizzard.com/static/logo.png",
        ])]
        claims = [{"claim_id": "CLM-0001", "importance": "critical", "status": "supported", "challenging_evidence_ids": [],
                   "claim": "Deities need four deaths", "search_phrases": {"en": "Deity four deaths", "zh": "神祇 四次死亡"}},
                  {"claim_id": "CLM-0002", "importance": "material", "status": "supported",
                   "challenge_search": {"query_ids": ["QRY-0001"], "result": "none_found"}}]
        records = search_waves.plan_wave(ctx, 2, root=None, queries=queries, sources=sources, claims=claims,
                                         planned=seed, candidates=[])
        follows = [record for record in records if record.get("query_kind") == "follow_link"]
        self.assertEqual({record["follow_url"] for record in follows}, {
            "https://us.forums.blizzard.com/en/hearthstone/t/aberrations/1",
            "https://hearthstone.blizzard.com/en-us/news/24303864",
        })
        self.assertTrue(all(record["origin_source_ids"] == ["SRC-0001"] and record["wave"] == 2 for record in follows))
        refutations = [record for record in records if record["pass"] == "contradiction"]
        self.assertTrue(refutations)
        self.assertTrue(all(record["challenge_claim_ids"] == ["CLM-0001"] for record in refutations))
        targeted = [record for record in refutations if "Deity four deaths" in record["query"] or "神祇" in record["query"]]
        self.assertTrue({"web", "reddit", "chinese"} <= {record["executor"] for record in targeted})
        gaps = {record["executor"] for record in records if record.get("queue_reason")}
        self.assertIn("reddit", gaps, "a searched lane with no inspected source gets gap queries")
        self.assertNotIn("official", gaps)

    def test_saturation_needs_consecutive_dry_waves_at_the_configured_threshold(self) -> None:
        state = search_waves.new_state(2, 1, 6, ["en"])
        sources = [inspected("SRC-0001", "https://hearthstone.blizzard.com/en-us/news/1")]
        waves = []
        for wave, found in ((1, ["SRC-0001"]), (2, ["SRC-0001"]), (3, [])):
            record = {"query_id": f"QRY-{wave:04d}", "family": "primary", "wave": wave, "query": f"q{wave}"}
            state["waves_planned"][str(wave)] = [record["query_id"]]
            waves.append(executed(record, found))
            search_waves.close_wave(state, wave, queries=waves, sources=sources, claims=[], evidence=[])
        self.assertEqual([item["new_source_ids"] for item in state["waves"]], [["SRC-0001"], [], []])
        self.assertEqual([item["dry"] for item in state["waves"]], [False, True, True])
        self.assertTrue(state["saturation"]["saturated"])
        self.assertEqual(search_waves.validate_state(state), [])
        state["waves"][1]["dry"] = False
        self.assertIn("dry flag disagrees", " ".join(search_waves.validate_state(state)))

    def test_pending_queries_and_new_claims_keep_a_wave_wet(self) -> None:
        state = search_waves.new_state(1, 1, 6, ["en"])
        state["waves_planned"]["1"] = ["QRY-0001", "QRY-0002"]
        queries = [executed({"query_id": "QRY-0001", "family": "primary", "wave": 1, "query": "q"}, [])]
        record = search_waves.close_wave(state, 1, queries=queries, sources=[], claims=[], evidence=[])
        self.assertEqual(record["pending_query_ids"], ["QRY-0002"])
        self.assertFalse(record["dry"])
        state = search_waves.new_state(1, 1, 6, ["en"])
        state["waves_planned"]["1"] = ["QRY-0001"]
        sources = [{"source_id": "SRC-0001", "final_url": "https://a.example/x", "access_integrity": "snippet", "lineage_id": "L"}]
        queries = [executed({"query_id": "QRY-0001", "family": "general", "wave": 1, "query": "q"}, ["SRC-0001"])]
        claims = [{"claim_id": "CLM-0001", "supporting_evidence_ids": ["EVD-0001"]}]
        evidence = [{"evidence_id": "EVD-0001", "source_id": "SRC-0001"}]
        record = search_waves.close_wave(state, 1, queries=queries, sources=sources, claims=claims, evidence=evidence)
        self.assertEqual(record["new_source_ids"], [], "a snippet is not an inspected source")
        self.assertEqual(record["new_claim_ids"], ["CLM-0001"])
        self.assertFalse(record["dry"])

    def test_cli_records_threshold_plans_closes_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp) / "run"
            result = run(INIT, str(bundle), "--question", "Aberrations", "--domain", "hearthstone")
            self.assertEqual(result.returncode, 0, result.stderr)
            (bundle / "plan.json").write_text(json.dumps({"query_localization": LOCALIZATION}), encoding="utf-8")
            planned = run(WAVES, "plan", str(bundle), "--threshold", "1", "--min-new", "1", "--apply")
            self.assertEqual(planned.returncode, 0, planned.stderr)
            state = json.loads((bundle / "search-waves.json").read_text(encoding="utf-8"))
            self.assertEqual(state["config"]["threshold_waves"], 1)
            again = run(WAVES, "plan", str(bundle), "--apply")
            self.assertEqual(again.returncode, 2)
            self.assertIn("already planned", again.stderr)
            tasks = run(WAVES, "tasks", str(bundle), "--wave", "1", "--executor", "chinese")
            chinese = [json.loads(line) for line in tasks.stdout.splitlines()]
            self.assertTrue(chinese and all(record["language"] == "zh" for record in chinese))
            write_jsonl(bundle / "queries.jsonl", [executed(record, []) for record in read_jsonl(bundle / "query-plan.jsonl")])
            closed = run(WAVES, "close", str(bundle), "--wave", "1")
            self.assertEqual(closed.returncode, 0, closed.stderr)
            self.assertIn("next: stop", closed.stdout)
            self.assertIn("search stopped", run(WAVES, "plan", str(bundle), "--apply").stderr)
            validation = run(SCRIPTS / "validate_research_run.py", str(bundle))
            self.assertNotIn("search-waves.json", validation.stdout)

    def test_entity_names_are_filled_from_dbf_without_overwriting(self) -> None:
        localization = {"entities": [{"entity_id": "wyrm", "dbf": 117714, "names": {"en": "Windpeak Wyrm"}}]}
        changed = search_waves.fill_entity_names(localization, ["en", "ru", "zh"], lambda dbf: {
            "names": {"en": "Other", "ru": "Ветровой змей", "zh": "乘风浮龙"},
            "name_sources": {"en": "e", "ru": "koloda", "zh": "hsjson"},
        })
        self.assertEqual(changed, ["wyrm:ru", "wyrm:zh"])
        self.assertEqual(localization["entities"][0]["names"]["en"], "Windpeak Wyrm")
        self.assertEqual(localization["entities"][0]["name_sources"], {"ru": "koloda", "zh": "hsjson"})


class CoverageMapTest(unittest.TestCase):
    def test_map_statuses_reasons_and_staleness(self) -> None:
        queries = [
            executed({"query_id": "QRY-0001", "family": "primary", "query": "a"}, ["SRC-0001"]),
            executed({"query_id": "QRY-0002", "family": "reddit", "query": "b"}, [], status="no_results"),
            {**executed({"query_id": "QRY-0003", "family": "general", "language": "zh", "query": "c"}, [], status="blocked"),
             "failure_reason": "nga.cn requires login"},
        ]
        sources = [inspected("SRC-0001", "https://hearthstone.blizzard.com/en-us/news/1")]
        document = platform_coverage.build_map(queries, sources)
        lanes = document["lanes"]
        self.assertEqual(lanes["official"]["status"], "found")
        self.assertEqual(lanes["reddit"]["status"], "searched_not_found")
        self.assertEqual(lanes["chinese"]["status"], "unavailable")
        self.assertEqual(lanes["chinese"]["reason"], "nga.cn requires login")
        self.assertEqual(lanes["podcast"]["status"], "not_searched")
        problems = platform_coverage.check_map(document, queries, sources)
        self.assertTrue(any("podcast is not_searched without a reason" in item for item in problems))
        reasoned = platform_coverage.build_map(queries, sources, document, {lane: "out of scope" for lane in ("statistics", "x", "youtube", "podcast", "web")})
        self.assertEqual(platform_coverage.check_map(reasoned, queries, sources), [])
        kept = platform_coverage.build_map(queries, sources, reasoned)
        self.assertEqual(kept["lanes"]["podcast"]["reason"], "out of scope", "an unchanged status keeps its reason")
        more = sources + [inspected("SRC-0002", "https://coinconcede.com/568")]
        self.assertTrue(any("lane podcast disagrees" in item for item in platform_coverage.check_map(reasoned, queries, more)))
        self.assertEqual(platform_coverage.build_map(queries, more, reasoned)["lanes"]["podcast"]["reason"], None)


class RecallScoringTest(unittest.TestCase):
    CASE = {
        "case_id": "RECALL-900", "oracle_version": "1.1", "case_type": "patch", "title": "t", "domain": "hearthstone",
        "mode": "constructed", "as_of": "2026-10-25", "prompt": "p",
        "gold_sources": [
            {"match": "url", "url": "https://hearthstone.blizzard.com/en-us/news/24301454", "source_class": "official", "why": "notes",
             "verified_at": "2026-10-25", "verified_via": "direct"},
            {"match": "url", "url": "https://hs.blizzard.cn/news/24301454/", "source_class": "chinese", "why": "cn",
             "verified_at": "2026-10-25", "verified_via": "direct"},
            {"match": "host_prefix", "host": "www.reddit.com", "path_prefix": "/r/CompetitiveHS", "source_class": "reddit", "why": "r",
             "probe_url": "https://www.reddit.com/r/CompetitiveHS/", "verified_at": "2026-10-25", "verified_via": "direct"},
        ],
    }

    def test_oracle_1_1_requires_verification_and_valid_probe(self) -> None:
        self.assertEqual(validate_recall.validate_cases([self.CASE]), [])
        broken = json.loads(json.dumps(self.CASE))
        del broken["gold_sources"][0]["verified_via"]
        broken["gold_sources"][1]["source_class"] = "community"
        broken["gold_sources"][2]["probe_url"] = "https://www.reddit.com/r/hearthstone/"
        errors = " ".join(validate_recall.validate_cases([broken]))
        self.assertIn("verified_via", errors)
        self.assertIn("source_class must be one of", errors)
        self.assertIn("probe_url must be a page inside", errors)

    def test_article_mirrors_match_but_regions_stay_distinct(self) -> None:
        gold = self.CASE["gold_sources"]
        self.assertTrue(validate_recall.gold_matches(gold[0], "https://playhearthstone.com/en-us/blog/24301454/"))
        self.assertTrue(validate_recall.gold_matches(gold[0], "https://news.blizzard.com/en-us/article/24301454/37-0-patch-notes"))
        self.assertFalse(validate_recall.gold_matches(gold[0], "https://hs.blizzard.cn/news/24301454/index.html"))
        self.assertTrue(validate_recall.gold_matches(gold[1], "https://hs.blizzard.cn/news/24301454/index.html"))

    def test_breakdown_separates_opened_and_surfaced_gold(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp)
            write_jsonl(bundle / "sources.jsonl", [inspected("SRC-0001", "https://playhearthstone.com/en-us/blog/24301454/")])
            write_jsonl(bundle / "queries.jsonl", [])
            write_jsonl(bundle / "candidates.jsonl", [{"candidate_id": "CAN-1", "query_id": "Q", "url": "https://www.reddit.com/r/CompetitiveHS/comments/x/"}])
            report = validate_recall.score_bundle(self.CASE, bundle)
        self.assertEqual((report["gold_found"], report["gold_discovered"]), (1, 2))
        self.assertEqual(report["by_class"]["official"]["recall"], 1.0)
        self.assertEqual(report["by_class"]["reddit"], {"gold": 1, "found": 0, "discovered": 1, "recall": 0.0, "discovery_recall": 1.0})
        self.assertEqual(report["by_class"]["chinese"]["discovery_recall"], 0.0)


class FakeSearcher:
    """Deterministic index: a lane's domains decide what a query can surface."""

    INDEX = {
        "hearthstone.blizzard.com": "https://hearthstone.blizzard.com/en-us/news/24303864",
        "reddit.com": "https://www.reddit.com/r/BobsTavern/comments/abc/plan/",
        "hs.blizzard.cn": "https://hs.blizzard.cn/news/24303864/",
    }

    def __init__(self) -> None:
        self.calls = {"search": 0, "fetch": 0, "cache_hits": 0}

    def search(self, query: str, include_domains: list[str]) -> list[dict[str, Any]]:
        self.calls["search"] += 1
        rows = [{"source_url": url} for domain, url in self.INDEX.items() if domain in include_domains]
        return rows or [{"source_url": f"https://web.example/{abs(hash(query)) % 1000}"}]

    def fetch(self, url: str) -> dict[str, Any] | None:
        self.calls["fetch"] += 1
        links = ["https://us.forums.blizzard.com/en/hearthstone/t/hotfix/9"] if "blizzard.com" in url else []
        return {"source_url": url, "title": "page", "content": "text", "links": links}


class LiveRecallTest(unittest.TestCase):
    CASE = {
        "case_id": "RECALL-901", "title": "Aberrations", "as_of": "2026-10-05",
        "search_setup": {"topic": LOCALIZATION["topics"]["__all__"], "version_markers": ["36.6.3"], "entities": [], "depth": "deep"},
        "gold_sources": [
            {"match": "url", "url": "https://hearthstone.blizzard.com/en-us/news/24303864", "source_class": "official", "why": "o"},
            {"match": "url", "url": "https://hs.blizzard.cn/news/24303864/", "source_class": "chinese", "why": "c"},
            {"match": "url", "url": "https://us.forums.blizzard.com/en/hearthstone/t/hotfix/9", "source_class": "official", "why": "f"},
        ],
    }

    def run_planner(self, planner: str, root: Path) -> tuple[run_recall.LiveRun, dict[str, Any]]:
        live = run_recall.LiveRun(self.CASE, planner, root, FakeSearcher(), budget=80, threshold=1, min_new=1,
                                  max_waves=3, max_opens=1, names=None)
        (live.run_baseline if planner == "baseline" else live.run_waves)()
        live.write()
        return live, validate_recall.score_bundle(self.CASE, root)

    def test_waves_reach_lanes_and_linked_pages_the_baseline_misses(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            _, baseline = self.run_planner("baseline", Path(temp) / "baseline")
            live, waves = self.run_planner("waves", Path(temp) / "waves")
            self.assertEqual(baseline["gold_discovered"], 0)
            self.assertEqual(waves["gold_discovered"], 3, waves["misses"])
            self.assertGreaterEqual(len(live.state["waves"]), 2)
            self.assertEqual(search_waves.validate_state(live.state), [])
            self.assertLessEqual(live.actions, 80)

    def test_history_records_by_class_and_shows_delta(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for value in (0.25, 0.5):
                summary = {"results": {"RECALL-901": {"status": "fail", "recall": value, "discovery_recall": value, "gold_found": 1,
                                                       "gold_discovered": 1, "gold_total": 4, "queries_total": 3}},
                           "recall": value, "discovery_recall": value, "by_class": {"official": {"discovery_recall": value}}}
                run_recall.append_history(directory, run_recall.history_entry(label=f"r{value}", mode="live-search", summary=summary,
                                                                              extra={"planner": "waves"}))
            entries = read_jsonl(directory / run_recall.HISTORY_FILE)
            self.assertEqual([entry["label"] for entry in entries], ["r0.25", "r0.5"])
            self.assertIn("commit", entries[0]["git"])
            from contextlib import redirect_stdout
            from io import StringIO

            buffer = StringIO()
            with redirect_stdout(buffer):
                run_recall.show_history(directory, 10)
            self.assertIn("+0.250 vs previous", buffer.getvalue())


class NamesAndAdaptersTest(unittest.TestCase):
    def test_hearthstonejson_supplies_chinese_and_koloda_keeps_russian(self) -> None:
        cards = {"enUS": [{"dbfId": 69550, "name": "Innervate"}], "zhCN": [{"dbfId": 69550, "name": "激活"}]}

        def transport(request: Any, timeout: float) -> tuple[int, dict[str, str], bytes]:
            locale = request.full_url.split("/")[-2]
            return 200, {}, json.dumps(cards[locale]).encode("utf-8")

        class Koloda:
            def resolve(self, dbf: int, kind: str = "auto") -> dict[str, Any]:
                return {"name_ru": "Озарение", "name_en": None, "source_url": "https://api.kolodahearthstone.com/x"}

        with tempfile.TemporaryDirectory() as temp:
            hsjson = hearthstone_names.HearthstoneJsonNames(Path(temp), transport=transport)
            result = hearthstone_names.search_names(69550, koloda=Koloda(), hsjson=hsjson)
            self.assertEqual(result["names"], {"ru": "Озарение", "en": "Innervate", "zh": "激活"})
            self.assertEqual(result["missing_languages"], [])
            self.assertTrue((Path(temp) / "zhCN.json").is_file())
            self.assertEqual(hsjson.find_dbf("innervate"), [69550])

    def test_fetch_source_keeps_outbound_links(self) -> None:
        html = '<a href="/en-us/news/2#top">x</a><a href="https://x.com/a">y</a><a href="mailto:a@b">z</a><a href="#self">s</a>'
        self.assertEqual(fetch_source.extract_links(html, "https://hearthstone.blizzard.com/en-us/news/1"),
                         ["https://hearthstone.blizzard.com/en-us/news/2", "https://x.com/a"])

    def test_tinyfish_cli_update_notice_does_not_break_parsing(self) -> None:
        from unittest.mock import patch

        completed = subprocess.CompletedProcess([], 0, stdout='{"results": []}\n{"notice": "update"}\n', stderr="")
        with patch.object(community_sources.shutil, "which", return_value="/bin/tinyfish"), \
                patch.object(community_sources.subprocess, "run", return_value=completed):
            self.assertEqual(community_sources.run_tinyfish(["search"], "search"), {"results": []})


if __name__ == "__main__":
    unittest.main()
