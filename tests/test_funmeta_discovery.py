import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/funmeta/scripts/funmeta.py"
sys.path.insert(0, str(SCRIPT.parent))
from discovery import plan, provenance, shortlist_count
from quality import next_actions
from funmeta import initialize, validate
from test_funmeta import FunmetaV2Fixture


def run_data():
    return {"schema_version": 2, "discovery_policy": 1, "format": "standard",
            "sources": [], "search_log": [], "candidates": [], "gaps": {}, "meta_source_ids": []}


def attempt(class_name, channel, language="en", **extra):
    return {"id": f"{class_name}-{channel}-{language}", "class": class_name,
            "channel": channel, "language": language, "query": "actual query",
            "notes": "source unavailable", "status": "blocked", "source_ids": [], **extra}


class DiscoveryTests(unittest.TestCase):
    def test_catalog_calls_cover_all_classes_without_restrictive_query(self):
        tasks = plan(run_data(), 11)["suggested_queries"]
        self.assertEqual(len(tasks), 11)
        self.assertEqual({t["channel"] for t in tasks}, {"catalog"})
        names = {t["arguments"]["className"] for t in tasks}
        self.assertTrue({"DeathKnight", "DemonHunter", "Mage", "Warrior"} <= names)
        self.assertTrue(all("query" not in t["arguments"] for t in tasks))

    def test_blocked_catalog_moves_to_new_sources_without_repeating_page(self):
        data = run_data()
        first = plan(data, 11)["suggested_queries"]
        data["search_log"] = [attempt(t["class"], "catalog") for t in first]
        tasks = plan(data, 11)["suggested_queries"]
        self.assertEqual({t["channel"] for t in tasks}, {"creators"})

    def test_old_generic_attempts_do_not_exhaust_new_channels(self):
        data = run_data()
        for i in range(4):
            row = attempt("death-knight", "catalog")
            row.pop("channel")
            row["id"] = str(i)
            data["search_log"].append(row)
        self.assertEqual(plan(data)["suggested_queries"][0]["arguments"]["className"], "DeathKnight")

    def test_real_pagination_uses_reported_offset(self):
        data = run_data()
        data["sources"] = [{"id": "read", "kind": "deck", "access": "full", "url": "https://example.com/deck"}]
        data["search_log"] = [attempt("mage", "catalog", status="inspected", source_ids=["read"], next_offset=30)]
        # Other classes have already completed source discovery.
        data["candidates"] = [{"id": key, "class": key, "decision": "include"}
                              for key in ("death-knight", "demon-hunter", "druid", "hunter", "paladin",
                                          "priest", "rogue", "shaman", "warlock", "warrior")]
        data["search_log"].extend(attempt(c["class"], "community", language)
                                  for c in data["candidates"] for language in ("ru", "en"))
        tasks = plan(data, 22)["suggested_queries"]
        page = next(t for t in tasks if t["class"] == "mage" and t["channel"] == "catalog")
        self.assertEqual(page["arguments"]["offset"], 30)

    def test_snippets_and_same_composition_do_not_fill_shortlist(self):
        data = run_data()
        data["sources"] = [{"id": "a", "kind": "deck", "access": "full", "url": "https://example.com/1"},
                           {"id": "b", "kind": "deck", "access": "excerpt", "url": "https://example.com/2"}]
        base = {"id": "a", "class": "mage", "decision": "pending", "source_ids": ["a"],
                "deck_list": {"format": 2, "heroes": [7], "cards": [[1, 2]], "sideboards": []}}
        data["candidates"] = [base, {**base, "id": "copy"}, {**base, "id": "snippet", "source_ids": ["b"]}]
        result = plan(data, 22)
        self.assertEqual(next(c for c in result["coverage"] if c["class"] == "mage")["distinct_full_source_leads"], 1)
        self.assertGreater(result["remaining_search_lanes"], 60)  # Mage still contributes six lanes.
        self.assertIn("obtain_or_reconstruct_and_compare_code", result["candidate_tasks"][0]["tasks"])
        self.assertIn("read_full_deck_source", result["candidate_tasks"][2]["tasks"])
        self.assertTrue(result["meta_tasks"])

    def test_gap_needs_both_languages_distinct_channels_and_real_focus(self):
        data = run_data()
        data["search_log"] = [attempt("mage", "creators"), attempt("mage", "community", "ru"),
                              attempt("mage", "build-around")]
        def ready():
            return next(r for r in plan(data)["coverage"] if r["class"] == "mage")["gap_search_complete"]
        self.assertFalse(ready())
        data["search_log"][-1]["focus"] = "synthetic sourced card"
        self.assertTrue(ready())
        data["search_log"][1]["language"] = "en"
        self.assertFalse(ready())

    def test_catalog_repeated_offset_is_rejected_instead_of_looping(self):
        data = run_data()
        data["sources"] = [{"id": "read", "kind": "community"}]
        data["search_log"] = [attempt("mage", "catalog", status="inspected", source_ids=["read"], next_offset=30),
                              attempt("mage", "catalog", id="second", status="inspected", source_ids=["read"], next_offset=30)]
        with self.assertRaisesRegex(ValueError, "must advance"):
            plan(data)

    def test_bad_policy_and_unknown_channel_fail(self):
        for value in (True, 0, 2, "1"):
            data = run_data()
            data["discovery_policy"] = value
            with self.assertRaisesRegex(ValueError, "discovery_policy"):
                plan(data)
        data = run_data()
        data["search_log"] = [attempt("mage", "invented")]
        with self.assertRaisesRegex(ValueError, "channel"):
            plan(data)

    def test_selected_class_still_gets_missing_language_search(self):
        data = run_data()
        data["candidates"] = [{"id": "a", "class": "mage", "decision": "include"}]
        data["search_log"] = [attempt("mage", "creators")]
        data["candidates"].extend({"id": name, "class": name, "decision": "include"}
                                  for name in ("death-knight", "demon-hunter", "druid", "hunter", "paladin",
                                               "priest", "rogue", "shaman", "warlock", "warrior"))
        tasks = [t for t in plan(data, 22)["suggested_queries"] if t["class"] == "mage"]
        self.assertEqual([(t["channel"], t["language"]) for t in tasks], [("community", "ru")])
        self.assertEqual(next_actions(data), plan(data))

    def test_same_source_and_mirrored_composition_count_once(self):
        sources = {name: {"kind": "deck", "access": "full", "url": f"https://example.com/{name}"}
                   for name in ("a", "b")}
        deck = {"format": 2, "heroes": [7], "cards": [[1, 2]], "sideboards": []}
        candidates = [{"class": "mage", "source_ids": ["a"]},
                      {"class": "mage", "source_ids": ["a", "b"], "deck_list": deck},
                      {"class": "mage", "source_ids": ["b"], "deck_list": deck}]
        self.assertEqual(shortlist_count(candidates, sources), 1)

    def test_cli_plan_and_next_are_read_only_and_ignore_missing_meta(self):
        with tempfile.TemporaryDirectory() as temporary:
            selection = initialize(Path(temporary) / "run", "2026-10-19", "standard")
            before = selection.read_bytes()
            for command in ("plan", "next"):
                result = subprocess.run([sys.executable, str(SCRIPT), command, str(selection)],
                                        capture_output=True, encoding="utf-8")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["suggested_queries"][0]["channel"], "catalog")
            self.assertEqual(selection.read_bytes(), before)

    def test_code_origin_requires_full_source_for_this_candidate(self):
        sources = {"a": {"kind": "deck", "access": "full"}, "b": {"kind": "deck", "access": "full"}}
        candidate = {"source_ids": ["a"]}
        for kind in ("author-export", "reconstructed-list"):
            candidate["code_provenance"] = {"kind": kind, "source_ids": ["a"]}
            provenance(candidate, sources)
            candidate["code_provenance"]["source_ids"] = ["b"]
            with self.assertRaisesRegex(ValueError, "full deck source"):
                provenance(candidate, sources)


class NewPolicyValidationTests(FunmetaV2Fixture, unittest.TestCase):
    # Reuse the mature acceptance fixture; these tests exercise full check, not only helpers.
    def test_new_policy_refuses_unsearched_gaps_and_missing_code_origin(self):
        self.data["discovery_policy"] = 1
        with self.assertRaisesRegex(ValueError, "code_provenance"):
            validate(self.data, self.run)
        self.candidate["code_provenance"] = {"kind": "reconstructed-list", "source_ids": ["deck"]}
        with self.assertRaisesRegex(ValueError, "broaden source"):
            validate(self.data, self.run)
        for class_name in self.data["gaps"]:
            self.data["search_log"].extend([attempt(class_name, "creators"),
                attempt(class_name, "community", "ru"), attempt(class_name, "build-around", focus="sourced card")])
        self.assertEqual(validate(self.data, self.run)["status"], "structure_valid")

    def test_unavailable_code_cannot_be_included_in_new_run(self):
        self.data["discovery_policy"] = 1
        self.candidate.update(deck_code_status="unavailable")
        self.candidate.pop("deck_code")
        with self.assertRaisesRegex(ValueError, "verified deck code required"):
            validate(self.data, self.run)
