import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from editorteam.editorial_lab import assemble_mcp_chunks, blind_cases, review_summary


def chunk(offset, text, next_offset, length=6, access="full"):
    return {
        "request": {"id": "one", "textOffset": offset},
        "response": {
            "retrievedAt": "2026-10-10T00:00:00Z",
            "data": {
                "id": "one",
                "url": "https://example.org/article",
                "title": "Статья",
                "source": "koloda",
                "text": text,
                "textLength": length,
                "nextOffset": next_offset,
                "metadata": {"access": access},
            },
        },
    }


class EditorialLabTests(unittest.TestCase):
    def test_only_complete_chunk_chains_become_candidates(self):
        articles = assemble_mcp_chunks([chunk(0, "abc", 3), chunk(3, "def", None)])
        self.assertEqual(articles[0]["text"], "abcdef")
        self.assertEqual(articles[0]["review_status"], "candidate")
        for pages in (
            [chunk(3, "def", None)],
            [chunk(0, "abc", 3)],
            [chunk(0, "abc", None)],
            [chunk(0, "abcdef", None, access="excerpt")],
        ):
            with self.assertRaises(ValueError):
                assemble_mcp_chunks(pages)

    def test_utf16_offsets_and_duplicate_chunks(self):
        self.assertEqual(
            assemble_mcp_chunks([chunk(0, "😀", 2, 3), chunk(2, "x", None, 3)])[0]["text"], "😀x"
        )
        with self.assertRaises(ValueError):
            assemble_mcp_chunks([chunk(0, "abc", 3), chunk(0, "abc", 3)])
        unsafe = chunk(0, "abcdef", None)
        unsafe["response"]["data"]["url"] = "https://:example-password@example.org/article"
        with self.assertRaises(ValueError):
            assemble_mcp_chunks([unsafe])

    def test_blind_ids_hide_variant_and_require_complete_pairs(self):
        rows = [
            {"case_id": "case", "variant": "baseline", "text": "Исходный вариант", "patch": "test"},
            {"case_id": "case", "variant": "candidate", "text": "Новый вариант", "patch": "test"},
        ]
        packet, key = blind_cases(rows, seed=17)
        self.assertEqual(len(packet), 2)
        self.assertNotIn("variant", packet[0])
        self.assertEqual({r["variant"] for r in key}, {"baseline", "candidate"})
        with self.assertRaises(ValueError):
            blind_cases(rows[:1], seed=17)

    def test_unreviewed_samples_never_get_a_quality_score(self):
        summary = review_summary(
            [{"case_id": "one", "variant": "candidate", "review_status": "pending"}]
        )
        self.assertIsNone(summary["editor_minutes"])
        self.assertIsNone(summary["critical_errors"])
        with self.assertRaises(ValueError):
            review_summary(
                [
                    {
                        "case_id": "one",
                        "variant": "candidate",
                        "review_status": "reviewed",
                        "editor_minutes": -1,
                        "critical_errors": 0,
                    }
                ]
            )


if __name__ == "__main__":
    unittest.main()
