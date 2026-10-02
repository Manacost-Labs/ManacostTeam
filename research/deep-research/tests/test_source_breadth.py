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
        self.assertEqual(report["platforms"]["x"]["duplicate_source_ids"], ["S2"])
        self.assertEqual(report["unlinked_inspected_source_ids"], [])
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

    def test_share_urls_and_timestamps_count_one_original_per_platform(self):
        from platform_coverage import analyze_records

        variants = {
            "youtube": [
                "https://www.youtube.com/watch?v=Video_A&t=10",
                "https://youtu.be/Video_A?si=share&t=20",
                "https://m.youtube.com/shorts/Video_A",
                "https://www.youtube.com/embed/Video_A",
                "https://www.youtube.com/live/Video_A?feature=share",
                "https://www.youtube.com/watch?v=Video_B",
            ],
            "x": [
                "https://x.com/author/status/123?s=20",
                "https://twitter.com/author/status/123#reply",
                "https://mobile.twitter.com/author/status/123/photo/1",
                "https://x.com/i/web/status/123",
                "https://x.com/other/status/124",
            ],
            "reddit": [
                "https://www.reddit.com/r/test/comments/abc123/title/",
                "https://old.reddit.com/r/test/comments/abc123/title/comment/",
                "https://redd.it/abc123",
                "https://www.reddit.com/comments/abc123?utm_source=share",
                "https://www.reddit.com/r/test/comments/abc124/other/",
            ],
        }
        for platform, urls in variants.items():
            with self.subTest(platform=platform):
                sources = [
                    {
                        "source_id": f"S{index}",
                        "url": url,
                        "access_integrity": "full",
                        "found_by_query_ids": ["Q1", "Q2"],
                    }
                    for index, url in enumerate(urls)
                ]
                queries = [
                    {
                        "query_id": identity,
                        "family": platform,
                        "status": "completed",
                        "executed_at": "2026-10-03",
                    }
                    for identity in ["Q1", "Q2"]
                ]
                report = analyze_records(queries, sources, required=[platform])
                lane = report["platforms"][platform]
                self.assertEqual(lane["inspected_sources"], 2)
                self.assertEqual(len(lane["duplicate_source_ids"]), len(urls) - 2)
                self.assertEqual(report["unlinked_inspected_source_ids"], [])

    def test_general_web_query_parameters_are_preserved(self):
        from platform_coverage import inspection_identity

        first = "https://example.com/data?patch=1"
        second = "https://example.com/data?patch=2"
        self.assertNotEqual(inspection_identity(first), inspection_identity(second))

    def test_no_results_with_forward_or_reverse_source_links_is_invalid(self):
        from platform_coverage import analyze_records

        query = {
            "query_id": "Q1",
            "family": "youtube",
            "status": "no_results",
            "executed_at": "2026-10-03",
        }
        source = {
            "source_id": "S1",
            "url": "https://youtu.be/Video_A",
            "access_integrity": "transcript",
        }
        for forward in [True, False]:
            with self.subTest(forward=forward):
                q = {**query, "result_source_ids": ["S1"]} if forward else query
                s = source if forward else {**source, "found_by_query_ids": ["Q1"]}
                with self.assertRaisesRegex(ValueError, "no_results query cannot link"):
                    analyze_records([q], [s], required=["youtube"])
        report = analyze_records([query], [], required=["youtube"])
        self.assertEqual(report["verdict"], "partial")
        self.assertEqual(report["platforms"]["youtube"]["executed_queries"], 1)

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
