import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import source_gateway  # noqa: E402


class SourceGatewayCommandTest(unittest.TestCase):
    def test_youtube_search_is_bounded_and_schema_validated(self) -> None:
        argv = source_gateway.command_argv(
            {
                "command": "youtube-search",
                "options": {"query": "Hearthstone guide", "limit": 5},
            }
        )
        self.assertEqual(
            argv,
            ["youtube-search", "--query", "Hearthstone guide", "--limit", "5"],
        )
        with self.assertRaisesRegex(ValueError, "between 1 and 50"):
            source_gateway.command_argv(
                {
                    "command": "youtube-search",
                    "options": {"query": "Hearthstone guide", "limit": 51},
                }
            )

    def test_youtube_transcript_exposes_no_translation_cost_switch(self) -> None:
        argv = source_gateway.command_argv(
            {
                "command": "youtube-transcript",
                "options": {
                    "video": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                    "language": "en",
                    "translate_to": "ru",
                },
            }
        )
        self.assertEqual(
            argv,
            [
                "youtube-transcript",
                "--video",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "--language",
                "en",
            ],
        )

    def test_named_dataset_route_accepts_only_plain_source_ids(self) -> None:
        argv = source_gateway.command_argv(
            {
                "command": "stats-api",
                "options": {
                    "operation": "dataset",
                    "source_id": "metastats_matchups",
                },
            }
        )
        self.assertEqual(
            argv,
            [
                "stats-api",
                "--operation",
                "dataset",
                "--source-id",
                "metastats_matchups",
                "--limit",
                "50",
                "--offset",
                "0",
            ],
        )
        with self.assertRaisesRegex(ValueError, "source_id"):
            source_gateway.command_argv(
                {
                    "command": "stats-api",
                    "options": {
                        "operation": "dataset",
                        "source_id": "../../admin",
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
