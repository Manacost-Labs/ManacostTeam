#!/usr/bin/env python3
"""Tests for search planning, search coverage, source fetching, and the shared taxonomy."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from urllib.request import Request


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
INIT = SCRIPTS / "init_research_run.py"
PLAN = SCRIPTS / "plan_queries.py"
COVERAGE = SCRIPTS / "search_coverage.py"
FETCH = SCRIPTS / "fetch_source.py"
VALIDATE = SCRIPTS / "validate_research_run.py"
FINGERPRINT = SCRIPTS / "fingerprint_research_sources.py"
MIGRATE = SCRIPTS / "migrate_research_bundle.py"
sys.path.insert(0, str(SCRIPTS))

import fetch_source  # noqa: E402
import search_coverage  # noqa: E402
from search_support import (  # noqa: E402
    QUERY_FAMILIES,
    canonical_url,
    lineage_hint,
    next_id,
    normalize_query,
)


def run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args], check=False, capture_output=True, text=True
    )


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        encoding="utf-8",
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def init_bundle(target: Path, *, profile: str = "research-report", depth: str = "deep") -> None:
    result = run(
        INIT,
        str(target),
        "--question",
        "How should the first Dark Gift be used in Battlegrounds?",
        "--depth",
        depth,
        "--domain",
        "hearthstone",
        "--output-profile",
        profile,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def executed_query(query_id: str, family: str, query: str, sources: list[str]) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "pass": "discovery",
        "family": family,
        "language": "en",
        "query": query,
        "executed_at": "2026-09-01T10:00:00Z",
        "status": "completed",
        "result_source_ids": sources,
    }


def source(
    source_id: str, url: str, lineage: str, *, verified: bool = False, run_dir: Path | None = None
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "source_id": source_id,
        "title": f"Source {source_id}",
        "requested_url": url,
        "final_url": url,
        "accessed_at": "2026-09-01T10:05:00Z",
        "access_integrity": "full",
        "source_type": "official",
        "lineage_id": lineage,
        "mutable": True,
        "fingerprint_status": "verified" if verified else "unavailable",
    }
    if verified:
        assert run_dir is not None
        (run_dir / "snapshots").mkdir(exist_ok=True)
        payload = f"Source: {source_id}\nURL: {url}\n\nfixture text\n".encode("utf-8")
        (run_dir / "snapshots" / f"{source_id}.txt").write_bytes(payload)
        record["snapshot_path"] = f"snapshots/{source_id}.txt"
        record["content_sha256"] = hashlib.sha256(payload).hexdigest()
        record["content_bytes"] = len(payload)
        record["fingerprinted_at"] = "2026-09-01T10:06:00Z"
    else:
        record["fingerprint_reason"] = "test fixture"
    return record


class SearchSupportTest(unittest.TestCase):
    def test_canonical_url_strips_tracking_fragment_and_mobile_prefix(self) -> None:
        self.assertEqual(
            canonical_url("HTTPS://m.Example.com:443/path/?utm_source=x&b=2&a=1#frag"),
            "https://example.com/path?a=1&b=2",
        )
        self.assertEqual(
            canonical_url("https://www.reddit.com/r/hearthstone/"),
            "https://reddit.com/r/hearthstone",
        )

    def test_lineage_hint_is_stable_for_equivalent_urls(self) -> None:
        one = lineage_hint("https://example.com/a?utm_medium=social")
        two = lineage_hint("https://www.example.com/a/")
        self.assertEqual(one, two)
        self.assertTrue(one.startswith("LIN-EXAMPLE-COM-"))

    def test_normalize_query_and_next_id(self) -> None:
        self.assertEqual(normalize_query('  "Dark Gift"   Timing '), "dark gift timing")
        self.assertEqual(next_id("QRY", {"QRY-0003", "QRY-0010", "junk"}), "QRY-0011")
        self.assertEqual(next_id("SRC", set()), "SRC-0001")
        self.assertIn("counterargument", QUERY_FAMILIES)


class PlanQueriesTest(unittest.TestCase):
    def test_plan_expands_sections_languages_entities_and_dedups(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            init_bundle(run_dir, profile="editor-ready", depth="exhaustive")
            plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
            plan["deliverable_outline"] = [
                {
                    "section_id": "SEC-0001",
                    "working_title": "Dark Gift timing",
                    "reader_question": "When to press it?",
                    "readiness_condition": "x",
                    "status": "planned",
                    "coverage_note": "",
                },
                {
                    "section_id": "SEC-0002",
                    "working_title": "Excluded section",
                    "reader_question": "",
                    "readiness_condition": "x",
                    "status": "excluded",
                    "coverage_note": "out of scope",
                },
            ]
            (run_dir / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            write_jsonl(
                run_dir / "queries.jsonl",
                [executed_query("QRY-0007", "general", "Dark Gift timing explained", [])],
            )
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            manifest["current_context"] = {"patch": "36.4"}
            (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            preview = run(PLAN, str(run_dir), "--language", "en", "--language", "ru", "--entity", "Jeef")
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertFalse((run_dir / "query-plan.jsonl").exists())

            applied = run(
                PLAN, str(run_dir), "--language", "en", "--language", "ru", "--entity", "Jeef", "--apply"
            )
            self.assertEqual(applied.returncode, 0, applied.stderr)
            records = read_jsonl(run_dir / "query-plan.jsonl")
            self.assertTrue(records)
            queries = [record["query"] for record in records]
            self.assertNotIn("Dark Gift timing explained", queries)
            self.assertIn("Dark Gift timing patch notes 36.4", queries)
            self.assertIn("Jeef overrated", queries)
            self.assertIn("Dark Gift timing ошибки", queries)
            self.assertTrue(all(record["deliverable_section_ids"] == ["SEC-0001"] for record in records))
            self.assertTrue(all(record["status"] == "planned" for record in records))
            self.assertEqual(records[0]["query_id"], "QRY-0008")
            self.assertEqual(len(queries), len({normalize_query(query) for query in queries}))
            families = {record["family"] for record in records}
            self.assertIn("localized", families)
            self.assertIn("counterargument", families)

            rerun = run(PLAN, str(run_dir), "--language", "en", "--language", "ru", "--entity", "Jeef", "--apply")
            self.assertEqual(rerun.returncode, 0, rerun.stderr)
            self.assertEqual(len(read_jsonl(run_dir / "query-plan.jsonl")), len(records))

    def test_plan_refuses_long_topic_and_unknown_family(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            init_bundle(run_dir)
            result = run(PLAN, str(run_dir), "--topic", " ".join(["word"] * 13))
            self.assertEqual(result.returncode, 2)
            self.assertIn("--topic", result.stderr)
            result = run(PLAN, str(run_dir), "--topic", "Dark Gift", "--family", "nonsense")
            self.assertEqual(result.returncode, 2)
            self.assertIn("unknown query family", result.stderr)
            quick = run(PLAN, str(run_dir), "--topic", "Dark Gift", "--language", "en", "--json")
            self.assertEqual(quick.returncode, 0, quick.stderr)
            families = {json.loads(line)["family"] for line in quick.stdout.splitlines()}
            self.assertEqual(families, {"general", "primary", "statistics", "experts", "reddit", "x", "youtube", "mistakes", "counterargument", "freshness"})


class SearchCoverageTest(unittest.TestCase):
    def build_bundle(self, run_dir: Path) -> None:
        """A legacy schema 1.1 bundle: free-text families are warnings, not errors."""

        init_bundle(run_dir, depth="quick")
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        manifest["schema_version"] = "1.1"
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        write_jsonl(
            run_dir / "queries.jsonl",
            [
                executed_query("QRY-0001", "primary", "Dark Gift official", ["SRC-0001"]),
                executed_query("QRY-0002", "freshness", "Dark Gift 36.4", ["SRC-0002"]),
                executed_query("QRY-0003", "legacy label", "Dark Gift stats", []),
            ],
        )
        write_jsonl(
            run_dir / "sources.jsonl",
            [
                source("SRC-0001", "https://hearthstone.blizzard.com/news/1", "LIN-A", verified=True, run_dir=run_dir),
                source("SRC-0002", "https://hearthstone.blizzard.com/news/2", "LIN-A"),
            ],
        )
        write_jsonl(
            run_dir / "evidence.jsonl",
            [
                {"evidence_id": "EVD-0001", "source_id": "SRC-0001", "claim_ids": ["CLM-0001", "CLM-0002"], "relationship": "supporting", "locator": "p1", "evidence_type": "fact", "faithful_paraphrase": "x"},
                {"evidence_id": "EVD-0002", "source_id": "SRC-0002", "claim_ids": ["CLM-0001"], "relationship": "supporting", "locator": "p2", "evidence_type": "fact", "faithful_paraphrase": "y"},
            ],
        )
        write_jsonl(
            run_dir / "claims.jsonl",
            [
                {"claim_id": "CLM-0001", "claim": "critical thing", "importance": "critical", "status": "supported", "confidence": "HIGH", "supporting_evidence_ids": ["EVD-0001", "EVD-0002"], "challenging_evidence_ids": []},
                {"claim_id": "CLM-0002", "claim": "material thing", "importance": "material", "status": "supported", "confidence": "MEDIUM", "supporting_evidence_ids": ["EVD-0001"], "challenging_evidence_ids": [], "challenge_search": {"query_ids": ["QRY-0002"], "result": "none_found"}},
            ],
        )

    def test_report_flags_missing_families_challenges_and_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            self.build_bundle(run_dir)
            report = search_coverage.analyze(run_dir)
            errors = "\n".join(report["findings"]["errors"])
            warnings = "\n".join(report["findings"]["warnings"])
            self.assertIn("missing required quick query families: counterargument", errors)
            self.assertIn("CLM-0001", errors)
            self.assertNotIn("CLM-0002", errors)
            self.assertIn("share one lineage: CLM-0001", warnings)
            self.assertIn("share one host: CLM-0001", warnings)
            self.assertIn("fingerprint coverage 1/2", warnings)
            self.assertIn("no candidates.jsonl", warnings)
            self.assertEqual(report["queries"]["non_canonical_family"], ["QRY-0003"])
            self.assertEqual(report["claims"]["challenge_coverage"], 0.5)
            self.assertEqual(report["branches"]["__all__"]["families_present"], ["freshness", "primary"])

            strict = run(COVERAGE, str(run_dir), "--strict")
            self.assertEqual(strict.returncode, 1)
            self.assertIn("Search coverage: FAIL", strict.stdout)
            lenient = run(COVERAGE, str(run_dir), "--json")
            self.assertEqual(lenient.returncode, 0)
            self.assertEqual(json.loads(lenient.stdout)["depth"], "quick")

    def test_report_passes_when_families_and_challenges_are_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            self.build_bundle(run_dir)
            queries = read_jsonl(run_dir / "queries.jsonl")
            queries.append(executed_query("QRY-0004", "counterargument", "why not Dark Gift", []))
            write_jsonl(run_dir / "queries.jsonl", queries)
            write_jsonl(
                run_dir / "query-plan.jsonl",
                [{"query_id": "QRY-0005", "family": "reddit", "query": "site:reddit.com Dark Gift", "status": "planned"}],
            )
            write_jsonl(
                run_dir / "candidates.jsonl",
                [
                    {"candidate_id": "CAN-0001", "query_id": "QRY-0001", "url": "https://hearthstone.blizzard.com/news/1", "decision": "opened", "source_id": "SRC-0001"},
                    {"candidate_id": "CAN-0002", "query_id": "QRY-0001", "url": "https://aggregator.example/x", "decision": "rejected", "reason": "duplicate_lineage"},
                ],
            )
            claims = read_jsonl(run_dir / "claims.jsonl")
            claims[0]["challenge_search"] = {"query_ids": ["QRY-0004"], "result": "none_found"}
            write_jsonl(run_dir / "claims.jsonl", claims)
            report = search_coverage.analyze(run_dir)
            self.assertEqual(report["findings"]["errors"], [])
            self.assertEqual(report["plan"]["unexecuted_ids"], ["QRY-0005"])
            self.assertEqual(report["candidates"]["open_rate"], 0.5)
            self.assertEqual(report["candidates"]["rejections_by_reason"], {"duplicate_lineage": 1})

            validation = run(VALIDATE, str(run_dir), "--stage", "working")
            self.assertEqual(validation.returncode, 0, validation.stdout)
            self.assertIn("non-canonical query family 'legacy label'", validation.stdout)

    def test_validator_rejects_malformed_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            self.build_bundle(run_dir)
            write_jsonl(
                run_dir / "candidates.jsonl",
                [
                    {"candidate_id": "CAN-0001", "query_id": "QRY-9999", "url": "https://a.example", "decision": "opened", "source_id": "SRC-0009"},
                    {"candidate_id": "CAN-0001", "query_id": "QRY-0001", "url": "https://b.example", "decision": "rejected"},
                    {"candidate_id": "CAN-0003", "query_id": "QRY-0001", "url": "https://c.example", "decision": "maybe"},
                ],
            )
            validation = run(VALIDATE, str(run_dir), "--stage", "working")
            self.assertEqual(validation.returncode, 1)
            self.assertIn("unknown query QRY-9999", validation.stdout)
            self.assertIn("must reference a known source_id", validation.stdout)
            self.assertIn("duplicate ID CAN-0001", validation.stdout)
            self.assertIn("needs a canonical reason", validation.stdout)
            self.assertIn("invalid decision", validation.stdout)


HTML_FIXTURE = """<!doctype html><html><head><meta charset="utf-8"><title> Dark Gift  Developer Insight </title>
<style>body{color:red}</style><script>window.x = 1;</script></head>
<body><nav>Menu</nav><h1>Dark Gifts</h1><p>Dark Discovery costs <b>3</b> gold.</p>
<div><p>It unlocks on turn three.</p></div><noscript>enable js</noscript>
<p>""" + " ".join(f"Filler sentence number {i} keeps the fixture above the readable-text floor." for i in range(8)) + """</p>
</body></html>"""


def fake_transport(status: int = 200, final_url: str | None = None, body: bytes | None = None, content_type: str = "text/html; charset=utf-8"):
    def transport(request: Request, timeout: float):
        assert "Cookie" not in request.headers
        assert request.get_header("User-agent", "").startswith("deep-research-fetch-source")
        return status, final_url or request.full_url, {"Content-Type": content_type}, body if body is not None else HTML_FIXTURE.encode("utf-8")

    return transport


class FetchSourceTest(unittest.TestCase):
    def test_html_to_text_drops_scripts_and_keeps_title(self) -> None:
        title, text = fetch_source.html_to_text(HTML_FIXTURE)
        self.assertEqual(title, "Dark Gift Developer Insight")
        self.assertIn("Dark Discovery costs 3 gold.", text)
        self.assertIn("It unlocks on turn three.", text)
        self.assertNotIn("window.x", text)
        self.assertNotIn("color:red", text)
        self.assertNotIn("enable js", text)

    def test_url_safety_rules(self) -> None:
        for bad in ("ftp://example.com/x", "https://user:pw@example.com/x", "http://localhost/x", "http://10.0.0.1/x", "http://[::1]/x"):
            with self.subTest(url=bad):
                with self.assertRaises(fetch_source.FetchError):
                    fetch_source.check_url(bad, allow_private=False)
        fetch_source.check_url("http://10.0.0.1/x", allow_private=True)
        fetch_source.check_url("https://hearthstone.blizzard.com/news", allow_private=False)

    def test_fetch_rejects_non_200_and_binary(self) -> None:
        with self.assertRaises(fetch_source.FetchError):
            fetch_source.fetch("https://example.com/x", transport=fake_transport(status=404))
        with self.assertRaises(fetch_source.FetchError):
            fetch_source.fetch("https://example.com/x", transport=fake_transport(content_type="application/pdf"))
        with self.assertRaises(fetch_source.FetchError):
            fetch_source.fetch("https://example.com/x", transport=fake_transport(body=b"x" * (fetch_source.MAX_RESPONSE_BYTES + 1)))

    def test_apply_records_verified_source_and_links_query(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            init_bundle(run_dir)
            write_jsonl(run_dir / "queries.jsonl", [executed_query("QRY-0001", "primary", "Dark Gift official", [])])
            url = "https://us.forums.blizzard.com/en/hearthstone/t/dark-gifts/163606?utm_source=x"
            preview = fetch_source.main([str(run_dir), url, "--query-id", "QRY-0001"], transport=fake_transport(final_url=url.split("?")[0]))
            self.assertEqual(preview, 0)
            self.assertEqual(read_jsonl(run_dir / "sources.jsonl"), [])

            applied = fetch_source.main(
                [str(run_dir), url, "--query-id", "QRY-0001", "--source-type", "official", "--platform", "forum", "--apply"],
                transport=fake_transport(final_url=url.split("?")[0]),
            )
            self.assertEqual(applied, 0)
            sources = read_jsonl(run_dir / "sources.jsonl")
            self.assertEqual(len(sources), 1)
            record = sources[0]
            self.assertEqual(record["source_id"], "SRC-0001")
            self.assertEqual(record["title"], "Dark Gift Developer Insight")
            self.assertEqual(record["final_url"], url.split("?")[0])
            self.assertEqual(record["canonical_url"], "https://us.forums.blizzard.com/en/hearthstone/t/dark-gifts/163606")
            self.assertEqual(record["fingerprint_status"], "verified")
            self.assertTrue(record["mutable"])
            self.assertEqual(record["platform"], "forum")
            self.assertEqual(record["found_by_query_ids"], ["QRY-0001"])
            snapshot = run_dir / record["snapshot_path"]
            self.assertEqual(hashlib.sha256(snapshot.read_bytes()).hexdigest(), record["content_sha256"])
            self.assertEqual(snapshot.stat().st_size, record["content_bytes"])
            self.assertIn("Dark Discovery costs 3 gold.", snapshot.read_text(encoding="utf-8"))
            queries = read_jsonl(run_dir / "queries.jsonl")
            self.assertEqual(queries[0]["result_source_ids"], ["SRC-0001"])

            duplicate = fetch_source.main([str(run_dir), "https://www.us.forums.blizzard.com/en/hearthstone/t/dark-gifts/163606/", "--apply"], transport=fake_transport())
            self.assertEqual(duplicate, 1)
            self.assertEqual(len(read_jsonl(run_dir / "sources.jsonl")), 1)

            fingerprint = run(FINGERPRINT, str(run_dir))
            self.assertEqual(fingerprint.returncode, 0, fingerprint.stderr)
            self.assertIn("1 verified, 0 missing", fingerprint.stdout)
            validation = run(VALIDATE, str(run_dir), "--stage", "working")
            self.assertEqual(validation.returncode, 0, validation.stdout)

    def test_file_mode_ingests_saved_page_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            init_bundle(run_dir)
            saved = Path(temp) / "page.html"
            saved.write_text(HTML_FIXTURE, encoding="utf-8")
            result = run(FETCH, str(run_dir), "https://example.com/insight", "--file", str(saved), "--immutable", "--apply")
            self.assertEqual(result.returncode, 0, result.stderr)
            record = read_jsonl(run_dir / "sources.jsonl")[0]
            self.assertFalse(record["mutable"])
            self.assertEqual(record["retrieved_by"], "fetch_source.py --file")
            self.assertNotIn("http_status", record)
            self.assertTrue(record["lineage_id"].startswith("LIN-EXAMPLE-COM-"))

            unknown_query = run(FETCH, str(run_dir), "https://example.com/other", "--file", str(saved), "--query-id", "QRY-0042", "--apply")
            self.assertEqual(unknown_query.returncode, 2)
            self.assertIn("unknown query", unknown_query.stderr)


if __name__ == "__main__":
    unittest.main()


class Schema12Test(unittest.TestCase):
    """Schema 1.2 search-integrity rules: canonical queries, excerpt anchors, challenge quota."""

    def build(self, run_dir: Path) -> None:
        init_bundle(run_dir, depth="quick")
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], "1.2")
        write_jsonl(
            run_dir / "queries.jsonl",
            [
                executed_query("QRY-0001", "primary", "Dark Gift official", ["SRC-0001"]),
                {**executed_query("QRY-0002", "counterargument", "why not Dark Gift", []), "pass": "contradiction"},
            ],
        )
        write_jsonl(
            run_dir / "sources.jsonl",
            [source("SRC-0001", "https://hearthstone.blizzard.com/news/1", "LIN-A", verified=True, run_dir=run_dir)],
        )
        write_jsonl(
            run_dir / "evidence.jsonl",
            [{"evidence_id": "EVD-0001", "source_id": "SRC-0001", "claim_ids": ["CLM-0001"], "relationship": "supporting", "locator": "p1", "evidence_type": "fact", "faithful_paraphrase": "x", "exact_excerpt": "Source: SRC-0001 URL: https://hearthstone.blizzard.com/news/1"}],
        )
        write_jsonl(
            run_dir / "claims.jsonl",
            [{"claim_id": "CLM-0001", "claim": "critical thing", "importance": "critical", "status": "supported", "confidence": "HIGH", "supporting_evidence_ids": ["EVD-0001"], "challenging_evidence_ids": [], "challenge_search": {"query_ids": ["QRY-0002"], "result": "none_found"}}],
        )

    def test_anchored_and_challenged_bundle_passes_working(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            self.build(run_dir)
            result = run(VALIDATE, str(run_dir), "--stage", "working")
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertNotIn("exact_excerpt", result.stdout)
            self.assertNotIn("challenge", result.stdout)
            report = search_coverage.analyze(run_dir)
            self.assertEqual(report["anchors"]["anchor_coverage"], 1.0)

    def test_excerpt_not_in_snapshot_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            self.build(run_dir)
            evidence = read_jsonl(run_dir / "evidence.jsonl")
            evidence[0]["exact_excerpt"] = "this sentence does not appear in the snapshot"
            write_jsonl(run_dir / "evidence.jsonl", evidence)
            result = run(VALIDATE, str(run_dir), "--stage", "working")
            self.assertEqual(result.returncode, 1)
            self.assertIn("exact_excerpt not found in snapshot of SRC-0001", result.stdout)
            evidence[0]["exact_excerpt"] = "Source: SRC"
            write_jsonl(run_dir / "evidence.jsonl", evidence)
            result = run(VALIDATE, str(run_dir), "--stage", "working")
            self.assertIn("needs at least 4 words", result.stdout)

    def test_missing_anchor_and_challenge_block_final_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            self.build(run_dir)
            evidence = read_jsonl(run_dir / "evidence.jsonl")
            del evidence[0]["exact_excerpt"]
            write_jsonl(run_dir / "evidence.jsonl", evidence)
            claims = read_jsonl(run_dir / "claims.jsonl")
            del claims[0]["challenge_search"]
            write_jsonl(run_dir / "claims.jsonl", claims)
            working = run(VALIDATE, str(run_dir), "--stage", "working")
            self.assertEqual(working.returncode, 0, working.stdout)
            self.assertIn("warning: claims.jsonl:1: critical claim has no challenging evidence", working.stdout)
            self.assertIn("warning: claims.jsonl:1: supporting evidence without a verified exact_excerpt", working.stdout)
            final = run(VALIDATE, str(run_dir), "--stage", "final")
            self.assertEqual(final.returncode, 1)
            self.assertIn("- claims.jsonl:1: critical claim has no challenging evidence", final.stdout)
            self.assertIn("- claims.jsonl:1: supporting evidence without a verified exact_excerpt", final.stdout)

    def test_challenge_search_references_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            self.build(run_dir)
            claims = read_jsonl(run_dir / "claims.jsonl")
            claims[0]["challenge_search"] = {"query_ids": ["QRY-0099"], "result": "maybe"}
            write_jsonl(run_dir / "claims.jsonl", claims)
            result = run(VALIDATE, str(run_dir), "--stage", "working")
            self.assertEqual(result.returncode, 1)
            self.assertIn("references unknown query QRY-0099", result.stdout)
            self.assertIn("challenge_search result is invalid", result.stdout)

    def test_non_canonical_query_values_are_errors_in_12(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            self.build(run_dir)
            queries = read_jsonl(run_dir / "queries.jsonl")
            queries[0]["family"] = "Polish law"
            queries[0]["pass"] = "primary-source"
            del queries[0]["language"]
            write_jsonl(run_dir / "queries.jsonl", queries)
            result = run(VALIDATE, str(run_dir), "--stage", "working")
            self.assertEqual(result.returncode, 1)
            self.assertIn("- queries.jsonl:1: non-canonical query family 'Polish law'", result.stdout)
            self.assertIn("- queries.jsonl:1: non-canonical query pass 'primary-source'", result.stdout)
            self.assertIn("warning: queries.jsonl:1: schema 1.2 query should record a language", result.stdout)

    def test_migration_from_11_to_12_needs_family_map_and_is_reversible(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            self.build(run_dir)
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            manifest["schema_version"] = "1.1"
            (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            queries = read_jsonl(run_dir / "queries.jsonl")
            queries[0]["family"] = "Polish law"
            queries[0]["pass"] = "primary-source"
            del queries[0]["language"]
            write_jsonl(run_dir / "queries.jsonl", queries)
            self.assertEqual(run(VALIDATE, str(run_dir), "--stage", "working").returncode, 0)

            refused = run(MIGRATE, str(run_dir), "--to", "1.2")
            self.assertEqual(refused.returncode, 1)
            self.assertIn("family: 'Polish law'", refused.stderr)
            self.assertIn("pass: 'primary-source'", refused.stderr)

            mapping = Path(temp) / "map.json"
            mapping.write_text(json.dumps({"families": {"Polish law": "primary"}, "passes": {"primary-source": "collection"}}), encoding="utf-8")
            preview = run(MIGRATE, str(run_dir), "--to", "1.2", "--family-map", str(mapping))
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertEqual(json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["schema_version"], "1.1")

            applied = run(MIGRATE, str(run_dir), "--to", "1.2", "--family-map", str(mapping), "--apply")
            self.assertEqual(applied.returncode, 0, applied.stderr)
            migrated = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(migrated["schema_version"], "1.2")
            self.assertEqual(migrated["provenance"]["migrated_from"], "1.1")
            queries = read_jsonl(run_dir / "queries.jsonl")
            self.assertEqual(queries[0]["family"], "primary")
            self.assertEqual(queries[0]["legacy_family"], "Polish law")
            self.assertEqual(queries[0]["pass"], "collection")
            self.assertEqual(queries[0]["language"], "en")
            self.assertEqual(run(VALIDATE, str(run_dir), "--stage", "working").returncode, 0)

            backup = next((run_dir / "migration-backups").iterdir())
            rolled = run(MIGRATE, str(run_dir), "--rollback", str(backup))
            self.assertEqual(rolled.returncode, 0, rolled.stderr)
            self.assertEqual(json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["schema_version"], "1.1")
            self.assertEqual(read_jsonl(run_dir / "queries.jsonl")[0]["family"], "Polish law")


REGISTRY = ROOT / "references/domains/hearthstone-sources.json"
TIMELINE = ROOT / "references/domains/hearthstone-patches.json"
REGISTRY_SEED = SCRIPTS / "registry_seed.py"
FRESHNESS = SCRIPTS / "freshness_check.py"


class ExcerptMatchingTest(unittest.TestCase):
    def test_elided_excerpt_matches_in_order_only(self) -> None:
        from search_support import quote_in_text

        text = "Starting on Turn 3, you may spend 3 Gold to Discover a minion. This can be done once per turn, up to 3 times per game."
        self.assertTrue(quote_in_text(text, "Starting on Turn 3 ... once per turn, up to 3 times"))
        self.assertTrue(quote_in_text(text, "starting on turn 3 … up to 3 times per game."))
        self.assertFalse(quote_in_text(text, "up to 3 times ... Starting on Turn 3"))
        self.assertFalse(quote_in_text(text, "Turn ... game"))
        self.assertTrue(quote_in_text("It’s a “quoted” — phrase", "it's a \"quoted\" - phrase"))


class PlanQueriesRussianDefaultTest(unittest.TestCase):
    def test_hearthstone_domain_defaults_to_english_and_russian(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            init_bundle(run_dir)
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            manifest["current_context"] = {"client_patch": "36.4", "mode": "Solo Battlegrounds"}
            (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            result = run(PLAN, str(run_dir), "--topic", "Dark Gift timing", "--json")
            self.assertEqual(result.returncode, 0, result.stderr)
            records = [json.loads(line) for line in result.stdout.splitlines()]
            languages = {record["language"] for record in records}
            self.assertEqual(languages, {"en", "ru"})
            self.assertIn("Dark Gift timing patch notes 36.4", [record["query"] for record in records])


class RegistrySeedTest(unittest.TestCase):
    def test_registry_is_well_formed(self) -> None:
        import registry_seed

        registry = registry_seed.load_registry(REGISTRY)
        self.assertGreaterEqual(len(registry["hosts"]), 10)
        self.assertTrue(all(entry.get("authority") for entry in registry["hosts"]))

    def test_seed_filters_by_mode_and_dedups(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            init_bundle(run_dir)
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            manifest["current_context"] = {"mode": "Solo Battlegrounds"}
            (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            preview = run(REGISTRY_SEED, str(run_dir), "--json")
            self.assertEqual(preview.returncode, 0, preview.stderr)
            records = [json.loads(line) for line in preview.stdout.splitlines()]
            ids = {record["registry_id"] for record in records}
            self.assertIn("blizzard-news", ids)
            self.assertIn("r-bobstavern", ids)
            self.assertIn("koloda-battlegrounds-heroes", ids)
            self.assertNotIn("hsguru", ids)
            self.assertNotIn("r-competitivehs", ids)
            self.assertTrue(all(record["status"] == "planned" for record in records))
            self.assertTrue(all(record["family"] in QUERY_FAMILIES for record in records))
            self.assertFalse((run_dir / "query-plan.jsonl").exists())

            applied = run(REGISTRY_SEED, str(run_dir), "--apply", "--deliverable-section", "SEC-0001")
            self.assertEqual(applied.returncode, 0, applied.stderr)
            first = read_jsonl(run_dir / "query-plan.jsonl")
            self.assertEqual(len(first), len(records))
            self.assertEqual(first[0]["deliverable_section_ids"], ["SEC-0001"])
            again = run(REGISTRY_SEED, str(run_dir), "--apply")
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(len(read_jsonl(run_dir / "query-plan.jsonl")), len(records))

            constructed = run(REGISTRY_SEED, str(run_dir), "--mode", "constructed", "--section", "hosts", "--json")
            constructed_ids = {json.loads(line)["registry_id"] for line in constructed.stdout.splitlines()}
            self.assertIn("hsguru", constructed_ids)
            self.assertNotIn("amalgadon", constructed_ids)

    def test_coverage_reports_registry_share(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            init_bundle(run_dir)
            write_jsonl(
                run_dir / "sources.jsonl",
                [
                    source("SRC-0001", "https://hearthstone.blizzard.com/en-us/news/1", "LIN-A"),
                    source("SRC-0002", "https://api.kolodahearthstone.com/v1/battlegrounds/heroes", "LIN-B"),
                    source("SRC-0003", "https://randomblog.example/post", "LIN-C"),
                ],
            )
            report = search_coverage.analyze(run_dir)
            registry = report["registry"]
            self.assertTrue(registry["present"])
            self.assertEqual(registry["sources_from_registry"], 2)
            self.assertEqual(registry["hosts_outside_registry"], ["randomblog.example"])
            self.assertEqual(registry["authoritative_hosts_used"], ["api.kolodahearthstone.com", "hearthstone.blizzard.com"])
            self.assertTrue(any("outside the registry" in item for item in report["findings"]["warnings"]))


class FreshnessCheckTest(unittest.TestCase):
    def test_timeline_is_well_formed(self) -> None:
        import freshness_check

        patches = freshness_check.load_timeline(TIMELINE)
        self.assertEqual(patches[-1]["version"], "36.4")
        self.assertEqual(freshness_check.latest_as_of(freshness_check.patches_for_mode(patches, "battlegrounds"), __import__("datetime").date(2026, 8, 10))["version"], "36.2.1")

    def test_stale_patch_and_unlabeled_sources_are_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            init_bundle(run_dir)
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
            manifest["as_of"] = "2026-08-31"
            manifest["current_context"] = {"client_patch": "36.2.2", "mode": "Solo Battlegrounds"}
            (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            old_current = source("SRC-0001", "https://hearthstone.blizzard.com/news/1", "LIN-A")
            old_current.update({"patch": "36.2", "freshness_status": "CURRENT"})
            old_labeled = source("SRC-0002", "https://hearthstone.blizzard.com/news/2", "LIN-B")
            old_labeled.update({"patch": "36.2", "freshness_status": "STALE_IN_PART"})
            unknown = source("SRC-0003", "https://hearthstone.blizzard.com/news/3", "LIN-C")
            unknown.update({"patch": "99.9"})
            no_patch = source("SRC-0004", "https://www.youtube.com/watch?v=abc", "LIN-D")
            no_patch.update({"freshness_status": "CURRENT", "published_at": "2026-08-10"})
            # Battlegrounds balance last changed in 36.2.2; a 36.2.2 source labeled CURRENT stays valid across 36.4.
            still_current = source("SRC-0005", "https://hearthstone.blizzard.com/news/5", "LIN-E")
            still_current.update({"patch": "36.2.2", "freshness_status": "CURRENT"})
            write_jsonl(run_dir / "sources.jsonl", [old_current, old_labeled, unknown, no_patch, still_current])

            result = run(FRESHNESS, str(run_dir), "--strict")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("declared client patch 36.2.2 is older than 36.4", result.stdout)
            self.assertIn("SRC-0001 (36.2 < 36.2.2)", result.stdout)
            self.assertNotIn("SRC-0002", result.stdout.split("without a stale")[1].split("\n")[0])
            self.assertIn("SRC-0003 (99.9)", result.stdout)
            self.assertNotIn("SRC-0005", result.stdout)
            self.assertIn("published before the latest balance patch and name no patch: SRC-0004", result.stdout)

            manifest["current_context"]["client_patch"] = "36.4"
            (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            old_current["freshness_status"] = "VERSION_COMPATIBLE"
            unknown["patch"] = "36.4"
            write_jsonl(run_dir / "sources.jsonl", [old_current, old_labeled, unknown, no_patch, still_current])
            result = run(FRESHNESS, str(run_dir), "--strict", "--json")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["findings"]["errors"], [])
            self.assertEqual(report["latest_patch"]["version"], "36.4")
            self.assertEqual(report["latest_balance_patch"]["version"], "36.2.2")


CANDIDATES = SCRIPTS / "candidates.py"
LINEAGE = SCRIPTS / "lineage_suggest.py"


class CandidatesLedgerTest(unittest.TestCase):
    def test_record_reject_bulk_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            init_bundle(run_dir)
            write_jsonl(run_dir / "queries.jsonl", [executed_query("QRY-0001", "primary", "Dark Gift official", [])])
            rejected = run(CANDIDATES, "record", str(run_dir), "--query-id", "QRY-0001", "--url", "https://agg.example/x?utm_source=a", "--decision", "rejected", "--reason", "duplicate_lineage", "--rank", "3")
            self.assertEqual(rejected.returncode, 0, rejected.stderr)
            missing_reason = run(CANDIDATES, "record", str(run_dir), "--query-id", "QRY-0001", "--url", "https://agg.example/y", "--decision", "rejected")
            self.assertEqual(missing_reason.returncode, 2)
            unknown = run(CANDIDATES, "record", str(run_dir), "--query-id", "QRY-0009", "--url", "https://agg.example/y", "--decision", "deferred")
            self.assertEqual(unknown.returncode, 2)
            # Same query and canonical URL updates the row instead of duplicating it.
            again = run(CANDIDATES, "record", str(run_dir), "--query-id", "QRY-0001", "--url", "https://www.agg.example/x/", "--decision", "deferred")
            self.assertEqual(again.returncode, 0, again.stderr)
            records = read_jsonl(run_dir / "candidates.jsonl")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["decision"], "deferred")
            self.assertNotIn("reason", records[0])
            self.assertEqual(records[0]["rank"], 3)

            bulk = Path(temp) / "bulk.json"
            bulk.write_text(json.dumps([
                {"query_id": "QRY-0001", "url": "https://b.example/1", "decision": "rejected", "reason": "off_topic"},
                {"query_id": "QRY-0001", "url": "https://b.example/2"},
            ]), encoding="utf-8")
            result = run(CANDIDATES, "bulk", str(run_dir), str(bulk))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(read_jsonl(run_dir / "candidates.jsonl")), 3)
            summary = run(CANDIDATES, "summary", str(run_dir))
            self.assertIn("deferred=2", summary.stdout)
            self.assertIn("rejected off_topic: 1", summary.stdout)
            validation = run(VALIDATE, str(run_dir), "--stage", "working")
            self.assertEqual(validation.returncode, 0, validation.stdout)

    def test_fetch_source_records_opened_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            init_bundle(run_dir)
            write_jsonl(run_dir / "queries.jsonl", [executed_query("QRY-0001", "primary", "Dark Gift official", [])])
            url = "https://us.forums.blizzard.com/en/hearthstone/t/dark-gifts/163606"
            run(CANDIDATES, "record", str(run_dir), "--query-id", "QRY-0001", "--url", url, "--decision", "deferred")
            applied = fetch_source.main([str(run_dir), url, "--query-id", "QRY-0001", "--apply"], transport=fake_transport())
            self.assertEqual(applied, 0)
            records = read_jsonl(run_dir / "candidates.jsonl")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["decision"], "opened")
            self.assertEqual(records[0]["source_id"], "SRC-0001")
            self.assertEqual(records[0]["title"], "Dark Gift Developer Insight")
            report = search_coverage.analyze(run_dir)
            self.assertEqual(report["candidates"]["open_rate"], 1.0)


class LineageSuggestTest(unittest.TestCase):
    def test_near_duplicate_snapshots_share_lineage_after_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            init_bundle(run_dir)
            base = " ".join(f"word{i} dark gift timing matters on turn {i % 7}" for i in range(60))
            (run_dir / "snapshots").mkdir()
            texts = {
                "SRC-0001": "Source: A\nURL: https://a.example/orig\n\n" + base,
                "SRC-0002": "Source: B\nURL: https://b.example/repost\n\n" + base + " extra closing remark",
                "SRC-0003": "Source: C\nURL: https://c.example/other\n\n" + " ".join(f"unrelated token {i} about arena drafting" for i in range(60)),
            }
            records = []
            for index, (source_id, text) in enumerate(texts.items(), 1):
                (run_dir / "snapshots" / f"{source_id}.txt").write_text(text, encoding="utf-8")
                record = source(source_id, f"https://{'abc'[index-1]}.example/{source_id}", f"LIN-{index}")
                record["accessed_at"] = f"2026-09-01T10:0{index}:00Z"
                record["snapshot_path"] = f"snapshots/{source_id}.txt"
                records.append(record)
            write_jsonl(run_dir / "sources.jsonl", records)

            preview = run(LINEAGE, str(run_dir), "--json")
            self.assertEqual(preview.returncode, 0, preview.stderr)
            report = json.loads(preview.stdout)
            self.assertEqual(report["compared"], 3)
            self.assertEqual(len(report["suggestions"]), 1)
            suggestion = report["suggestions"][0]
            self.assertEqual((suggestion["source_a"], suggestion["source_b"]), ("SRC-0001", "SRC-0002"))
            self.assertEqual(suggestion["adopting_source_id"], "SRC-0002")
            self.assertEqual(suggestion["suggested_lineage_id"], "LIN-1")
            self.assertEqual(read_jsonl(run_dir / "sources.jsonl")[1]["lineage_id"], "LIN-2")

            applied = run(LINEAGE, str(run_dir), "--apply")
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertIn("Applied lineage to 1 sources", applied.stdout)
            updated = read_jsonl(run_dir / "sources.jsonl")
            self.assertEqual(updated[1]["lineage_id"], "LIN-1")
            self.assertEqual(updated[1]["previous_lineage_id"], "LIN-2")
            self.assertEqual(updated[1]["lineage_matched_source_id"], "SRC-0001")
            self.assertEqual(updated[2]["lineage_id"], "LIN-3")
            rerun = json.loads(run(LINEAGE, str(run_dir), "--json").stdout)
            self.assertEqual(rerun["suggestions"], [])


class SaturationTest(unittest.TestCase):
    def test_yield_attribution_and_trailing_zero_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            init_bundle(run_dir, depth="quick")
            queries = [
                executed_query("QRY-0001", "primary", "q1", ["SRC-0001"]),
                executed_query("QRY-0002", "statistics", "q2", ["SRC-0002"]),
                executed_query("QRY-0003", "experts", "q3", []),
                executed_query("QRY-0004", "counterargument", "q4", ["SRC-0001"]),
                executed_query("QRY-0005", "freshness", "q5", []),
            ]
            for index, record in enumerate(queries):
                record["executed_at"] = f"2026-09-01T10:0{index}:00Z"
            write_jsonl(run_dir / "queries.jsonl", queries)
            write_jsonl(run_dir / "sources.jsonl", [
                source("SRC-0001", "https://hearthstone.blizzard.com/news/1", "LIN-A"),
                source("SRC-0002", "https://hsreplay.net/meta/", "LIN-B"),
            ])
            write_jsonl(run_dir / "evidence.jsonl", [
                {"evidence_id": "EVD-0001", "source_id": "SRC-0001", "claim_ids": ["CLM-0001"], "relationship": "supporting", "locator": "p", "evidence_type": "fact", "faithful_paraphrase": "x"},
                {"evidence_id": "EVD-0002", "source_id": "SRC-0002", "claim_ids": ["CLM-0002"], "relationship": "supporting", "locator": "p", "evidence_type": "statistic", "faithful_paraphrase": "y"},
            ])
            write_jsonl(run_dir / "claims.jsonl", [
                {"claim_id": "CLM-0001", "claim": "a", "importance": "critical", "status": "supported", "confidence": "HIGH", "supporting_evidence_ids": ["EVD-0001"], "challenging_evidence_ids": [], "challenge_search": {"query_ids": ["QRY-0004"], "result": "none_found"}},
                {"claim_id": "CLM-0002", "claim": "b", "importance": "material", "status": "supported", "confidence": "MEDIUM", "supporting_evidence_ids": ["EVD-0002"], "challenging_evidence_ids": []},
            ])
            report = search_coverage.analyze(run_dir)
            self.assertEqual(report["yield_by_query"], {"QRY-0001": 1, "QRY-0002": 1, "QRY-0003": 0, "QRY-0004": 0, "QRY-0005": 0})
            sat = report["saturation"]["__all__"]
            self.assertEqual(sat["claims_yielded"], 2)
            self.assertEqual(sat["last_yield_query_id"], "QRY-0002")
            self.assertEqual(sat["trailing_zero_yield"], 3)
            self.assertTrue(sat["saturated"])
            self.assertFalse(any("not yet saturated" in item for item in report["findings"]["warnings"]))
            # A query that only re-finds a known source yields nothing; one that supports a new claim resets the run.
            queries.append({**executed_query("QRY-0006", "reddit", "q6", ["SRC-0002"]), "executed_at": "2026-09-01T10:09:00Z"})
            write_jsonl(run_dir / "queries.jsonl", queries)
            self.assertEqual(search_coverage.analyze(run_dir)["saturation"]["__all__"]["trailing_zero_yield"], 4)
            queries.append({**executed_query("QRY-0007", "youtube", "q7", ["SRC-0003"]), "executed_at": "2026-09-01T10:10:00Z"})
            write_jsonl(run_dir / "queries.jsonl", queries)
            sources = read_jsonl(run_dir / "sources.jsonl")
            sources.append(source("SRC-0003", "https://www.youtube.com/watch?v=abc", "LIN-C"))
            write_jsonl(run_dir / "sources.jsonl", sources)
            evidence = read_jsonl(run_dir / "evidence.jsonl")
            evidence.append({"evidence_id": "EVD-0003", "source_id": "SRC-0003", "claim_ids": ["CLM-0003"], "relationship": "supporting", "locator": "12:30", "evidence_type": "opinion", "faithful_paraphrase": "z"})
            write_jsonl(run_dir / "evidence.jsonl", evidence)
            claims = read_jsonl(run_dir / "claims.jsonl")
            claims.append({"claim_id": "CLM-0003", "claim": "c", "importance": "supporting", "status": "supported", "confidence": "LOW", "supporting_evidence_ids": ["EVD-0003"], "challenging_evidence_ids": []})
            write_jsonl(run_dir / "claims.jsonl", claims)
            report = search_coverage.analyze(run_dir)
            self.assertEqual(report["yield_by_query"]["QRY-0007"], 1)
            self.assertEqual(report["saturation"]["__all__"]["trailing_zero_yield"], 0)
            self.assertTrue(any("not yet saturated" in item for item in report["findings"]["warnings"]))


class FetchRefreshTest(unittest.TestCase):
    def test_refresh_replaces_snapshot_and_keeps_descriptive_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            init_bundle(run_dir)
            record = source("SRC-0001", "https://us.forums.blizzard.com/en/hearthstone/t/dark-gifts/163606", "LIN-HAND")
            record.update({"title": "Hand-written title", "author": "Blizzard", "patch": "36.2", "notes": "keep me"})
            write_jsonl(run_dir / "sources.jsonl", [record])
            both = fetch_source.main([str(run_dir), "https://x.example", "--refresh", "SRC-0001", "--apply"], transport=fake_transport())
            self.assertEqual(both, 2)
            unknown = fetch_source.main([str(run_dir), "--refresh", "SRC-0009", "--apply"], transport=fake_transport())
            self.assertEqual(unknown, 2)
            refreshed = fetch_source.main([str(run_dir), "--refresh", "SRC-0001", "--apply"], transport=fake_transport())
            self.assertEqual(refreshed, 0)
            sources = read_jsonl(run_dir / "sources.jsonl")
            self.assertEqual(len(sources), 1)
            updated = sources[0]
            self.assertEqual(updated["source_id"], "SRC-0001")
            self.assertEqual(updated["title"], "Hand-written title")
            self.assertEqual(updated["author"], "Blizzard")
            self.assertEqual(updated["patch"], "36.2")
            self.assertEqual(updated["lineage_id"], "LIN-HAND")
            self.assertEqual(updated["fingerprint_status"], "verified")
            self.assertNotIn("fingerprint_reason", updated)
            snapshot = run_dir / updated["snapshot_path"]
            self.assertEqual(hashlib.sha256(snapshot.read_bytes()).hexdigest(), updated["content_sha256"])
            self.assertIn("Dark Discovery costs 3 gold.", snapshot.read_text(encoding="utf-8"))
            again = fetch_source.main([str(run_dir), "--refresh", "SRC-0001", "--apply"], transport=fake_transport())
            self.assertEqual(again, 0)
            self.assertEqual(len(read_jsonl(run_dir / "sources.jsonl")), 1)

    def test_thin_or_javascript_shell_pages_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            init_bundle(run_dir)
            shell = b"<html><head><title>App</title></head><body><div id='root'></div><p>Please enable JavaScript to continue.</p></body></html>"
            result = fetch_source.main([str(run_dir), "https://spa.example/page", "--apply"], transport=fake_transport(body=shell))
            self.assertEqual(result, 1)
            self.assertEqual(read_jsonl(run_dir / "sources.jsonl"), [])


RECALL = SCRIPTS / "validate_recall.py"
RECALL_DIR = ROOT.parent / "evaluation/recall"


class RecallBenchmarkTest(unittest.TestCase):
    def test_case_definitions_are_valid(self) -> None:
        result = run(RECALL, str(RECALL_DIR), "--stage", "plan")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("10 cases defined", result.stdout)

    def test_scoring_reports_recall_misses_and_first_authoritative_query(self) -> None:
        import validate_recall

        with tempfile.TemporaryDirectory() as temp:
            bench = Path(temp) / "recall"
            bench.mkdir()
            case = {
                "case_id": "RECALL-101", "oracle_version": "1.0", "title": "t", "domain": "hearthstone", "mode": "battlegrounds", "as_of": "2026-08-31", "prompt": "p",
                "gold_sources": [
                    {"match": "url", "url": "https://hearthstone.blizzard.com/en-us/news/24293284", "source_class": "official", "why": "patch"},
                    {"match": "host_prefix", "host": "api.kolodahearthstone.com", "path_prefix": "/api/bg", "source_class": "statistics", "why": "stats"},
                    {"match": "host_prefix", "host": "www.reddit.com", "path_prefix": "/r/BobsTavern", "source_class": "community", "why": "community"},
                ],
            }
            (bench / "cases.jsonl").write_text("".join(json.dumps(case) + "\n" for _ in range(1)) * 1, encoding="utf-8")
            errors = validate_recall.validate_cases([case])
            self.assertEqual(errors, [])
            bad = dict(case, gold_sources=[{"match": "url", "url": "http://x", "why": "", "source_class": "x"}])
            self.assertTrue(validate_recall.validate_cases([bad]))

            run_dir = Path(temp) / "run"
            init_bundle(run_dir)
            write_jsonl(run_dir / "sources.jsonl", [
                {**source("SRC-0001", "https://www.reddit.com/r/BobsTavern/comments/abc/", "LIN-A"), "source_type": "community"},
                {**source("SRC-0002", "https://hearthstone.blizzard.com/en-us/news/24293284?utm_source=x", "LIN-B"), "source_type": "official"},
            ])
            write_jsonl(run_dir / "queries.jsonl", [
                executed_query("QRY-0001", "reddit", "q1", ["SRC-0001"]),
                {**executed_query("QRY-0002", "primary", "q2", ["SRC-0002"]), "executed_at": "2026-09-01T10:05:00Z"},
            ])
            report = validate_recall.score_bundle(case, run_dir)
            self.assertEqual(report["gold_found"], 2)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["misses"][0]["gold"], "api.kolodahearthstone.com/api/bg")
            self.assertEqual(report["queries_to_first_authoritative"], 2)

            (bench / "results.jsonl").write_text(json.dumps({"case_id": "RECALL-101", "bundle_path": str(run_dir)}) + "\n", encoding="utf-8")
            cases = [dict(case, case_id=f"RECALL-{100 + i}") for i in range(1, 11)]
            (bench / "cases.jsonl").write_text("".join(json.dumps(item) + "\n" for item in cases), encoding="utf-8")
            scored = run(RECALL, str(bench), "--stage", "score")
            self.assertEqual(scored.returncode, 1, scored.stdout)
            self.assertIn("RECALL-101: fail recall 0.667", scored.stdout)
            self.assertIn("not_run: RECALL-102", scored.stdout)
            sources = read_jsonl(run_dir / "sources.jsonl")
            sources.append({**source("SRC-0003", "https://api.kolodahearthstone.com/api/bg/heroes/1", "LIN-C"), "source_type": "statistics"})
            write_jsonl(run_dir / "sources.jsonl", sources)
            scored = run(RECALL, str(bench), "--stage", "score")
            self.assertEqual(scored.returncode, 0, scored.stdout)
            self.assertIn("RECALL-101: pass recall 1.0", scored.stdout)
            strict = run(RECALL, str(bench), "--stage", "score", "--require-all")
            self.assertEqual(strict.returncode, 1)


TRIAL = SCRIPTS / "model_trial.py"


class ModelTrialTest(unittest.TestCase):
    def test_start_prepares_bundle_task_and_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            trial_dir = Path(temp) / "trial"
            result = run(TRIAL, "start", str(trial_dir), "--case", "RECALL-006", "--host", "gemini-cli", "--model", "gemini-test")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            trial = json.loads((trial_dir / "trial.json").read_text(encoding="utf-8"))
            self.assertEqual(trial["case_id"], "RECALL-006")
            self.assertEqual(trial["host"], "gemini-cli")
            self.assertEqual(trial["languages"], ["en", "ru"])
            bundle = Path(trial["bundle"])
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "1.2")
            self.assertEqual(manifest["as_of"], "2026-08-31")
            self.assertEqual(manifest["current_context"]["mode"], "Solo Battlegrounds")
            plan = read_jsonl(bundle / "query-plan.jsonl")
            self.assertTrue(any(record.get("registry_id") == "blizzard-news" for record in plan))
            self.assertTrue(any(record.get("family") == "counterargument" for record in plan))
            task = (trial_dir / "TASK.md").read_text(encoding="utf-8")
            self.assertIn("When should the first Dark Gift", task)
            self.assertIn("fetch_source.py", task)
            self.assertIn("validate_research_run.py", task)
            self.assertIn("Never invent a source", task)
            refused = run(TRIAL, "start", str(trial_dir), "--case", "RECALL-006", "--host", "codex", "--model", "x")
            self.assertEqual(refused.returncode, 2)
            unknown = run(TRIAL, "start", str(Path(temp) / "other"), "--case", "RECALL-999", "--host", "codex", "--model", "x")
            self.assertEqual(unknown.returncode, 2)

    def test_score_and_compare_produce_transparent_totals(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            trial_dir = Path(temp) / "trial"
            start = run(TRIAL, "start", str(trial_dir), "--case", "RECALL-006", "--host", "claude-code", "--model", "claude-test", "--depth", "quick")
            self.assertEqual(start.returncode, 0, start.stderr)
            bundle = Path(json.loads((trial_dir / "trial.json").read_text(encoding="utf-8"))["bundle"])
            empty = run(TRIAL, "score", str(trial_dir), "--json")
            self.assertEqual(empty.returncode, 0, empty.stderr)
            empty_card = json.loads(empty.stdout)
            self.assertLess(empty_card["total"], 15)
            self.assertEqual(empty_card["components"]["recall"]["points"], 0)

            # Fill the bundle with gold sources, anchored evidence, and a challenge search.
            gold = [
                ("SRC-0001", "https://us.forums.blizzard.com/en/hearthstone/t/battlegrounds-developer-insight-dark-gifts/163606", "official"),
                ("SRC-0002", "https://us.forums.blizzard.com/en/hearthstone/t/3621-hotfix-patch/164300", "official"),
                ("SRC-0003", "https://hearthstone.blizzard.com/en-us/news/24293284", "official"),
                ("SRC-0004", "https://api.kolodahearthstone.com/api/bg/heroes", "statistics"),
                ("SRC-0005", "https://www.youtube.com/watch?v=qvhwVb1NSOw", "video"),
            ]
            sources = []
            for source_id, url, source_type in gold:
                record = source(source_id, url, f"LIN-{source_id}", verified=True, run_dir=bundle)
                record.update({"source_type": source_type, "patch": "36.2.2", "freshness_status": "CURRENT"})
                sources.append(record)
            write_jsonl(bundle / "sources.jsonl", sources)
            write_jsonl(bundle / "queries.jsonl", [
                {**executed_query("QRY-0001", "primary", "Dark Gift official", ["SRC-0001", "SRC-0002", "SRC-0003"]), "pass": "discovery"},
                {**executed_query("QRY-0002", "statistics", "Dark Gift statistics", ["SRC-0004"]), "executed_at": "2026-09-01T10:01:00Z"},
                {**executed_query("QRY-0003", "counterargument", "why not Dark Gift", []), "pass": "contradiction", "executed_at": "2026-09-01T10:02:00Z"},
                {**executed_query("QRY-0004", "freshness", "Dark Gift 36.4", []), "pass": "freshness", "executed_at": "2026-09-01T10:03:00Z"},
                {**executed_query("QRY-0005", "youtube", "Dark Gift video", ["SRC-0005"]), "executed_at": "2026-09-01T10:04:00Z"},
            ])
            write_jsonl(bundle / "evidence.jsonl", [
                {"evidence_id": "EVD-0001", "source_id": "SRC-0001", "claim_ids": ["CLM-0001"], "relationship": "supporting", "locator": "p1", "evidence_type": "fact", "faithful_paraphrase": "x", "exact_excerpt": "Source: SRC-0001 URL: https://us.forums.blizzard.com"},
            ])
            write_jsonl(bundle / "claims.jsonl", [
                {"claim_id": "CLM-0001", "claim": "critical thing", "importance": "critical", "status": "supported", "confidence": "HIGH", "supporting_evidence_ids": ["EVD-0001"], "challenging_evidence_ids": [], "challenge_search": {"query_ids": ["QRY-0003"], "result": "none_found"}},
            ])
            manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
            manifest["current_context"]["client_patch"] = "36.4"
            (bundle / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            scored = run(TRIAL, "score", str(trial_dir))
            self.assertEqual(scored.returncode, 0, scored.stdout + scored.stderr)
            card = json.loads((trial_dir / "scorecard.json").read_text(encoding="utf-8"))
            self.assertEqual(card["components"]["recall"]["points"], 20)
            self.assertEqual(card["components"]["anchors"]["points"], 10)
            self.assertEqual(card["components"]["challenge"]["points"], 10)
            self.assertEqual(card["components"]["fingerprints"]["points"], 10)
            self.assertEqual(card["components"]["freshness"]["points"], 5)
            self.assertEqual(card["components"]["families"]["points"], 10)
            self.assertEqual(card["facts"]["final_validation"], "fail")
            self.assertGreater(card["total"], empty_card["total"])
            self.assertEqual(card["total"], round(sum(item["points"] for item in card["components"].values()), 1))

            other = Path(temp) / "other"
            run(TRIAL, "start", str(other), "--case", "RECALL-006", "--host", "codex", "--model", "codex-test", "--depth", "quick")
            run(TRIAL, "score", str(other))
            table = Path(temp) / "compare.md"
            compare = run(TRIAL, "compare", str(trial_dir), str(other), "--markdown", str(table))
            self.assertEqual(compare.returncode, 0, compare.stderr)
            lines = compare.stdout.splitlines()
            self.assertIn("| trial | host | model | case | total |", lines[0])
            self.assertIn("claude-code", lines[2])
            self.assertIn("codex", lines[3])
            self.assertTrue(table.is_file())
