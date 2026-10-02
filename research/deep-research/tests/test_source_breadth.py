import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import plan_queries


class SourceBreadthTests(unittest.TestCase):
    def test_each_platform_query_stays_on_its_platform_in_both_languages(self):
        records = plan_queries.build_plan(
            branches=[("SEC-01", "Hearthstone Arena")],
            families=["x", "reddit", "youtube"],
            languages=["en", "ru"],
            entities=["Test Player"],
            markers=["36.6"],
            year="2026",
            existing_queries=[],
            existing_ids=set(),
            coverage_enabled=True,
        )
        expected = {
            "x": ("site:x.com", "site:twitter.com"),
            "reddit": ("site:reddit.com",),
            "youtube": ("site:youtube.com",),
        }
        for record in records:
            self.assertTrue(
                any(site in record["query"] for site in expected[record["family"]]),
                record,
            )
            self.assertEqual(record["target_platform"], record["family"])
            self.assertEqual(record["deliverable_section_ids"], ["SEC-01"])
        for language in ["en", "ru"]:
            for family in expected:
                self.assertGreaterEqual(
                    sum(
                        r["language"] == language and r["family"] == family
                        for r in records
                    ),
                    3,
                )

    def test_coverage_does_not_count_planned_queries_or_snippets_as_inspection(self):
        from platform_coverage import analyze_records

        report = analyze_records(
            [
                {"query_id": "Q1", "family": "x", "status": "planned"},
                {
                    "query_id": "Q2",
                    "result_source_ids": ["S1"],
                    "family": "reddit",
                    "status": "completed",
                    "executed_at": "2026-10-03",
                },
            ],
            [
                {
                    "source_id": "S1",
                    "url": "https://reddit.com/r/hearthstone/comments/test",
                    "access_integrity": "snippet",
                },
                {
                    "source_id": "S2",
                    "url": "https://www.youtube.com/watch?v=test",
                    "access_integrity": "full_text",
                },
            ],
            required=["x", "reddit", "youtube"],
        )
        self.assertEqual(report["platforms"]["x"]["executed_queries"], 0)
        self.assertEqual(report["platforms"]["reddit"]["inspected_sources"], 0)
        self.assertEqual(report["platforms"]["youtube"]["inspected_sources"], 0)
        self.assertEqual(report["unlinked_inspected_source_ids"], ["S2"])
        self.assertEqual(report["verdict"], "partial")

    def test_inspection_must_link_to_the_same_section_language_and_platform(self):
        from platform_coverage import analyze_records

        queries = [
            {
                "query_id": "Q1",
                "family": "reddit",
                "status": "completed",
                "executed_at": "2026-10-03T12:00:00Z",
                "language": "en",
                "deliverable_section_ids": ["SEC-1"],
                "result_source_ids": ["S1"],
            }
        ]
        sources = [
            {
                "source_id": "S1",
                "final_url": "https://reddit.com/r/test/comments/1",
                "access_integrity": "full",
            }
        ]
        report = analyze_records(
            queries,
            sources,
            required=["reddit"],
            sections=["SEC-1", "SEC-2"],
            languages=["en", "ru"],
        )
        self.assertEqual(report["platforms"]["reddit"]["inspected_sources"], 1)
        self.assertEqual(len(report["gap_details"]), 3)
        self.assertEqual(report["verdict"], "partial")
        sources[0]["final_url"] = "https://www.youtube.com/watch?v=1"
        self.assertEqual(
            analyze_records(queries, sources, required=["reddit"])["verdict"], "partial"
        )

    def test_source_backlinks_work_and_duplicate_urls_do_not_inflate_counts(self):
        from platform_coverage import analyze_records

        queries = [
            {
                "query_id": "Q1",
                "family": "x",
                "status": "completed",
                "executed_at": "2026-10-03T12:00:00Z",
            }
        ]
        sources = [
            {
                "source_id": identity,
                "url": "https://x.com/test/status/1" + fragment,
                "access_integrity": "full",
                "found_by_query_ids": ["Q1"],
            }
            for identity, fragment in [("S1", ""), ("S2", "#reply")]
        ]
        report = analyze_records(queries, sources, required=["x"])
        self.assertEqual(report["verdict"], "covered")
        self.assertEqual(report["platforms"]["x"]["inspected_sources"], 1)
        queries[0]["status"] = "blocked"
        report = analyze_records(queries, sources, required=["x"])
        self.assertEqual(report["platforms"]["x"]["inspected_sources"], 0)
        self.assertEqual(report["gap_details"][0]["failed_queries"], 1)

    def test_duplicate_ids_and_broken_links_are_invalid(self):
        from platform_coverage import analyze_records

        query = {"query_id": "Q1", "family": "x", "status": "planned"}
        with self.assertRaisesRegex(ValueError, "duplicate query_id"):
            analyze_records([query, query], [], required=["x"])
        with self.assertRaisesRegex(ValueError, "unknown source"):
            analyze_records(
                [{**query, "result_source_ids": ["absent"]}], [], required=["x"]
            )
        with self.assertRaisesRegex(ValueError, "unknown query"):
            analyze_records(
                [],
                [{"source_id": "S1", "found_by_query_ids": ["absent"]}],
                required=["x"],
            )

    def test_malformed_json_has_a_controlled_line_number(self):
        import tempfile

        from platform_coverage import read_ledger

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sources.jsonl"
            path.write_text("{}\n{broken\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sources.jsonl:2: malformed JSON"):
                read_ledger(path)


if __name__ == "__main__":
    unittest.main()
