import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main
from fastapi import HTTPException

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
from resolve_context import resolve_context  # noqa: E402


class TranslationContextTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data = Path(self.temporary.name)
        self.override = patch.object(main, "DATA_DIR", self.data)
        self.override.start()
        self.addCleanup(self.override.stop)
        (self.data / "hearthstone-names.en-ru.tsv").write_text(
            "Shared Name\tИмя HS\tbuild=123\n", encoding="utf-8"
        )
        (self.data / "world-of-warcraft-names.en-ru.tsv").write_text(
            "Shared Name\tИмя WoW\tproduct=retail; build=123\n"
            "Other Name\tДругой продукт\tproduct=classic-era; build=123\n"
            "Old Name\tСтарая сборка\tproduct=retail; build=122\n",
            encoding="utf-8",
        )

    def context(self, game="hearthstone", profile="manacost", build="123"):
        return resolve_context(REPO, game=game, profile=profile, patch=build)

    def test_legacy_prepare_keeps_shape_defaults_and_legacy_memory(self):
        main.append_translation_memory(
            main.memory_path(), "Plain text.", "Старый перевод.", ""
        )
        result = main.prepare_material(
            "Plain text.", main.PrepareRequest(text="Plain text.")
        )
        self.assertEqual(result["context"]["game"], "wow")
        self.assertNotIn("task_context", result)
        self.assertEqual(result["segments"][0]["memory_match"], "Старый перевод.")

    def test_game_product_and_build_isolate_glossaries(self):
        hs = main.prepare_material(
            "Shared Name", main.PrepareRequest(task_context=self.context())
        )
        wow = main.prepare_material(
            "Shared Name and Other Name and Old Name",
            main.PrepareRequest(
                task_context=self.context("world-of-warcraft"), product="retail"
            ),
        )
        self.assertEqual(list(hs["terms"].values()), ["Имя HS"])
        self.assertEqual(list(wow["terms"].values()), ["Имя WoW"])
        self.assertIn("Other Name", wow["protected_markdown"])
        self.assertIn("Old Name", wow["protected_markdown"])
        self.assertEqual(wow["task_context"]["game"]["id"], "world-of-warcraft")

    def test_memory_does_not_cross_games_profiles_products_or_builds(self):
        import asyncio

        asyncio.run(
            main.approve_memory(
                main.MemoryRequest(
                    source_en="Plain text.",
                    target_ru="Только HS.",
                    task_context=self.context(),
                )
            )
        )
        matching = main.prepare_material(
            "Plain text.", main.PrepareRequest(task_context=self.context())
        )
        self.assertEqual(matching["segments"][0]["memory_match"], "Только HS.")
        for supplied in (
            {"task_context": self.context("world-of-warcraft"), "product": "retail"},
            {"task_context": self.context(profile="neutral")},
            {"task_context": self.context(build="124")},
        ):
            with self.subTest(supplied=supplied):
                result = main.prepare_material(
                    "Plain text.", main.PrepareRequest(**supplied)
                )
                self.assertIsNone(result["segments"][0]["memory_match"])

    def test_conflicts_and_invalid_context_fail_without_memory_writes(self):
        import asyncio

        wrong = self.context()
        wrong["schema_version"] = 2
        for supplied in (
            {"task_context": self.context(), "game": "wow"},
            {"task_context": self.context(), "patch": "different"},
            {"task_context": wrong},
            {"task_context": None},
            {"task_context": self.context("world-of-warcraft")},
        ):
            with (
                self.subTest(supplied=supplied),
                self.assertRaises(HTTPException) as raised,
            ):
                main.prepare_material("Plain text.", main.PrepareRequest(**supplied))
            self.assertEqual(raised.exception.status_code, 422)
        with self.assertRaises(HTTPException):
            asyncio.run(
                main.approve_memory(
                    main.MemoryRequest(
                        source_en="Before", target_ru="After", task_context=wrong
                    )
                )
            )
        self.assertFalse((self.data / "memory").exists())

    def test_missing_glossary_is_reported_without_fabricating_terms(self):
        result = main.prepare_material(
            "Shared Name", main.PrepareRequest(task_context=self.context(build="999"))
        )
        self.assertEqual(result["terms"], {})
        self.assertIn("glossary_unavailable", result["resource_warnings"])

    def test_http_rejects_invalid_context_before_fetch_and_supports_wow_alias(self):
        from fastapi.testclient import TestClient

        with TestClient(main.app) as client, patch.object(main, "fetch_html") as fetch:
            invalid = client.post(
                "/prepare", json={"url": "https://example.com/", "task_context": None}
            )
            self.assertEqual(invalid.status_code, 422)
            fetch.assert_not_called()
            valid = client.post(
                "/prepare",
                json={
                    "text": "Shared Name",
                    "task_context": self.context("world-of-warcraft"),
                    "game": "wow",
                    "product": "retail",
                },
            )
            self.assertEqual(valid.status_code, 200)
            self.assertEqual(list(valid.json()["terms"].values()), ["Имя WoW"])

    def test_memory_isolates_wow_products(self):
        import asyncio

        metadata = self.context("world-of-warcraft")
        asyncio.run(
            main.approve_memory(
                main.MemoryRequest(
                    source_en="Plain text.",
                    target_ru="Только retail.",
                    task_context=metadata,
                    product="retail",
                )
            )
        )
        other = main.prepare_material(
            "Plain text.",
            main.PrepareRequest(task_context=metadata, product="classic-era"),
        )
        self.assertIsNone(other["segments"][0]["memory_match"])

    def test_glossary_update_invalidates_old_marker_memory(self):
        import asyncio

        asyncio.run(
            main.approve_memory(
                main.MemoryRequest(
                    source_en="[[[TERM_1]]]",
                    target_ru="Имя HS",
                    task_context=self.context(),
                )
            )
        )
        matching = main.prepare_material(
            "Shared Name", main.PrepareRequest(task_context=self.context())
        )
        self.assertEqual(matching["segments"][0]["memory_match"], "Имя HS")
        (self.data / "hearthstone-names.en-ru.tsv").write_text(
            "Shared Name\tНовое имя\tbuild=123\n", encoding="utf-8"
        )
        updated = main.prepare_material(
            "Shared Name", main.PrepareRequest(task_context=self.context())
        )
        self.assertIsNone(updated["segments"][0]["memory_match"])


if __name__ == "__main__":
    unittest.main()
