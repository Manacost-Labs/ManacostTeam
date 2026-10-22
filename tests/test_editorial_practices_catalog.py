import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EditorialPracticesCatalogTest(unittest.TestCase):
    def test_shared_catalog_and_portable_resources(self):
        canonical = ROOT / "editor/src/editorteam/editorial_practices.json"
        embedded = ROOT / "editor/go/internal/editorialreview/practices.json"
        self.assertEqual(canonical.read_bytes(), embedded.read_bytes())
        data = json.loads(canonical.read_text(encoding="utf-8"))
        self.assertEqual(26, len(data["practices"]))
        self.assertEqual(26, len({row["section"] for row in data["practices"]}))
        expected = {
            "2.1": "significance", "2.2": "source_use", "2.3": "substance", "2.4": "promotion",
            "2.5": "didactic", "2.6": "conclusions", "2.7": "outlook", "2.8": "title_entity",
            "3.1": "links", "3.2": "bibliography", "3.3": "tracking",
            "4.1": "dialogue", "4.2": "knowledge_gaps", "4.3": "placeholders",
            "5.1": "participles", "5.2": "parallelism", "5.3": "triples", "5.4": "attribution",
            "5.5": "references", "5.6": "ranges", "6.1": "markup", "6.2": "categories",
            "7.1": "capitalization", "7.2": "bold", "7.3": "lists", "7.4": "dashes",
        }
        self.assertEqual(expected, {row["section"]: row["id"] for row in data["practices"]})
        self.assertEqual("https://ru.wikipedia.org/w/index.php?oldid=155487940", data["source_url"])
        registry = json.loads((ROOT / "teams/registry.json").read_text(encoding="utf-8"))
        publish = next(s for s in registry["skills"] if s["name"] == "manacost-publish")
        resources = {r["destination"] for r in publish["resources"]}
        self.assertTrue({"python/editorteam/editorial_practices.py", "python/editorteam/editorial_practices.json", "references/editorial-practices.md"} <= resources)
